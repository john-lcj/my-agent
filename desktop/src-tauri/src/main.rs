#![cfg_attr(all(not(debug_assertions), target_os = "windows"), windows_subsystem = "windows")]

use std::{
    env,
    fs,
    io,
    io::{Read, Write},
    net::{TcpListener, TcpStream},
    path::{Path, PathBuf},
    process::{Child, Command, Stdio},
    sync::Mutex,
    thread,
    time::Duration,
};

use tauri::{Manager, WindowEvent, WindowUrl};

#[derive(Default)]
struct BackendState {
    child: Mutex<Option<Child>>,
}

impl Drop for BackendState {
    fn drop(&mut self) {
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
        Some(".env" | "data" | "logs" | "uploads")
    )
}

fn copy_dir_preserving_state(src: &Path, dst: &Path) -> io::Result<()> {
    fs::create_dir_all(dst)?;
    for entry in fs::read_dir(src)? {
        let entry = entry?;
        let src_path = entry.path();
        let dst_path = dst.join(entry.file_name());
        if should_preserve_support_entry(&dst_path) {
            continue;
        }
        let file_type = entry.file_type()?;

        if file_type.is_dir() {
            copy_dir_preserving_state(&src_path, &dst_path)?;
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

fn file_text(path: &Path) -> String {
    fs::read_to_string(path).unwrap_or_default().trim().to_string()
}

fn support_needs_bundle_refresh(support_root: &Path, resource_root: &Path) -> bool {
    if !has_server(support_root) {
        return true;
    }
    let resource_stamp = file_text(&resource_root.join(".captain_bundle_stamp"));
    if resource_stamp.is_empty() {
        return false;
    }
    file_text(&support_root.join(".captain_bundle_stamp")) != resource_stamp
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
    let auth_secret = ensure_macos_keychain_secret("env:AUTH_SECRET", 32);
    let api_token = ensure_macos_keychain_secret("env:AGENT_API_TOKEN", 32);
    if env_path.exists() {
        return Ok(());
    }
    let workspace = env::var("HOME").unwrap_or_else(|_| root.display().to_string());
    let secret_lines = if auth_secret.is_some() && api_token.is_some() {
        "CAPTAIN_USE_KEYCHAIN=1\n# AUTH_SECRET and AGENT_API_TOKEN are stored in macOS Keychain.\n".to_string()
    } else {
        format!(
            "AUTH_SECRET={auth_secret}\nAGENT_API_TOKEN={api_token}\n",
            auth_secret = auth_secret.unwrap_or(random_hex(32)?),
            api_token = api_token.unwrap_or(random_hex(32)?),
        )
    };
    let content = format!(
        "# Captain macOS local config\n\
AGENT_PROVIDER=deepseek\n\
AGENT_MODEL=deepseek-v4-flash\n\
AGENT_WEB_PORT=8000\n\
AGENT_WORKSPACE_ROOT={workspace}\n\
CAPTAIN_LICENSE_KEY=\n\
{secret_lines}\
\n\
# Fill your model key before using real models.\n\
DEEPSEEK_API_KEY=\n",
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

fn ensure_macos_support_from_bundle() -> io::Result<Option<PathBuf>> {
    if !cfg!(target_os = "macos") {
        return Ok(None);
    }
    let Some(support_root) = macos_support_app_root() else {
        return Ok(None);
    };

    for resource_root in macos_resource_app_roots() {
        if has_server(&resource_root) {
            if support_needs_bundle_refresh(&support_root, &resource_root) {
                if let Some(parent) = support_root.parent() {
                    fs::create_dir_all(parent)?;
                }
                if support_root.exists() && !has_server(&support_root) {
                    fs::remove_dir_all(&support_root)?;
                    copy_dir_preserving_symlinks(&resource_root, &support_root)?;
                } else if support_root.exists() {
                    copy_dir_preserving_state(&resource_root, &support_root)?;
                } else {
                    copy_dir_preserving_symlinks(&resource_root, &support_root)?;
                }
            }
            ensure_default_env(&support_root)?;
            return Ok(Some(support_root));
        }
    }

    if has_server(&support_root) {
        ensure_default_env(&support_root)?;
        return Ok(Some(support_root));
    }

    Ok(None)
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

    for candidate in dev_project_roots().into_iter().chain(packaged_project_roots()) {
        if has_server(&candidate) {
            ensure_default_env(&candidate)?;
            return Ok(candidate);
        }
    }

    Err(io::Error::new(
        io::ErrorKind::NotFound,
        "找不到 Captain 后端目录。请重新安装 Captain.app, 或设置 CAPTAIN_PROJECT_ROOT。",
    ))
}

fn candidate_python_paths(root: &Path) -> Vec<PathBuf> {
    let mut candidates = Vec::new();

    if cfg!(windows) {
        candidates.push(root.join(".venv").join("Scripts").join("python.exe"));
        candidates.push(root.join("runtime").join("python").join("python.exe"));
        candidates.push(PathBuf::from("python"));
    } else {
        candidates.push(root.join(".venv").join("bin").join("python"));
        candidates.push(root.join("runtime").join("python").join("bin").join("python3"));
        candidates.push(PathBuf::from("python3"));
        candidates.push(PathBuf::from("python"));
    }

    candidates
}

fn resolve_python(root: &Path) -> PathBuf {
    for candidate in candidate_python_paths(root) {
        if candidate.components().count() == 1 || candidate.is_file() {
            return candidate;
        }
    }
    PathBuf::from(if cfg!(windows) { "python" } else { "python3" })
}

fn port_available(port: u16) -> bool {
    TcpListener::bind(("127.0.0.1", port)).is_ok()
}

fn pick_port() -> u16 {
    if let Ok(raw) = env::var("AGENT_WEB_PORT") {
        if let Ok(port) = raw.parse::<u16>() {
            if port_available(port) {
                return port;
            }
        }
    }

    (8000..=8099).find(|port| port_available(*port)).unwrap_or(8000)
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

fn backend_error_page(root: &Path, port: u16) -> io::Result<PathBuf> {
    let log_dir = root
        .parent()
        .map(Path::to_path_buf)
        .unwrap_or_else(|| root.to_path_buf());
    fs::create_dir_all(&log_dir)?;
    let path = log_dir.join("backend-start-error.html");
    let err_log = log_dir.join("backend.err.log");
    let html = format!(
        r#"<!doctype html><meta charset="utf-8">
<title>Captain 启动失败</title>
<style>
body{{font:14px -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;background:#f7f5f1;color:#24221f;margin:0;padding:40px;line-height:1.7}}
.box{{max-width:760px;margin:auto;background:#fff;border:1px solid #ded8cf;border-radius:12px;padding:28px;box-shadow:0 12px 40px rgba(0,0,0,.08)}}
h1{{font-size:22px;margin:0 0 10px}} code{{background:#f0ece5;border-radius:6px;padding:2px 5px}} .path{{word-break:break-all}}
</style>
<div class="box">
<h1>Captain 后端没有成功启动</h1>
<p>App 已启动，但本地服务未能在端口 <code>{port}</code> 上就绪。</p>
<p>请先查看日志：<br><code class="path">{err_log}</code></p>
<p>常见原因：端口被占用、Python runtime 损坏、依赖安装不完整、模型/授权配置异常。</p>
<p>在设置里的「关于」页可以使用「打开日志」和「导出诊断包」发给维护者排查。</p>
</div>"#,
        port = port,
        err_log = err_log.display(),
    );
    fs::write(&path, html)?;
    Ok(path)
}

fn spawn_backend(root: &Path, port: u16) -> Result<Child, io::Error> {
    let python = resolve_python(root);
    let log_dir = root
        .parent()
        .map(Path::to_path_buf)
        .unwrap_or_else(|| root.to_path_buf());
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
        .arg("server.app")
        .current_dir(root)
        .env("AGENT_PROJECT_ROOT", root.as_os_str())
        .env("CAPTAIN_PROJECT_ROOT", root.as_os_str())
        .env("CAPTAIN_DESKTOP", "1")
        .env("CAPTAIN_USE_KEYCHAIN", "1")
        .env("AGENT_WEB_HOST", "127.0.0.1")
        .env("AGENT_WEB_PORT", port.to_string())
        .stdin(Stdio::null())
        .stdout(Stdio::from(stdout))
        .stderr(Stdio::from(stderr));

    command.spawn().map_err(|err| {
        io::Error::new(
            err.kind(),
            format!("无法启动 Captain 后端: {} ({})", err, python.display()),
        )
    })
}

fn stop_backend(state: tauri::State<'_, BackendState>) {
    if let Ok(mut guard) = state.child.lock() {
        if let Some(mut child) = guard.take() {
            let _ = child.kill();
            let _ = child.wait();
        }
    }
}

fn main() {
    tauri::Builder::default()
        .manage(BackendState::default())
        .setup(|app| {
            let root = project_root()?;
            let port = pick_port();
            let child = spawn_backend(&root, port)?;
            {
                let state = app.state::<BackendState>();
                let mut guard = state
                    .child
                    .lock()
                    .map_err(|_| io::Error::new(io::ErrorKind::Other, "后端状态锁异常"))?;
                *guard = Some(child);
            }

            let ready = wait_for_backend(port);
            let url = if ready {
                format!("http://127.0.0.1:{}/", port)
            } else {
                let path = backend_error_page(&root, port)?;
                format!("file://{}", path.to_string_lossy().replace(' ', "%20"))
            };

            let window_url = WindowUrl::External(url.parse()?);

            tauri::WindowBuilder::new(app, "main", window_url)
            .title("Captain")
            .inner_size(1280.0, 820.0)
            .min_inner_size(980.0, 680.0)
            .build()?;

            Ok(())
        })
        .on_window_event(|event| {
            if matches!(event.event(), WindowEvent::CloseRequested { .. }) {
                let state = event.window().state::<BackendState>();
                stop_backend(state);
            }
        })
        .run(tauri::generate_context!())
        .expect("error while running Captain desktop");
}
