#![cfg_attr(
    all(not(debug_assertions), target_os = "windows"),
    windows_subsystem = "windows"
)]

use sha2::{Digest, Sha256};
use std::{
    collections::HashMap,
    env, fs, io,
    io::{Read, Write},
    net::{TcpListener, TcpStream},
    path::{Path, PathBuf},
    process::{Child, Command, Stdio},
    sync::Mutex,
    thread,
    time::Duration,
};

#[cfg(windows)]
use std::os::windows::process::CommandExt;

use tauri::{
    CustomMenuItem, Manager, SystemTray, SystemTrayEvent, SystemTrayMenu, SystemTrayMenuItem,
    WindowEvent, WindowUrl,
};

#[derive(Default)]
struct BackendState {
    child: Mutex<Option<Child>>,
    owns_backend: Mutex<bool>,
}

struct LaunchInfo {
    port: u16,
    preferred_port: u16,
    port_switched: bool,
    root: PathBuf,
}

impl Drop for BackendState {
    fn drop(&mut self) {
        if let Ok(owns) = self.owns_backend.lock() {
            if !*owns {
                return;
            }
        }
        if let Ok(mut guard) = self.child.lock() {
            if let Some(mut child) = guard.take() {
                let _ = child.kill();
                let _ = child.wait();
            }
        }
    }
}

fn has_server(root: &Path) -> bool {
    root.join("server").join("app.py").is_file()
}

fn macos_support_app_root() -> Option<PathBuf> {
    if !cfg!(target_os = "macos") {
        return None;
    }
    if let Ok(raw) = env::var("CAPTAIN_MACOS_SUPPORT_DIR") {
        return Some(PathBuf::from(raw).join("app"));
    }
    env::var_os("HOME").map(|home| {
        PathBuf::from(home)
            .join("Library")
            .join("Application Support")
            .join("Captain")
            .join("app")
    })
}

fn macos_resource_app_roots() -> Vec<PathBuf> {
    let mut roots = Vec::new();
    if !cfg!(target_os = "macos") {
        return roots;
    }
    if let Ok(exe) = env::current_exe() {
        if let Some(contents_dir) = exe.parent().and_then(Path::parent) {
            let resources = contents_dir.join("Resources");
            roots.push(resources.join("app"));
            roots.push(resources.join("resources").join("app"));
        }
    }
    roots
}

fn windows_support_app_root() -> Option<PathBuf> {
    if !cfg!(target_os = "windows") {
        return None;
    }
    if let Ok(raw) = env::var("CAPTAIN_WINDOWS_SUPPORT_DIR") {
        return Some(PathBuf::from(raw).join("app"));
    }
    env::var_os("LOCALAPPDATA").map(|local| PathBuf::from(local).join("Captain").join("app"))
}

fn windows_resource_app_roots() -> Vec<PathBuf> {
    let mut roots = Vec::new();
    if !cfg!(target_os = "windows") {
        return roots;
    }
    if let Ok(exe) = env::current_exe() {
        if let Some(exe_dir) = exe.parent() {
            roots.push(exe_dir.join("resources").join("app"));
            roots.push(exe_dir.join("_up_").join("resources").join("app"));
            roots.push(exe_dir.join("app"));
        }
    }
    roots
}

fn copy_dir_preserving_symlinks(src: &Path, dst: &Path) -> io::Result<()> {
    fs::create_dir_all(dst)?;
    for entry in fs::read_dir(src)? {
        let entry = entry?;
        let src_path = entry.path();
        let dst_path = dst.join(entry.file_name());
        let file_type = entry.file_type()?;

        if file_type.is_dir() {
            copy_dir_preserving_symlinks(&src_path, &dst_path)?;
        } else if file_type.is_symlink() {
            let target = fs::read_link(&src_path)?;
            #[cfg(unix)]
            {
                let _ = fs::remove_file(&dst_path);
                std::os::unix::fs::symlink(target, &dst_path)?;
            }
            #[cfg(not(unix))]
            {
                fs::copy(&src_path, &dst_path)?;
            }
        } else if file_type.is_file() {
            if let Some(parent) = dst_path.parent() {
                fs::create_dir_all(parent)?;
            }
            fs::copy(&src_path, &dst_path)?;
            let permissions = fs::metadata(&src_path)?.permissions();
            fs::set_permissions(&dst_path, permissions)?;
        }
    }
    Ok(())
}

fn should_preserve_support_entry(path: &Path) -> bool {
    matches!(
        path.file_name().and_then(|name| name.to_str()),
        Some(".env" | ".venv" | "data" | "logs" | "uploads")
    )
}

