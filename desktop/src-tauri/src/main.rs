#![cfg_attr(all(not(debug_assertions), target_os = "windows"), windows_subsystem = "windows")]

use std::{
    env,
    io,
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

fn has_server(root: &Path) -> bool {
    root.join("server").join("app.py").is_file()
}

fn project_root() -> PathBuf {
    for key in ["CAPTAIN_PROJECT_ROOT", "AGENT_PROJECT_ROOT"] {
        if let Ok(raw) = env::var(key) {
            let path = PathBuf::from(raw);
            if has_server(&path) {
                return path;
            }
        }
    }

    let dev_root = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .and_then(Path::parent)
        .map(Path::to_path_buf);
    if let Some(root) = dev_root {
        if has_server(&root) {
            return root;
        }
    }

    env::current_dir().unwrap_or_else(|_| PathBuf::from("."))
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

fn spawn_backend(root: &Path, port: u16) -> Result<Child, io::Error> {
    let python = resolve_python(root);
    let mut command = Command::new(&python);
    command
        .arg("-m")
        .arg("server.app")
        .current_dir(root)
        .env("AGENT_PROJECT_ROOT", root.as_os_str())
        .env("CAPTAIN_PROJECT_ROOT", root.as_os_str())
        .env("CAPTAIN_DESKTOP", "1")
        .env("AGENT_WEB_HOST", "127.0.0.1")
        .env("AGENT_WEB_PORT", port.to_string())
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null());

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
            let root = project_root();
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
                format!("http://127.0.0.1:{}/healthz", port)
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