fn file_text(path: &Path) -> String {
    fs::read_to_string(path)
        .unwrap_or_default()
        .trim()
        .to_string()
}

fn parse_bundle_stamp(root: &Path) -> HashMap<String, String> {
    let mut values = HashMap::new();
    for line in file_text(&root.join(".captain_bundle_stamp")).lines() {
        if let Some((key, value)) = line.split_once('=') {
            values.insert(key.trim().to_string(), value.trim().to_string());
        }
    }
    values
}

fn stamp_manifest_hash(stamp: &HashMap<String, String>) -> String {
    let mut keys = stamp
        .keys()
        .filter(|key| key.as_str() != "manifest_hash")
        .collect::<Vec<_>>();
    keys.sort();
    let canonical = keys
        .into_iter()
        .map(|key| format!("{key}={}\n", stamp.get(key).unwrap_or(&String::new())))
        .collect::<String>();
    format!("{:x}", Sha256::digest(canonical.as_bytes()))
}

fn stamp_integrity_valid(stamp: &HashMap<String, String>) -> bool {
    stamp
        .get("manifest_hash")
        .map(|expected| expected == &stamp_manifest_hash(stamp))
        .unwrap_or(false)
}

fn version_parts(raw: &str) -> Option<(u64, u64, u64)> {
    let core = raw.split(['-', '+']).next()?;
    let mut parts = core.split('.');
    let major = parts.next()?.parse().ok()?;
    let minor = parts.next()?.parse().ok()?;
    let patch = parts.next()?.parse().ok()?;
    if parts.next().is_some() {
        return None;
    }
    Some((major, minor, patch))
}

fn stamp_is_trusted(stamp: &HashMap<String, String>) -> bool {
    matches!(
        stamp.get("trust").map(String::as_str),
        Some("platform-signed" | "tauri-signed")
    ) && stamp.get("stamp_schema").map(String::as_str) == Some("1")
        && stamp_integrity_valid(stamp)
}

fn support_needs_bundle_refresh(support_root: &Path, resource_root: &Path) -> bool {
    let resource = parse_bundle_stamp(resource_root);
    if !has_server(support_root) {
        return resource.get("stamp_schema").map(String::as_str) == Some("1")
            && stamp_integrity_valid(&resource);
    }
    if !stamp_is_trusted(&resource) {
        return false;
    }
    let support = parse_bundle_stamp(support_root);
    if support.is_empty() {
        return true;
    }
    let resource_version = resource
        .get("version")
        .and_then(|value| version_parts(value));
    let support_version = support
        .get("version")
        .and_then(|value| version_parts(value));
    match (resource_version, support_version) {
        (Some(new), Some(old)) if new > old => true,
        (Some(new), Some(old)) if new < old => false,
        (Some(_), Some(_)) => {
            let newer_build = resource.get("built_at") > support.get("built_at");
            let changed = resource.get("manifest_hash") != support.get("manifest_hash");
            newer_build && changed
        }
        (Some(_), None) => true,
        _ => false,
    }
}

fn remove_path(path: &Path) -> io::Result<()> {
    if !path.exists() {
        return Ok(());
    }
    if path.is_dir() && !path.is_symlink() {
        fs::remove_dir_all(path)
    } else {
        fs::remove_file(path)
    }
}

fn refresh_support_atomically(resource_root: &Path, support_root: &Path) -> io::Result<()> {
    let parent = support_root.parent().ok_or_else(|| {
        io::Error::new(
            io::ErrorKind::InvalidInput,
            "support directory has no parent",
        )
    })?;
    fs::create_dir_all(parent)?;
    let suffix = format!("{}-{}", std::process::id(), chrono_like_timestamp());
    let stage = parent.join(format!(".captain-app-next-{suffix}"));
    let backup = parent.join(format!(".captain-app-previous-{suffix}"));
    remove_path(&stage)?;
    remove_path(&backup)?;
    copy_dir_preserving_symlinks(resource_root, &stage)?;

    if !support_root.exists() {
        return fs::rename(stage, support_root);
    }

    fs::rename(support_root, &backup)?;
    if let Err(err) = fs::rename(&stage, support_root) {
        let _ = fs::rename(&backup, support_root);
        return Err(err);
    }

    let mut moved = Vec::new();
    let mut move_error = None;
    for entry in fs::read_dir(&backup)? {
        let entry = entry?;
        let old_path = entry.path();
        if !should_preserve_support_entry(&old_path) {
            continue;
        }
        let new_path = support_root.join(entry.file_name());
        if let Err(err) = remove_path(&new_path).and_then(|_| fs::rename(&old_path, &new_path)) {
            move_error = Some(err);
            break;
        }
        moved.push(entry.file_name());
    }

    if let Some(err) = move_error {
        for name in moved.into_iter().rev() {
            let _ = fs::rename(support_root.join(&name), backup.join(&name));
        }
        let _ = remove_path(support_root);
        let _ = fs::rename(&backup, support_root);
        return Err(err);
    }

    remove_path(&backup)?;
    Ok(())
}

fn random_hex(bytes: usize) -> io::Result<String> {
    let mut buf = vec![0_u8; bytes];
    match fs::File::open("/dev/urandom").and_then(|mut f| f.read_exact(&mut buf)) {
        Ok(()) => {}
        Err(_) => {
            let seed = format!(
                "{}:{}:{:?}",
                std::process::id(),
                chrono_like_timestamp(),
                env::current_exe().ok()
            );
            for (idx, byte) in buf.iter_mut().enumerate() {
                *byte = seed.as_bytes()[idx % seed.len()].wrapping_add(idx as u8);
            }
        }
    }
    Ok(buf.iter().map(|b| format!("{:02x}", b)).collect())
}

fn chrono_like_timestamp() -> u128 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_nanos())
        .unwrap_or(0)
}

fn macos_keychain_get(account: &str) -> Option<String> {
    if !cfg!(target_os = "macos") {
        return None;
    }
    let output = Command::new("security")
        .arg("find-generic-password")
        .arg("-s")
        .arg("club.irestart.captain")
        .arg("-a")
        .arg(account)
        .arg("-w")
        .output()
        .ok()?;
    if !output.status.success() {
        return None;
    }
    let value = String::from_utf8_lossy(&output.stdout).trim().to_string();
    if value.is_empty() {
        None
    } else {
        Some(value)
    }
}

fn macos_keychain_set(account: &str, value: &str) -> bool {
    if !cfg!(target_os = "macos") {
        return false;
    }
    Command::new("security")
        .arg("add-generic-password")
        .arg("-U")
        .arg("-s")
        .arg("club.irestart.captain")
        .arg("-a")
        .arg(account)
        .arg("-w")
        .arg(value)
        .status()
        .map(|status| status.success())
        .unwrap_or(false)
}

fn default_workspace_fallback(root: &Path) -> String {
    if cfg!(windows) {
        env::var("USERPROFILE").unwrap_or_else(|_| root.display().to_string())
    } else {
        env::var("HOME").unwrap_or_else(|_| root.display().to_string())
    }
}

fn platform_secret_lines() -> io::Result<String> {
    if cfg!(target_os = "macos") {
        let auth_secret = ensure_macos_keychain_secret("env:AUTH_SECRET", 32);
        let api_token = ensure_macos_keychain_secret("env:AGENT_API_TOKEN", 32);
        if auth_secret.is_some() && api_token.is_some() {
            return Ok(
                "CAPTAIN_USE_KEYCHAIN=1\n# AUTH_SECRET and AGENT_API_TOKEN are stored in macOS Keychain.\n"
                    .to_string(),
            );
        }
        return Ok(format!(
            "AUTH_SECRET={auth_secret}\nAGENT_API_TOKEN={api_token}\n",
            auth_secret = auth_secret.unwrap_or(random_hex(32)?),
            api_token = api_token.unwrap_or(random_hex(32)?),
        ));
    }

    Ok(format!(
        "AUTH_SECRET={auth_secret}\nAGENT_API_TOKEN={api_token}\n",
        auth_secret = random_hex(32)?,
        api_token = random_hex(32)?,
    ))
}

fn platform_env_header() -> &'static str {
    if cfg!(target_os = "macos") {
        "# Captain macOS local config\n"
    } else if cfg!(target_os = "windows") {
        "# Captain Windows local config\n"
    } else {
        "# Captain local config\n"
    }
}

fn ensure_macos_keychain_secret(account: &str, bytes: usize) -> Option<String> {
    if let Some(value) = macos_keychain_get(account) {
        return Some(value);
    }
    let value = random_hex(bytes).ok()?;
    if macos_keychain_set(account, &value) {
        Some(value)
    } else {
        None
    }
}

fn ensure_default_env(root: &Path) -> io::Result<()> {
    let env_path = root.join(".env");
    if env_path.exists() {
        return Ok(());
    }
    let workspace = default_workspace_fallback(root);
    let secret_lines = platform_secret_lines()?;
    let content = format!(
        "{header}\
AGENT_PROVIDER=deepseek\n\
AGENT_MODEL=deepseek-v4-flash\n\
AGENT_WEB_PORT=8000\n\
AGENT_WORKSPACE_ROOT={workspace}\n\
CAPTAIN_LICENSE_KEY=\n\
{secret_lines}\
\n\
# Fill your model key before using real models.\n\
DEEPSEEK_API_KEY=\n",
        header = platform_env_header(),
        workspace = workspace,
        secret_lines = secret_lines,
    );
    let mut file = fs::File::create(&env_path)?;
    file.write_all(content.as_bytes())?;
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        fs::set_permissions(&env_path, fs::Permissions::from_mode(0o600))?;
    }
    Ok(())
}

fn ensure_support_from_bundle(
    support_root: Option<PathBuf>,
    resource_roots: Vec<PathBuf>,
) -> io::Result<Option<PathBuf>> {
    let Some(support_root) = support_root else {
        return Ok(None);
    };

    for resource_root in resource_roots {
        if has_server(&resource_root) {
            if support_needs_bundle_refresh(&support_root, &resource_root) {
                refresh_support_atomically(&resource_root, &support_root)?;
            }
            if has_server(&support_root) {
                ensure_default_env(&support_root)?;
                return Ok(Some(support_root));
            }
            if cfg!(debug_assertions) {
                ensure_default_env(&resource_root)?;
                return Ok(Some(resource_root));
            }
        }
    }

    if has_server(&support_root) {
        ensure_default_env(&support_root)?;
        return Ok(Some(support_root));
    }

    Ok(None)
}

fn ensure_macos_support_from_bundle() -> io::Result<Option<PathBuf>> {
    if !cfg!(target_os = "macos") {
        return Ok(None);
    }
    ensure_support_from_bundle(macos_support_app_root(), macos_resource_app_roots())
}

fn ensure_windows_support_from_bundle() -> io::Result<Option<PathBuf>> {
    if !cfg!(target_os = "windows") {
        return Ok(None);
    }
    ensure_support_from_bundle(windows_support_app_root(), windows_resource_app_roots())
}

fn dev_project_roots() -> Vec<PathBuf> {
    let mut candidates = Vec::new();

    for key in ["CAPTAIN_PROJECT_ROOT", "AGENT_PROJECT_ROOT"] {
        if let Ok(raw) = env::var(key) {
            candidates.push(PathBuf::from(raw));
        }
    }

    let dev_root = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .and_then(Path::parent)
        .map(Path::to_path_buf);
    if let Some(root) = dev_root {
        candidates.push(root);
    }

    if let Ok(current) = env::current_dir() {
        candidates.push(current);
    }

    candidates
}

fn packaged_project_roots() -> Vec<PathBuf> {
    let mut candidates = Vec::new();
    if cfg!(target_os = "macos") {
        if let Some(root) = macos_support_app_root() {
            candidates.push(root);
        }
        candidates.extend(macos_resource_app_roots());
    }
    if cfg!(target_os = "windows") {
        if let Some(root) = windows_support_app_root() {
            candidates.push(root);
        }
        candidates.extend(windows_resource_app_roots());
    }
    candidates
}

fn project_root() -> Result<PathBuf, io::Error> {
    if cfg!(debug_assertions) {
        for candidate in dev_project_roots() {
            if has_server(&candidate) {
                ensure_default_env(&candidate)?;
                return Ok(candidate);
            }
        }
    }

    if let Some(root) = ensure_macos_support_from_bundle()? {
        if has_server(&root) {
            return Ok(root);
        }
    }

    if let Some(root) = ensure_windows_support_from_bundle()? {
        if has_server(&root) {
            return Ok(root);
        }
    }

    for candidate in dev_project_roots()
        .into_iter()
        .chain(packaged_project_roots())
    {
        if has_server(&candidate) {
            ensure_default_env(&candidate)?;
            return Ok(candidate);
        }
    }

    Err(io::Error::new(
        io::ErrorKind::NotFound,
        "找不到 Captain 后端目录。请重新安装 Captain, 或设置 CAPTAIN_PROJECT_ROOT。",
    ))
}

fn candidate_python_paths(root: &Path) -> Vec<PathBuf> {
    let mut candidates = Vec::new();

    if cfg!(windows) {
        candidates.push(root.join("runtime").join("python").join("python.exe"));
        candidates.push(root.join(".venv").join("Scripts").join("python.exe"));
        candidates.push(PathBuf::from("python"));
    } else {
        candidates.push(
            root.join("runtime")
                .join("python")
                .join("bin")
                .join("python3"),
        );
        candidates.push(root.join(".venv").join("bin").join("python"));
        candidates.push(PathBuf::from("python3"));
        candidates.push(PathBuf::from("python"));
    }

    candidates
}

fn resolve_python(root: &Path, packaged_python: Option<&Path>) -> PathBuf {
    if let Some(candidate) = packaged_python {
        if candidate.is_file() {
            return candidate.to_path_buf();
        }
    }
    for candidate in candidate_python_paths(root) {
        if candidate.components().count() == 1 || candidate.is_file() {
            return candidate;
        }
    }
    PathBuf::from(if cfg!(windows) { "python" } else { "python3" })
}

fn packaged_python_path(resource_dir: &Path) -> Option<PathBuf> {
    let executable = if cfg!(windows) {
        PathBuf::from("python.exe")
    } else {
        PathBuf::from("bin").join("python3")
    };
    [
        resource_dir.join("resources").join("app").join("runtime").join("python").join(&executable),
        resource_dir.join("app").join("runtime").join("python").join(&executable),
    ]
    .into_iter()
    .find(|candidate| candidate.is_file())
}

fn port_available(port: u16) -> bool {
    TcpListener::bind(("127.0.0.1", port)).is_ok()
}

fn process_alive(pid: u32) -> bool {
    Command::new("kill")
        .arg("-0")
        .arg(pid.to_string())
        .status()
        .map(|s| s.success())
        .unwrap_or(false)
}

fn gui_lock_path(root: &Path) -> PathBuf {
    support_log_dir(root).join(".captain.gui.lock")
}

/// 已有 Captain 窗口在跑则激活它并返回 false(当前进程应退出)。
fn ensure_single_gui_instance(root: &Path) -> bool {
    let lock = gui_lock_path(root);
    if lock.exists() {
        if let Ok(content) = fs::read_to_string(&lock) {
            if let Ok(pid) = content.trim().parse::<u32>() {
                if pid != std::process::id() && process_alive(pid) {
                    let _ = Command::new("open").arg("-a").arg("Captain").spawn();
                    return false;
                }
            }
        }
    }
    let _ = fs::write(&lock, std::process::id().to_string());
    true
}

fn release_gui_lock(root: &Path) {
    let lock = gui_lock_path(root);
    if lock.exists() {
        if let Ok(content) = fs::read_to_string(&lock) {
            if content.trim() == std::process::id().to_string() {
                let _ = fs::remove_file(&lock);
            }
        }
    }
}

fn diagnostics_value(port: u16, key: &str) -> Option<String> {
    let mut stream = TcpStream::connect(("127.0.0.1", port)).ok()?;
    stream.set_read_timeout(Some(Duration::from_secs(2))).ok()?;
    let req =
        "GET /api/system/diagnostics HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n";
    stream.write_all(req.as_bytes()).ok()?;
    let mut body = String::new();
    stream.read_to_string(&mut body).ok()?;
    let json = body.split("\r\n\r\n").nth(1).unwrap_or(&body);
    let needle = format!("\"{}\":\"", key);
    let start = json.find(&needle)? + needle.len();
    let rest = &json[start..];
    let end = rest.find('"')?;
    Some(rest[..end].to_string())
}

fn find_existing_backend(root: &Path) -> Option<u16> {
    let root_str = root.to_string_lossy();
    let log_str = root.join("logs").to_string_lossy().to_string();
    for port in 8000u16..=8099 {
        let same_root = diagnostics_value(port, "project_root")
            .map(|value| value == root_str)
            .unwrap_or(false);
        let same_data = diagnostics_value(port, "log_dir")
            .map(|value| value == log_str)
            .unwrap_or(false);
        if same_root || same_data {
            return Some(port);
        }
    }
    None
}

fn pick_port() -> (u16, u16, bool) {
    let preferred = env::var("AGENT_WEB_PORT")
        .ok()
        .and_then(|raw| raw.parse::<u16>().ok())
        .unwrap_or(8000);

    if port_available(preferred) {
        return (preferred, preferred, false);
    }

    let fallback = (8000..=8099)
        .find(|port| port_available(*port))
        .unwrap_or(preferred);
    (fallback, preferred, fallback != preferred)
}

fn wait_for_backend(port: u16) -> bool {
    for _ in 0..120 {
        if TcpStream::connect(("127.0.0.1", port)).is_ok() {
            return true;
        }
        thread::sleep(Duration::from_millis(100));
    }
    false
}

fn escape_js_string(raw: &str) -> String {
    raw.replace('\\', "\\\\")
        .replace('"', "\\\"")
        .replace('\n', "\\n")
        .replace('\r', "\\r")
}

fn app_version(root: &Path) -> String {
    let version = file_text(&root.join("VERSION"));
    if version.is_empty() {
        env!("CARGO_PKG_VERSION").to_string()
    } else {
        version
    }
}

fn bundle_stamp(root: &Path) -> String {
    file_text(&root.join(".captain_bundle_stamp"))
}

fn support_log_dir(root: &Path) -> PathBuf {
    root.parent()
        .map(Path::to_path_buf)
        .unwrap_or_else(|| root.to_path_buf())
}

fn open_logs_dir(root: &Path) {
    let dir = support_log_dir(root);
    if cfg!(target_os = "macos") {
        let _ = Command::new("open").arg(&dir).spawn();
    } else if cfg!(windows) {
        let _ = Command::new("explorer").arg(dir).spawn();
    } else {
        let _ = Command::new("xdg-open").arg(dir).spawn();
    }
}

fn diagnostic_summary(info: &LaunchInfo) -> String {
    let err_log = support_log_dir(&info.root).join("backend.err.log");
    format!(
        "Captain 诊断摘要\n版本: {}\nBundle stamp: {}\n期望端口: {}\n实际端口: {}\n端口已切换: {}\n项目目录: {}\n错误日志: {}",
        app_version(&info.root),
        bundle_stamp(&info.root),
        info.preferred_port,
        info.port,
        if info.port_switched { "是" } else { "否" },
        info.root.display(),
        err_log.display(),
    )
}

fn backend_error_page(info: &LaunchInfo) -> io::Result<PathBuf> {
    let log_dir = support_log_dir(&info.root);
    fs::create_dir_all(&log_dir)?;
    let path = log_dir.join("backend-start-error.html");
    let err_log = log_dir.join("backend.err.log");
    let summary = diagnostic_summary(info);
    let summary_json = format!("\"{}\"", escape_js_string(&summary));
    let port_note = if info.port_switched {
        format!(
            "期望端口 <code>{}</code> 已被占用，App 已尝试改用 <code>{}</code>，但后端仍未就绪。",
            info.preferred_port, info.port
        )
    } else {
        format!("本地服务未能在端口 <code>{}</code> 上就绪。", info.port)
    };
    let html = format!(
        r#"<!doctype html><meta charset="utf-8">
<title>Captain 启动失败</title>
<style>
body{{font:14px -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;background:#f7f5f1;color:#24221f;margin:0;padding:40px;line-height:1.7}}
.box{{max-width:760px;margin:auto;background:#fff;border:1px solid #ded8cf;border-radius:12px;padding:28px;box-shadow:0 12px 40px rgba(0,0,0,.08)}}
h1{{font-size:22px;margin:0 0 10px}} code{{background:#f0ece5;border-radius:6px;padding:2px 5px}} .path{{word-break:break-all}}
.btn{{margin-top:16px;background:#7c6cf0;color:#fff;border:none;border-radius:8px;padding:10px 16px;font-size:14px;cursor:pointer}}
</style>
<div class="box">
<h1>Captain 后端没有成功启动</h1>
<p>{port_note}</p>
<p>请先查看日志：<br><code class="path">{err_log}</code></p>
<p>常见原因：端口被占用、Python runtime 损坏、依赖安装不完整、模型/授权配置异常。</p>
<p>也可在 App 的「设置 → 诊断」打开日志、导出诊断包，或复制下方摘要发给维护者。</p>
<button class="btn" type="button" onclick="navigator.clipboard.writeText({summary_json}).then(()=>this.textContent='已复制诊断摘要')">复制诊断摘要</button>
</div>"#,
        port_note = port_note,
        err_log = err_log.display(),
        summary_json = summary_json,
    );
    fs::write(&path, html)?;
    Ok(path)
}

fn spawn_backend(root: &Path, port: u16, packaged_python: Option<&Path>) -> Result<Child, io::Error> {
    let python = resolve_python(root, packaged_python);
    let log_dir = support_log_dir(root);
    let stdout = fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open(log_dir.join("backend.out.log"))?;
    let stderr = fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open(log_dir.join("backend.err.log"))?;
    let mut command = Command::new(&python);
    command
        .arg("-m")
        .arg("uvicorn")
        .arg("server.app:app")
        .arg("--host")
        .arg("127.0.0.1")
        .arg("--port")
        .arg(port.to_string())
        .current_dir(root)
        .env("AGENT_PROJECT_ROOT", root.as_os_str())
        .env("CAPTAIN_PROJECT_ROOT", root.as_os_str())
        .env("CAPTAIN_DESKTOP", "1")
        .env("AGENT_WEB_HOST", "127.0.0.1")
        .env("AGENT_WEB_PORT", port.to_string())
        .stdin(Stdio::null())
        .stdout(Stdio::from(stdout))
        .stderr(Stdio::from(stderr));

    if cfg!(target_os = "macos") {
        command.env("CAPTAIN_USE_KEYCHAIN", "1");
    }

    #[cfg(windows)]
    {
        const CREATE_NO_WINDOW: u32 = 0x0800_0000;
        command.creation_flags(CREATE_NO_WINDOW);
    }

    command.spawn().map_err(|err| {
        io::Error::new(
            err.kind(),
            format!("无法启动 Captain 后端: {} ({})", err, python.display()),
        )
    })
}

fn stop_backend(state: tauri::State<'_, BackendState>, root: &Path) {
    if let Ok(owns) = state.owns_backend.lock() {
        if !*owns {
            release_gui_lock(root);
            return;
        }
    }
    if let Ok(mut guard) = state.child.lock() {
        if let Some(mut child) = guard.take() {
            let _ = child.kill();
            let _ = child.wait();
        }
    }
    release_gui_lock(root);
}

fn set_backend_state(app: &tauri::App, child: Option<Child>, owns: bool) -> Result<(), io::Error> {
    {
        let state = app.state::<BackendState>();
        let mut guard = state
            .child
            .lock()
            .map_err(|_| io::Error::new(io::ErrorKind::Other, "后端状态锁异常"))?;
        *guard = child;
    }
    {
        let state = app.state::<BackendState>();
        let mut owns_guard = state
            .owns_backend
            .lock()
            .map_err(|_| io::Error::new(io::ErrorKind::Other, "后端状态锁异常"))?;
        *owns_guard = owns;
    }
    Ok(())
}

async fn run_updater_check(app: tauri::AppHandle) {
    match app.updater().check().await {
        Ok(resp) if resp.is_update_available() => {
            let _ = resp.download_and_install().await;
        }
        Ok(_) => {}
        Err(err) => eprintln!("Captain updater check failed: {err}"),
    }
}

fn build_system_tray() -> SystemTray {
    let show = CustomMenuItem::new("show".to_string(), "打开主窗口");
    let logs = CustomMenuItem::new("logs".to_string(), "打开日志");
    let update = CustomMenuItem::new("update".to_string(), "检查更新");
    let quit = CustomMenuItem::new("quit".to_string(), "退出");
    let menu = SystemTrayMenu::new()
        .add_item(show)
        .add_item(logs)
        .add_item(update)
        .add_native_item(SystemTrayMenuItem::Separator)
        .add_item(quit);
    SystemTray::new().with_menu(menu)
}

fn main() {
    tauri::Builder::default()
        .system_tray(build_system_tray())
        .manage(BackendState::default())
        .setup(|app| {
            let root = project_root()?;
            if !ensure_single_gui_instance(&root) {
                std::process::exit(0);
            }

            let preferred = env::var("AGENT_WEB_PORT")
                .ok()
                .and_then(|raw| raw.parse::<u16>().ok())
                .unwrap_or(8000);
            let packaged_python = app
                .path_resolver()
                .resource_dir()
                .and_then(|resource_dir| packaged_python_path(&resource_dir));

            let (port, preferred_port, port_switched, spawned_child) =
                if let Some(existing) = find_existing_backend(&root) {
                    (existing, preferred, existing != preferred, None)
                } else {
                    let (port, preferred_port, port_switched) = pick_port();
                    let child = spawn_backend(&root, port, packaged_python.as_deref())?;
                    (port, preferred_port, port_switched, Some(child))
                };

            let owns_backend = spawned_child.is_some();
            set_backend_state(app, spawned_child, owns_backend)?;

            let launch = LaunchInfo {
                port,
                preferred_port,
                port_switched,
                root: root.clone(),
            };
            app.manage(launch);

            let ready = wait_for_backend(port);
            let url = if ready {
                format!("http://127.0.0.1:{}/", port)
            } else {
                let path = backend_error_page(&LaunchInfo {
                    port,
                    preferred_port,
                    port_switched,
                    root: root.clone(),
                })?;
                format!("file://{}", path.to_string_lossy().replace(' ', "%20"))
            };

            let window_url = WindowUrl::External(url.parse()?);

            tauri::WindowBuilder::new(app, "main", window_url)
                .title("Captain")
                .inner_size(1280.0, 820.0)
                .min_inner_size(980.0, 680.0)
                .build()?;

            let updater_app = app.handle();
            tauri::async_runtime::spawn(async move {
                run_updater_check(updater_app).await;
            });

            Ok(())
        })
        .on_system_tray_event(|app, event| {
            if let SystemTrayEvent::MenuItemClick { id, .. } = event {
                match id.as_str() {
                    "show" => {
                        if let Some(window) = app.get_window("main") {
                            let _ = window.show();
                            let _ = window.set_focus();
                        }
                    }
                    "logs" => {
                        if let Some(info) = app.try_state::<LaunchInfo>() {
                            open_logs_dir(&info.root);
                        }
                    }
                    "update" => {
                        let handle = app.clone();
                        tauri::async_runtime::spawn(async move {
                            run_updater_check(handle).await;
                        });
                    }
                    "quit" => {
                        if let Some(info) = app.try_state::<LaunchInfo>() {
                            if let Some(state) = app.try_state::<BackendState>() {
                                stop_backend(state, &info.root);
                            }
                        }
                        app.exit(0);
                    }
                    _ => {}
                }
            }
        })
        .on_window_event(|event| {
            if let WindowEvent::CloseRequested { api, .. } = event.event() {
                api.prevent_close();
                let _ = event.window().hide();
            }
        })
        .run(tauri::generate_context!())
        .expect("error while running Captain desktop");
}

#[cfg(test)]
mod tests {
    use super::*;

    fn temp_root(name: &str) -> PathBuf {
        let path = env::temp_dir().join(format!(
            "captain-{name}-{}-{}",
            std::process::id(),
            chrono_like_timestamp()
        ));
        fs::create_dir_all(&path).unwrap();
        path
    }

    fn write_runtime(root: &Path, version: &str, built_at: &str, trust: &str) {
        fs::create_dir_all(root.join("server")).unwrap();
        fs::write(root.join("server/app.py"), "app = None\n").unwrap();
        let mut stamp = HashMap::from([
            ("built_at".to_string(), built_at.to_string()),
            ("commit".to_string(), "abc".to_string()),
            ("stamp_schema".to_string(), "1".to_string()),
            ("trust".to_string(), trust.to_string()),
            ("version".to_string(), version.to_string()),
        ]);
        stamp.insert("manifest_hash".to_string(), stamp_manifest_hash(&stamp));
        let mut keys = stamp.keys().collect::<Vec<_>>();
        keys.sort();
        let content = keys
            .into_iter()
            .map(|key| format!("{key}={}\n", stamp.get(key).unwrap()))
            .collect::<String>();
        fs::write(root.join(".captain_bundle_stamp"), content).unwrap();
    }

    #[test]
    fn refresh_requires_a_trusted_newer_bundle() {
        let root = temp_root("refresh-order");
        let support = root.join("support");
        let resource = root.join("resource");
        write_runtime(&support, "1.0.0", "20260701000000", "development");
        write_runtime(&resource, "1.1.0", "20260702000000", "platform-signed");
        assert!(support_needs_bundle_refresh(&support, &resource));

        write_runtime(&resource, "0.9.0", "20260703000000", "platform-signed");
        assert!(!support_needs_bundle_refresh(&support, &resource));

        write_runtime(&resource, "2.0.0", "20260704000000", "development");
        assert!(!support_needs_bundle_refresh(&support, &resource));
        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn atomic_refresh_preserves_state_and_removes_old_code() {
        let root = temp_root("atomic-refresh");
        let support = root.join("support");
        let resource = root.join("resource");
        write_runtime(&support, "1.0.0", "20260701000000", "development");
        fs::create_dir_all(support.join("logs")).unwrap();
        fs::write(support.join("logs/state.db"), "user-state").unwrap();
        fs::write(support.join("obsolete.py"), "old").unwrap();
        write_runtime(&resource, "1.1.0", "20260702000000", "platform-signed");
        fs::write(resource.join("current.py"), "new").unwrap();

        refresh_support_atomically(&resource, &support).unwrap();

        assert_eq!(file_text(&support.join("logs/state.db")), "user-state");
        assert!(support.join("current.py").is_file());
        assert!(!support.join("obsolete.py").exists());
        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn tampered_bundle_stamp_is_rejected() {
        let root = temp_root("tampered-stamp");
        let support = root.join("support");
        let resource = root.join("resource");
        write_runtime(&resource, "1.1.0", "20260702000000", "platform-signed");
        assert!(support_needs_bundle_refresh(&support, &resource));
        let mut content = file_text(&resource.join(".captain_bundle_stamp"));
        content.push_str("\nversion=9.9.9\n");
        fs::write(resource.join(".captain_bundle_stamp"), content).unwrap();
        assert!(!support_needs_bundle_refresh(&support, &resource));
        let _ = fs::remove_dir_all(root);
    }
}
