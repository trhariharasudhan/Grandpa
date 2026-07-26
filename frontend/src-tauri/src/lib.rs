use std::sync::Arc;
use std::time::Duration;
use tauri::menu::{MenuBuilder, MenuItemBuilder};
use tauri::tray::TrayIconBuilder;
use tauri::{
    AppHandle, LogicalPosition, LogicalSize, Manager, WebviewUrl, WebviewWindow,
    WebviewWindowBuilder, WindowEvent,
};
use tauri_plugin_autostart::MacosLauncher;
use tokio::sync::Mutex;

const OLLAMA_PORT: u16 = 11434;
const GRANDPA_PORT: u16 = 8000;
const FLOATING_WINDOW_LABEL: &str = "grandpa-floating";
const FLOATING_COLLAPSED_WIDTH: f64 = 48.0;
const FLOATING_COLLAPSED_HEIGHT: f64 = 48.0;
const FLOATING_EXPANDED_WIDTH: f64 = 300.0;
const FLOATING_EXPANDED_HEIGHT: f64 = 340.0;
const FLOATING_EDGE_GAP: f64 = 20.0;
const FLOATING_TASKBAR_GAP: f64 = 72.0;
#[cfg(debug_assertions)]
const FLOATING_DEBUG_VISIBLE_POSITION: FloatingPosition = FloatingPosition { x: 100.0, y: 100.0 };
#[cfg(debug_assertions)]
const FLOATING_DEBUG_NORMAL_WINDOW_SIZE: f64 = 300.0;

#[cfg(target_os = "windows")]
const GWL_EXSTYLE: i32 = -20;
#[cfg(target_os = "windows")]
const WS_EX_TRANSPARENT: isize = 0x00000020;
#[cfg(target_os = "windows")]
const WS_EX_LAYERED: isize = 0x00080000;
#[cfg(target_os = "windows")]
const WS_EX_NOACTIVATE: isize = 0x08000000;
#[cfg(target_os = "windows")]
const WS_EX_TOOLWINDOW: isize = 0x00000080;
#[cfg(target_os = "windows")]
const SWP_NOSIZE: u32 = 0x0001;
#[cfg(target_os = "windows")]
const SWP_NOMOVE: u32 = 0x0002;
#[cfg(target_os = "windows")]
const SWP_NOZORDER: u32 = 0x0004;
#[cfg(target_os = "windows")]
const SWP_NOACTIVATE: u32 = 0x0010;
#[cfg(target_os = "windows")]
const SWP_FRAMECHANGED: u32 = 0x0020;
#[cfg(target_os = "windows")]
const HWND_TOPMOST: isize = -1;

#[cfg(target_os = "windows")]
extern "system" {
    fn GetWindowLongPtrW(hwnd: *mut std::ffi::c_void, n_index: i32) -> isize;
    fn SetWindowLongPtrW(hwnd: *mut std::ffi::c_void, n_index: i32, dw_new_long: isize) -> isize;
    fn SetWindowPos(
        hwnd: *mut std::ffi::c_void,
        hwnd_insert_after: *mut std::ffi::c_void,
        x: i32,
        y: i32,
        cx: i32,
        cy: i32,
        flags: u32,
    ) -> i32;
    fn EnumChildWindows(
        hwnd_parent: *mut std::ffi::c_void,
        lp_enum_func: extern "system" fn(*mut std::ffi::c_void, isize) -> i32,
        l_param: isize,
    ) -> i32;
    fn GetClassNameW(hwnd: *mut std::ffi::c_void, lp_class_name: *mut u16, n_max_count: i32)
        -> i32;
    fn GetLastError() -> u32;
}

/// Preferred small startup model. The desktop app never auto-pulls it; users
/// confirm model downloads through the normal model/chat flow.
const STARTUP_MODEL: &str = "qwen3.5:4b";

/// Tiny fallback model id used only as a server default when no local model is detected.
const FALLBACK_MODEL: &str = "qwen3:0.6b";

/// Qwen3.5 model variants, ordered smallest to largest.
/// Each entry is (ollama_tag, approximate_download_size_gb, min_ram_gb).
const QWEN35_MODELS: &[(&str, f64, f64)] = &[
    ("qwen3.5:0.8b", 1.0, 4.0),
    ("qwen3.5:2b", 2.7, 6.0),
    ("qwen3.5:4b", 3.4, 8.0),
    ("qwen3.5:9b", 6.6, 12.0),
    ("qwen3.5:27b", 17.0, 24.0),
    ("qwen3.5:35b", 24.0, 32.0),
    ("qwen3.5:122b", 81.0, 96.0),
];

/// Get total system RAM in GB.
fn total_ram_gb() -> f64 {
    #[cfg(target_os = "macos")]
    {
        use std::process::Command;
        if let Ok(output) = Command::new("sysctl").args(["-n", "hw.memsize"]).output() {
            if let Ok(s) = String::from_utf8(output.stdout) {
                if let Ok(bytes) = s.trim().parse::<u64>() {
                    return bytes as f64 / (1024.0 * 1024.0 * 1024.0);
                }
            }
        }
    }
    #[cfg(target_os = "linux")]
    {
        if let Ok(contents) = std::fs::read_to_string("/proc/meminfo") {
            for line in contents.lines() {
                if line.starts_with("MemTotal:") {
                    if let Some(kb_str) = line.split_whitespace().nth(1) {
                        if let Ok(kb) = kb_str.parse::<u64>() {
                            return kb as f64 / (1024.0 * 1024.0);
                        }
                    }
                }
            }
        }
    }
    #[cfg(target_os = "windows")]
    {
        use std::process::Command;
        // wmic returns TotalVisibleMemorySize in KB
        if let Ok(output) = Command::new("wmic")
            .args(["OS", "get", "TotalVisibleMemorySize", "/value"])
            .output()
        {
            if let Ok(s) = String::from_utf8(output.stdout) {
                for line in s.lines() {
                    if let Some(val) = line.strip_prefix("TotalVisibleMemorySize=") {
                        if let Ok(kb) = val.trim().parse::<u64>() {
                            return kb as f64 / (1024.0 * 1024.0);
                        }
                    }
                }
            }
        }
    }
    8.0
}

/// Return the list of Qwen3.5 models that fit on this machine, smallest first.
fn models_that_fit() -> Vec<&'static str> {
    let ram = total_ram_gb();
    QWEN35_MODELS
        .iter()
        .filter(|(_, _, min_ram)| ram >= *min_ram)
        .map(|(tag, _, _)| *tag)
        .collect()
}

/// Pick the default model — prefers STARTUP_MODEL if it fits, otherwise
/// falls back to the third-largest model that fits on this machine.
fn preferred_model() -> &'static str {
    let fitting = models_that_fit();
    // Prefer STARTUP_MODEL when it fits (fast, good quality)
    if fitting.contains(&STARTUP_MODEL) {
        return STARTUP_MODEL;
    }
    match fitting.len() {
        0 => FALLBACK_MODEL,
        1 => fitting[0],
        2 => fitting[0],
        n => fitting[n - 3], // third-largest
    }
}

/// Get the user home directory, handling both Unix (HOME) and Windows (USERPROFILE).
fn home_dir() -> String {
    std::env::var("HOME")
        .or_else(|_| std::env::var("USERPROFILE"))
        .unwrap_or_default()
}

/// Resolve full path to a binary by checking common locations.
/// macOS .app bundles don't inherit the shell PATH, so we probe manually.
fn resolve_bin(name: &str) -> String {
    let home = home_dir();

    #[cfg(not(target_os = "windows"))]
    let candidates = vec![
        format!("/opt/homebrew/bin/{name}"),
        format!("{home}/.local/bin/{name}"),
        format!("{home}/.cargo/bin/{name}"),
        format!("/usr/local/bin/{name}"),
        format!("/usr/bin/{name}"),
    ];

    #[cfg(target_os = "windows")]
    let candidates = {
        let localappdata = std::env::var("LOCALAPPDATA").unwrap_or_default();
        let programfiles = std::env::var("ProgramFiles").unwrap_or_default();
        let programfiles_x86 = std::env::var("ProgramFiles(x86)").unwrap_or_default();
        vec![
            // Git for Windows — standard install paths
            format!("{programfiles}\\Git\\cmd\\{name}.exe"),
            format!("{programfiles_x86}\\Git\\cmd\\{name}.exe"),
            format!("{localappdata}\\Programs\\Git\\cmd\\{name}.exe"),
            // Scoop package manager
            format!("{home}\\scoop\\shims\\{name}.exe"),
            // Cargo, local bin
            format!("{home}\\.cargo\\bin\\{name}.exe"),
            format!("{home}\\.local\\bin\\{name}.exe"),
            // Generic program locations
            format!("{localappdata}\\Programs\\{name}\\{name}.exe"),
            format!("{programfiles}\\{name}\\{name}.exe"),
            // Ollama installs to LOCALAPPDATA on Windows
            format!("{localappdata}\\Programs\\Ollama\\{name}.exe"),
            // uv installs via pip/pipx
            format!("{home}\\AppData\\Roaming\\Python\\Scripts\\{name}.exe"),
        ]
    };

    for path in &candidates {
        if std::path::Path::new(path).exists() {
            return path.clone();
        }
    }

    // Fallback: ask the OS to find it on PATH.
    // On Windows this uses `where.exe`, on Unix `which`.
    #[cfg(target_os = "windows")]
    {
        if let Ok(output) = std::process::Command::new("where")
            .arg(format!("{name}.exe"))
            .output()
        {
            if output.status.success() {
                let stdout = String::from_utf8_lossy(&output.stdout);
                if let Some(first_line) = stdout.lines().next() {
                    let p = first_line.trim();
                    if !p.is_empty() && std::path::Path::new(p).exists() {
                        return p.to_string();
                    }
                }
            }
        }
    }
    #[cfg(not(target_os = "windows"))]
    {
        if let Ok(output) = std::process::Command::new("which").arg(name).output() {
            if output.status.success() {
                let stdout = String::from_utf8_lossy(&output.stdout);
                if let Some(first_line) = stdout.lines().next() {
                    let p = first_line.trim();
                    if !p.is_empty() && std::path::Path::new(p).exists() {
                        return p.to_string();
                    }
                }
            }
        }
    }

    name.to_string()
}

/// Find the Grandpa project root (contains pyproject.toml).
/// Checks Grandpa_ROOT env var, walks up from the executable, then
/// probes common clone locations.
fn find_project_root() -> Option<std::path::PathBuf> {
    // 1. Explicit env var override
    if let Ok(root) = std::env::var("Grandpa_ROOT") {
        let path = std::path::PathBuf::from(&root);
        if path.join("pyproject.toml").exists() {
            return Some(path);
        }
    }

    // 2. Walk up from the running executable (works in dev and .app bundle)
    if let Ok(exe) = std::env::current_exe() {
        let mut dir = exe.parent().map(|p| p.to_path_buf());
        for _ in 0..8 {
            if let Some(ref d) = dir {
                if d.join("pyproject.toml").exists() {
                    return Some(d.clone());
                }
                dir = d.parent().map(|p| p.to_path_buf());
            }
        }
    }

    // 3. Fallback: well-known direct paths
    let home = home_dir();
    let direct = [
        format!("{home}/Grandpa"),
        format!("{home}/projects/hazy/Grandpa"),
        format!("{home}/projects/Grandpa"),
        format!("{home}/src/grandpa"),
        format!("{home}/Documents/Grandpa"),
        format!("{home}/Desktop/Grandpa"),
        format!("{home}/Developer/Grandpa"),
        format!("{home}/dev/Grandpa"),
        format!("{home}/Code/Grandpa"),
        format!("{home}/code/Grandpa"),
        format!("{home}/repos/Grandpa"),
        format!("{home}/github/Grandpa"),
    ];
    for p in &direct {
        let path = std::path::PathBuf::from(p);
        if path.join("pyproject.toml").exists() {
            return Some(path);
        }
    }

    // 4. Shallow scan: look for Grandpa one level inside common parent dirs.
    //    This catches clones like ~/Documents/my-stuff/Grandpa without
    //    needing to enumerate every possible intermediate folder.
    let scan_parents = [
        format!("{home}/Documents"),
        format!("{home}/Desktop"),
        format!("{home}/Developer"),
        format!("{home}/projects"),
        format!("{home}/repos"),
        format!("{home}/src"),
        format!("{home}/Code"),
        format!("{home}/code"),
        format!("{home}/dev"),
        format!("{home}/github"),
    ];
    for parent in &scan_parents {
        let parent_path = std::path::PathBuf::from(parent);
        if let Ok(entries) = std::fs::read_dir(&parent_path) {
            for entry in entries.flatten() {
                let candidate = entry.path().join("Grandpa");
                if candidate.join("pyproject.toml").exists() {
                    return Some(candidate);
                }
                // Also check if the entry itself is Grandpa (case-insensitive match)
                if let Some(name) = entry.file_name().to_str() {
                    if name.eq_ignore_ascii_case("Grandpa")
                        && entry.path().join("pyproject.toml").exists()
                    {
                        return Some(entry.path());
                    }
                }
            }
        }
    }

    None
}

// ---------------------------------------------------------------------------
// BackendManager — owns the Ollama + Grandpa server child processes
// ---------------------------------------------------------------------------

struct ChildHandle {
    child: tokio::process::Child,
}

impl ChildHandle {
    async fn kill(&mut self) {
        let _ = self.child.kill().await;
    }
}

#[derive(Default)]
struct BackendManager {
    ollama: Option<ChildHandle>,
    grandpa: Option<ChildHandle>,
}

impl BackendManager {
    async fn stop_all(&mut self) {
        if let Some(ref mut h) = self.grandpa {
            h.kill().await;
        }
        self.grandpa = None;
        if let Some(ref mut h) = self.ollama {
            h.kill().await;
        }
        self.ollama = None;
    }
}

type SharedBackend = Arc<Mutex<BackendManager>>;

// ---------------------------------------------------------------------------
// Setup status (reported to frontend)
// ---------------------------------------------------------------------------

#[derive(serde::Serialize, Clone)]
struct SetupStatus {
    phase: String,
    detail: String,
    ollama_ready: bool,
    server_ready: bool,
    model_ready: bool,
    error: Option<String>,
}

impl Default for SetupStatus {
    fn default() -> Self {
        Self {
            phase: "starting".into(),
            detail: "Initializing...".into(),
            ollama_ready: false,
            server_ready: false,
            model_ready: false,
            error: None,
        }
    }
}

type SharedStatus = Arc<Mutex<SetupStatus>>;

#[derive(serde::Serialize, serde::Deserialize, Clone, Copy, Debug)]
struct FloatingPosition {
    x: f64,
    y: f64,
}

#[derive(Clone, Copy, Debug)]
struct FloatingBounds {
    x: f64,
    y: f64,
    width: f64,
    height: f64,
}

#[derive(Clone, Copy, Debug)]
struct FloatingWindowConfig {
    collapsed_width: f64,
    collapsed_height: f64,
    expanded_width: f64,
    expanded_height: f64,
    visible: bool,
    always_on_top: bool,
    decorations: bool,
    transparent: bool,
    skip_taskbar: bool,
    resizable: bool,
    shadow: bool,
    focusable: bool,
}

#[derive(serde::Serialize, Clone, Debug)]
struct FloatingBackendStatus {
    state: String,
    detail: String,
    api_base: String,
}

#[derive(serde::Serialize, Clone, Debug, Default)]
struct FloatingHwndStatus {
    hwnd: String,
    class_name: String,
    extended_style: String,
    has_transparent: bool,
    has_layered: bool,
    has_noactivate: bool,
    has_toolwindow: bool,
}

#[derive(serde::Serialize, Clone, Debug, Default)]
struct FloatingInteractionStatus {
    available: bool,
    visible: bool,
    focused: bool,
    cursor_events_ignored: bool,
    outer: Option<FloatingHwndStatus>,
    children: Vec<FloatingHwndStatus>,
    repairs: Vec<FloatingStyleRepair>,
    repaired: bool,
    errors: Vec<String>,
}

#[derive(serde::Serialize, Clone, Debug, Default)]
struct FloatingStyleRepair {
    hwnd: String,
    class_name: String,
    old_extended_style: String,
    new_extended_style: String,
    removed_transparent: bool,
    removed_noactivate: bool,
}

fn floating_window_config() -> FloatingWindowConfig {
    let mut config = FloatingWindowConfig {
        collapsed_width: FLOATING_COLLAPSED_WIDTH,
        collapsed_height: FLOATING_COLLAPSED_HEIGHT,
        expanded_width: FLOATING_EXPANDED_WIDTH,
        expanded_height: FLOATING_EXPANDED_HEIGHT,
        visible: true,
        always_on_top: true,
        decorations: false,
        transparent: true,
        skip_taskbar: true,
        resizable: false,
        shadow: false,
        focusable: true,
    };
    #[cfg(debug_assertions)]
    {
        config.collapsed_width = FLOATING_DEBUG_NORMAL_WINDOW_SIZE;
        config.collapsed_height = FLOATING_DEBUG_NORMAL_WINDOW_SIZE;
        config.expanded_width = FLOATING_DEBUG_NORMAL_WINDOW_SIZE;
        config.expanded_height = FLOATING_DEBUG_NORMAL_WINDOW_SIZE;
        config.decorations = true;
        config.transparent = false;
        config.skip_taskbar = false;
        config.resizable = true;
        config.shadow = true;
        config.focusable = true;
    }
    config
}

fn args_request_hidden<I, S>(args: I) -> bool
where
    I: IntoIterator<Item = S>,
    S: AsRef<str>,
{
    args.into_iter().any(|arg| arg.as_ref() == "--hidden")
}

fn current_launch_requests_hidden() -> bool {
    args_request_hidden(std::env::args())
}

#[cfg(target_os = "windows")]
fn interactive_extended_style(style: isize, _top_level: bool) -> isize {
    style & !WS_EX_TRANSPARENT & !WS_EX_NOACTIVATE
}

#[cfg(target_os = "windows")]
fn hwnd_label(hwnd: *mut std::ffi::c_void) -> String {
    format!("0x{:X}", hwnd as usize)
}

#[cfg(target_os = "windows")]
fn hwnd_class_name(hwnd: *mut std::ffi::c_void) -> String {
    let mut buffer = [0u16; 256];
    let len = unsafe { GetClassNameW(hwnd, buffer.as_mut_ptr(), buffer.len() as i32) };
    if len <= 0 {
        return String::new();
    }
    String::from_utf16_lossy(&buffer[..len as usize])
}

#[cfg(target_os = "windows")]
fn hwnd_extended_style(hwnd: *mut std::ffi::c_void) -> isize {
    unsafe { GetWindowLongPtrW(hwnd, GWL_EXSTYLE) }
}

#[cfg(target_os = "windows")]
fn hwnd_status(hwnd: *mut std::ffi::c_void) -> FloatingHwndStatus {
    let style = hwnd_extended_style(hwnd);
    FloatingHwndStatus {
        hwnd: hwnd_label(hwnd),
        class_name: hwnd_class_name(hwnd),
        extended_style: format!("0x{:X}", style as usize),
        has_transparent: style & WS_EX_TRANSPARENT != 0,
        has_layered: style & WS_EX_LAYERED != 0,
        has_noactivate: style & WS_EX_NOACTIVATE != 0,
        has_toolwindow: style & WS_EX_TOOLWINDOW != 0,
    }
}

#[cfg(target_os = "windows")]
extern "system" fn collect_child_hwnds(hwnd: *mut std::ffi::c_void, l_param: isize) -> i32 {
    let children = unsafe { &mut *(l_param as *mut Vec<*mut std::ffi::c_void>) };
    children.push(hwnd);
    1
}

#[cfg(target_os = "windows")]
fn child_hwnds(hwnd: *mut std::ffi::c_void) -> Vec<*mut std::ffi::c_void> {
    let mut children = Vec::<*mut std::ffi::c_void>::new();
    unsafe {
        EnumChildWindows(hwnd, collect_child_hwnds, &mut children as *mut _ as isize);
    }
    children
}

#[cfg(target_os = "windows")]
fn repair_hwnd_interactivity(
    hwnd: *mut std::ffi::c_void,
    top_level: bool,
) -> Result<Option<FloatingStyleRepair>, String> {
    let current = hwnd_extended_style(hwnd);
    let next = interactive_extended_style(current, top_level);
    if next == current {
        return Ok(None);
    }
    let repair = FloatingStyleRepair {
        hwnd: hwnd_label(hwnd),
        class_name: hwnd_class_name(hwnd),
        old_extended_style: format!("0x{:X}", current as usize),
        new_extended_style: format!("0x{:X}", next as usize),
        removed_transparent: current & WS_EX_TRANSPARENT != 0,
        removed_noactivate: current & WS_EX_NOACTIVATE != 0,
    };
    let previous = unsafe { SetWindowLongPtrW(hwnd, GWL_EXSTYLE, next) };
    if previous == 0 {
        let error = unsafe { GetLastError() };
        if error != 0 {
            return Err(format!(
                "{} SetWindowLongPtrW failed with Win32 error {}",
                hwnd_label(hwnd),
                error
            ));
        }
    }
    let ok = unsafe {
        SetWindowPos(
            hwnd,
            std::ptr::null_mut(),
            0,
            0,
            0,
            0,
            SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED,
        )
    };
    if ok == 0 {
        return Err(format!(
            "{} SetWindowPos(SWP_FRAMECHANGED) failed with Win32 error {}",
            hwnd_label(hwnd),
            unsafe { GetLastError() }
        ));
    }
    Ok(Some(repair))
}

#[cfg(target_os = "windows")]
fn force_hwnd_topmost(hwnd: *mut std::ffi::c_void) -> Result<(), String> {
    let ok = unsafe {
        SetWindowPos(
            hwnd,
            HWND_TOPMOST as *mut std::ffi::c_void,
            0,
            0,
            0,
            0,
            SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_FRAMECHANGED,
        )
    };
    if ok == 0 {
        return Err(format!(
            "{} SetWindowPos(HWND_TOPMOST) failed with Win32 error {}",
            hwnd_label(hwnd),
            unsafe { GetLastError() }
        ));
    }
    Ok(())
}

#[cfg(target_os = "windows")]
fn floating_interaction_status_for_window(
    window: &tauri::WebviewWindow,
    repair: bool,
) -> FloatingInteractionStatus {
    let mut status = FloatingInteractionStatus {
        available: true,
        visible: window.is_visible().unwrap_or(false),
        focused: window.is_focused().unwrap_or(false),
        cursor_events_ignored: false,
        outer: None,
        children: Vec::new(),
        repairs: Vec::new(),
        repaired: false,
        errors: Vec::new(),
    };

    if let Err(error) = window.set_ignore_cursor_events(false) {
        status.cursor_events_ignored = true;
        status
            .errors
            .push(format!("set_ignore_cursor_events(false) failed: {error}"));
    }
    if let Err(error) = window.set_focusable(true) {
        status
            .errors
            .push(format!("set_focusable(true) failed: {error}"));
    }

    let Ok(hwnd) = window.hwnd() else {
        status.errors.push("floating HWND unavailable".into());
        return status;
    };
    let outer = hwnd.0 as *mut std::ffi::c_void;
    if repair {
        if let Err(error) = force_hwnd_topmost(outer) {
            status.errors.push(error);
        }
    }
    let mut hierarchy = vec![outer];
    hierarchy.extend(child_hwnds(outer));

    if repair {
        for (index, hwnd) in hierarchy.iter().enumerate() {
            match repair_hwnd_interactivity(*hwnd, index == 0) {
                Ok(Some(repair)) => {
                    status.repaired = true;
                    status.repairs.push(repair);
                }
                Ok(None) => {}
                Err(error) => status.errors.push(error),
            }
        }
    }

    status.outer = Some(hwnd_status(outer));
    status.children = child_hwnds(outer).into_iter().map(hwnd_status).collect();
    status
}

#[cfg(target_os = "windows")]
fn ensure_floating_interactive_window(
    window: &tauri::WebviewWindow,
    context: &str,
) -> FloatingInteractionStatus {
    let status = floating_interaction_status_for_window(window, true);
    #[cfg(debug_assertions)]
    {
        eprintln!(
            "Floating interaction repair ({context}): repaired={} visible={} focused={} errors={:?}",
            status.repaired, status.visible, status.focused, status.errors
        );
        for repair in &status.repairs {
            eprintln!(
                "Floating style repair HWND {} class={} old={} new={} removed_transparent={} removed_noactivate={}",
                repair.hwnd,
                repair.class_name,
                repair.old_extended_style,
                repair.new_extended_style,
                repair.removed_transparent,
                repair.removed_noactivate
            );
        }
        if let Some(outer) = &status.outer {
            eprintln!(
                "Floating outer HWND {} class={} exstyle={} transparent={} noactivate={} layered={}",
                outer.hwnd,
                outer.class_name,
                outer.extended_style,
                outer.has_transparent,
                outer.has_noactivate,
                outer.has_layered
            );
        }
        for child in &status.children {
            eprintln!(
                "Floating child HWND {} class={} exstyle={} transparent={} noactivate={} layered={}",
                child.hwnd,
                child.class_name,
                child.extended_style,
                child.has_transparent,
                child.has_noactivate,
                child.has_layered
            );
        }
    }
    status
}

#[cfg(not(target_os = "windows"))]
fn ensure_floating_interactive_window(
    _window: &tauri::WebviewWindow,
    _context: &str,
) -> FloatingInteractionStatus {
    FloatingInteractionStatus {
        available: true,
        ..FloatingInteractionStatus::default()
    }
}

#[cfg(not(target_os = "windows"))]
fn floating_interaction_status_for_window(
    window: &tauri::WebviewWindow,
    _repair: bool,
) -> FloatingInteractionStatus {
    FloatingInteractionStatus {
        available: true,
        visible: window.is_visible().unwrap_or(false),
        focused: window.is_focused().unwrap_or(false),
        ..FloatingInteractionStatus::default()
    }
}

fn floating_position_path() -> std::path::PathBuf {
    std::path::PathBuf::from(home_dir())
        .join(".grandpa")
        .join("floating-window.json")
}

fn read_floating_position_file() -> Option<FloatingPosition> {
    let raw = std::fs::read_to_string(floating_position_path()).ok()?;
    let position: FloatingPosition = serde_json::from_str(&raw).ok()?;
    valid_floating_position(position)
}

fn valid_floating_position(position: FloatingPosition) -> Option<FloatingPosition> {
    if position.x.is_finite()
        && position.y.is_finite()
        && position.x.abs() < 100_000.0
        && position.y.abs() < 100_000.0
    {
        Some(position)
    } else {
        None
    }
}

fn default_floating_position(
    bounds: FloatingBounds,
    window_width: f64,
    window_height: f64,
) -> FloatingPosition {
    FloatingPosition {
        x: bounds.x + (bounds.width - window_width - FLOATING_EDGE_GAP).max(FLOATING_EDGE_GAP),
        y: bounds.y + (bounds.height - window_height - FLOATING_TASKBAR_GAP).max(FLOATING_EDGE_GAP),
    }
}

fn clamp_floating_position(
    position: Option<FloatingPosition>,
    bounds: FloatingBounds,
    window_width: f64,
    window_height: f64,
) -> FloatingPosition {
    let fallback = default_floating_position(bounds, window_width, window_height);
    let Some(position) = position.and_then(valid_floating_position) else {
        return fallback;
    };
    let max_x = bounds.x + (bounds.width - window_width).max(0.0);
    let max_y = bounds.y + (bounds.height - window_height).max(0.0);
    if position.x < bounds.x || position.y < bounds.y || position.x > max_x || position.y > max_y {
        return fallback;
    }
    FloatingPosition {
        x: position.x.clamp(bounds.x, max_x),
        y: position.y.clamp(bounds.y, max_y),
    }
}

fn bounds_for_position(
    bounds: &[FloatingBounds],
    position: Option<FloatingPosition>,
) -> Option<FloatingBounds> {
    let position = position?;
    bounds
        .iter()
        .copied()
        .find(|bounds| {
            position.x >= bounds.x
                && position.y >= bounds.y
                && position.x <= bounds.x + bounds.width
                && position.y <= bounds.y + bounds.height
        })
        .or_else(|| bounds.first().copied())
}

fn floating_window_url() -> WebviewUrl {
    WebviewUrl::App("index.html?floating=1".into())
}

fn monitor_bounds_for_app(app: &AppHandle) -> Vec<FloatingBounds> {
    app.available_monitors()
        .ok()
        .map(|monitors| {
            monitors
                .iter()
                .map(|monitor| {
                    let scale = monitor.scale_factor();
                    let work_area = monitor.work_area();
                    FloatingBounds {
                        x: work_area.position.x as f64 / scale,
                        y: work_area.position.y as f64 / scale,
                        width: work_area.size.width as f64 / scale,
                        height: work_area.size.height as f64 / scale,
                    }
                })
                .collect::<Vec<_>>()
        })
        .unwrap_or_default()
}

fn fallback_floating_bounds() -> FloatingBounds {
    FloatingBounds {
        x: 0.0,
        y: 0.0,
        width: 1280.0,
        height: 720.0,
    }
}

fn safe_floating_position_for_app(
    app: &AppHandle,
    config: FloatingWindowConfig,
) -> FloatingPosition {
    let saved_position = read_floating_position_file();
    let monitor_bounds = monitor_bounds_for_app(app);
    let selected_bounds = bounds_for_position(&monitor_bounds, saved_position)
        .unwrap_or_else(fallback_floating_bounds);
    clamp_floating_position(
        saved_position,
        selected_bounds,
        config.collapsed_width,
        config.collapsed_height,
    )
}

#[cfg(debug_assertions)]
fn log_floating_windows(app: &AppHandle, context: &str) {
    let labels = app.webview_windows().keys().cloned().collect::<Vec<_>>();
    eprintln!("Floating diagnostics ({context}) windows: {:?}", labels);
}

#[cfg(not(debug_assertions))]
fn log_floating_windows(_app: &AppHandle, _context: &str) {}

fn apply_floating_window_state(
    window: &WebviewWindow,
    app: &AppHandle,
    context: &str,
) -> Result<(), String> {
    let config = floating_window_config();
    let mut position = safe_floating_position_for_app(app, config);
    let collapsed_width = config.collapsed_width;
    let collapsed_height = config.collapsed_height;
    #[cfg(debug_assertions)]
    {
        eprintln!(
            "Floating diagnostics ({context}) saved position file: {:?}",
            read_floating_position_file()
        );
        position = FLOATING_DEBUG_VISIBLE_POSITION;
        eprintln!(
            "Floating diagnostics ({context}) DEV normal-window probe forced: size={}x{} position={},{} transparent={} skip_taskbar={} decorations={}",
            collapsed_width,
            collapsed_height,
            position.x,
            position.y,
            config.transparent,
            config.skip_taskbar,
            config.decorations
        );
    }

    #[cfg(debug_assertions)]
    {
        let monitor_bounds = monitor_bounds_for_app(app);
        eprintln!("Floating diagnostics ({context}) show requested");
        eprintln!(
            "Floating diagnostics ({context}) monitor/work-area: {:?}",
            monitor_bounds
        );
        eprintln!(
            "Floating diagnostics ({context}) target position: {},{}",
            position.x.round(),
            position.y.round()
        );
    }

    window
        .set_size(LogicalSize::new(collapsed_width, collapsed_height))
        .map_err(|error| format!("set floating size failed: {error}"))?;
    window
        .set_min_size(Some(LogicalSize::new(collapsed_width, collapsed_height)))
        .map_err(|error| format!("set floating min size failed: {error}"))?;
    window
        .set_max_size(Some(LogicalSize::new(
            config.expanded_width,
            config.expanded_height,
        )))
        .map_err(|error| format!("set floating max size failed: {error}"))?;
    window
        .set_position(LogicalPosition::new(
            position.x.round() as i32,
            position.y.round() as i32,
        ))
        .map_err(|error| format!("set floating position failed: {error}"))?;
    if window.is_minimized().unwrap_or(false) {
        window
            .unminimize()
            .map_err(|error| format!("unminimize floating window failed: {error}"))?;
    }
    window
        .set_always_on_top(config.always_on_top)
        .map_err(|error| format!("set floating always-on-top failed: {error}"))?;
    window
        .set_skip_taskbar(config.skip_taskbar)
        .map_err(|error| format!("set floating skip-taskbar failed: {error}"))?;
    window
        .set_focusable(config.focusable)
        .map_err(|error| format!("set floating focusable failed: {error}"))?;
    window
        .set_ignore_cursor_events(false)
        .map_err(|error| format!("set floating cursor events failed: {error}"))?;
    window
        .show()
        .map_err(|error| format!("show floating window failed: {error}"))?;
    #[cfg(debug_assertions)]
    {
        let _ = window.set_focus();
    }

    let interaction_status = ensure_floating_interactive_window(window, context);
    if !interaction_status.errors.is_empty() {
        return Err(interaction_status.errors.join("; "));
    }

    #[cfg(debug_assertions)]
    {
        let visible = window.is_visible().unwrap_or(false);
        let size = window.outer_size().ok();
        let position = window.outer_position().ok();
        eprintln!("Floating diagnostics ({context}) show succeeded");
        eprintln!("Floating diagnostics ({context}) visible: {visible}");
        eprintln!("Floating diagnostics ({context}) size result: {:?}", size);
        eprintln!(
            "Floating diagnostics ({context}) position result: {:?}",
            position
        );
        eprintln!("Floating diagnostics ({context}) always-on-top requested: true");
        eprintln!("Floating diagnostics ({context}) skip-taskbar requested: true");
        eprintln!(
            "Floating diagnostics ({context}) transparent requested: {}",
            config.transparent
        );
        eprintln!(
            "Floating diagnostics ({context}) focusable requested: {}",
            config.focusable
        );
    }

    Ok(())
}

fn ensure_floating_window(app: &AppHandle, context: &str) -> Result<WebviewWindow, String> {
    log_floating_windows(app, &format!("{context} before ensure"));
    #[cfg(debug_assertions)]
    eprintln!("Floating diagnostics ({context}) creation requested");

    let config = floating_window_config();
    if let Some(window) = app.get_webview_window(FLOATING_WINDOW_LABEL) {
        #[cfg(debug_assertions)]
        eprintln!("Floating diagnostics ({context}) existing window found");
        apply_floating_window_state(&window, app, context)?;
        log_floating_windows(app, &format!("{context} after existing repair"));
        return Ok(window);
    }

    #[cfg(debug_assertions)]
    eprintln!("Floating diagnostics ({context}) existing window not found");
    let initial_position = safe_floating_position_for_app(app, config);
    let url = floating_window_url();
    #[cfg(debug_assertions)]
    eprintln!("Floating diagnostics ({context}) URL assigned: index.html?floating=1");

    let floating = WebviewWindowBuilder::new(app, FLOATING_WINDOW_LABEL, url)
        .title("Grandpa Assistant")
        .inner_size(config.collapsed_width, config.collapsed_height)
        .min_inner_size(config.collapsed_width, config.collapsed_height)
        .max_inner_size(config.expanded_width, config.expanded_height)
        .resizable(config.resizable)
        .decorations(config.decorations)
        .transparent(config.transparent)
        .always_on_top(config.always_on_top)
        .skip_taskbar(config.skip_taskbar)
        .shadow(config.shadow)
        .focusable(config.focusable)
        .accept_first_mouse(true)
        .visible(config.visible)
        .position(initial_position.x, initial_position.y)
        .build()
        .map_err(|error| format!("build floating window failed: {error}"))?;

    #[cfg(debug_assertions)]
    eprintln!("Floating diagnostics ({context}) builder completed");

    let floating_for_close = floating.clone();
    floating.on_window_event(move |window_event| {
        if let WindowEvent::CloseRequested { api, .. } = window_event {
            api.prevent_close();
            let _ = floating_for_close.hide();
        }
    });

    apply_floating_window_state(&floating, app, context)?;
    log_floating_windows(app, &format!("{context} after creation"));
    Ok(floating)
}

// ---------------------------------------------------------------------------
// Health-check helpers
// ---------------------------------------------------------------------------

async fn wait_for_url(url: &str, timeout: Duration) -> bool {
    let client = reqwest::Client::builder()
        .timeout(Duration::from_secs(2))
        .build()
        .unwrap();
    let deadline = tokio::time::Instant::now() + timeout;
    while tokio::time::Instant::now() < deadline {
        if let Ok(resp) = client.get(url).send().await {
            if resp.status().is_success() {
                return true;
            }
        }
        tokio::time::sleep(Duration::from_millis(500)).await;
    }
    false
}

async fn pull_model(model: &str) -> Result<(), String> {
    let url = format!("http://127.0.0.1:{}/api/pull", OLLAMA_PORT);
    let client = reqwest::Client::builder()
        .timeout(Duration::from_secs(600))
        .build()
        .map_err(|e| e.to_string())?;
    let resp = client
        .post(&url)
        .json(&serde_json::json!({"name": model, "stream": false}))
        .send()
        .await
        .map_err(|e| format!("Pull request failed: {}", e))?;
    if !resp.status().is_success() {
        return Err(format!("Pull returned status {}", resp.status()));
    }
    Ok(())
}

fn summarize_backend_stderr(stderr: &str) -> String {
    let trimmed = stderr.trim();
    if trimmed.is_empty() {
        return "Grandpa server did not start.".into();
    }
    if let Some(module) = missing_python_module(trimmed) {
        return format!(
            "Missing Python dependency: {module}. Run `uv sync --extra server` and enable the relevant optional extra for that feature."
        );
    }
    let last_line = trimmed
        .lines()
        .rev()
        .map(str::trim)
        .find(|line| !line.is_empty())
        .unwrap_or("Grandpa server did not start.");
    let line = last_line
        .strip_prefix("RuntimeError: ")
        .unwrap_or(last_line);
    line.chars().take(500).collect()
}

fn missing_python_module(stderr: &str) -> Option<String> {
    let marker = "ModuleNotFoundError: No module named ";
    let idx = stderr.find(marker)?;
    let rest = stderr[idx + marker.len()..].trim();
    let quote = rest.chars().next()?;
    if quote != '\'' && quote != '"' {
        return None;
    }
    let end = rest[1..].find(quote)?;
    Some(rest[1..1 + end].to_string())
}

// ---------------------------------------------------------------------------
// Backend boot sequence (runs in background after app launch)
// ---------------------------------------------------------------------------

async fn boot_backend(backend: SharedBackend, status: SharedStatus) {
    // Phase 1: Try Ollama briefly. Desktop UI startup must never depend on it.
    {
        let mut s = status.lock().await;
        s.phase = "ollama".into();
        s.detail = "Checking local inference engine...".into();
    }

    // Try the bundled sidecar first, fall back to system ollama
    let ollama_child = {
        let ollama_bin = resolve_bin("ollama");
        let sidecar = tokio::process::Command::new(&ollama_bin)
            .arg("serve")
            .env("OLLAMA_HOST", format!("127.0.0.1:{}", OLLAMA_PORT))
            .stdout(std::process::Stdio::null())
            .stderr(std::process::Stdio::null())
            .spawn();
        match sidecar {
            Ok(child) => Some(child),
            Err(_) => None,
        }
    };

    if let Some(child) = ollama_child {
        backend.lock().await.ollama = Some(ChildHandle { child });
    }

    let ollama_url = format!("http://127.0.0.1:{}/api/tags", OLLAMA_PORT);
    let ollama_ok = wait_for_url(&ollama_url, Duration::from_secs(3)).await;

    {
        let mut s = status.lock().await;
        s.ollama_ready = ollama_ok;
        s.model_ready = false;
        if ollama_ok {
            s.detail = "Inference engine is reachable.".into();
        } else {
            s.detail =
                "Ollama is unavailable. Grandpa will start without local model downloads.".into();
        }
    }

    // Phase 2: Start grandpa serve
    {
        let mut s = status.lock().await;
        s.phase = "server".into();
        s.detail = "Starting API server...".into();
    }

    let uv_bin = resolve_bin("uv");

    // Verify uv is actually installed
    if !std::path::Path::new(&uv_bin).exists() && uv_bin == "uv" {
        let mut s = status.lock().await;
        s.error = Some(
            "Could not find 'uv' (Python package manager). \
             Install it from https://astral.sh/uv then relaunch."
                .into(),
        );
        return;
    }

    let mut project_root = find_project_root();

    if project_root.is_none() {
        // Auto-clone on first launch
        let git_bin = resolve_bin("git");

        // Check that git is installed
        if !std::path::Path::new(&git_bin).exists() && git_bin == "git" {
            let mut s = status.lock().await;
            s.error = Some(
                "Could not find 'git'. \
                 Install it from https://git-scm.com then relaunch."
                    .into(),
            );
            return;
        }

        let target_path = std::path::PathBuf::from(home_dir()).join("Grandpa");
        let clone_target = target_path.display().to_string();

        // If the directory exists but is not a valid project, don't overwrite
        if target_path.exists() && !target_path.join("pyproject.toml").exists() {
            let mut s = status.lock().await;
            s.error = Some(format!(
                "{} exists but is not a valid Grandpa project. \
                 Remove it and relaunch, or set Grandpa_ROOT to the correct path.",
                clone_target,
            ));
            return;
        }

        {
            let mut s = status.lock().await;
            s.detail = "Downloading Grandpa (first launch)...".into();
        }

        let clone_result = tokio::process::Command::new(&git_bin)
            .args([
                "clone",
                "--depth",
                "1",
                "https://github.com/grandpa/grandpa.git",
                &clone_target,
            ])
            .stdout(std::process::Stdio::null())
            .stderr(std::process::Stdio::piped())
            .spawn();

        match clone_result {
            Ok(child) => match child.wait_with_output().await {
                Ok(output) if output.status.success() => {
                    project_root = Some(target_path);
                }
                Ok(output) => {
                    let stderr = String::from_utf8_lossy(&output.stderr);
                    let mut s = status.lock().await;
                    s.error = Some(format!(
                        "Failed to download Grandpa: {}. \
                         Clone manually: git clone https://github.com/grandpa/grandpa.git {}",
                        stderr.trim(),
                        clone_target,
                    ));
                    return;
                }
                Err(e) => {
                    let mut s = status.lock().await;
                    s.error = Some(format!(
                        "Failed to download Grandpa: {}. \
                         Clone manually: git clone https://github.com/grandpa/grandpa.git {}",
                        e, clone_target,
                    ));
                    return;
                }
            },
            Err(e) => {
                let mut s = status.lock().await;
                s.error = Some(format!(
                    "Could not run git: {}. \
                     Install git from https://git-scm.com then relaunch.",
                    e,
                ));
                return;
            }
        }
    }

    // Kill any leftover server on our port from a previous run
    {
        let client = reqwest::Client::builder()
            .timeout(Duration::from_secs(2))
            .build()
            .unwrap();
        if client
            .get(format!("http://127.0.0.1:{}/health", GRANDPA_PORT))
            .send()
            .await
            .is_ok()
        {
            // Something is already listening — try to kill it
            #[cfg(unix)]
            {
                let _ = tokio::process::Command::new("fuser")
                    .args(["-k", &format!("{}/tcp", GRANDPA_PORT)])
                    .output()
                    .await;
                tokio::time::sleep(Duration::from_secs(2)).await;
            }
            #[cfg(target_os = "windows")]
            {
                // Find the PID holding the port via netstat, then kill it
                if let Ok(output) = tokio::process::Command::new("cmd")
                    .args(["/C", &format!(
                        "for /f \"tokens=5\" %a in ('netstat -ano ^| findstr :{port} ^| findstr LISTENING') do taskkill /PID %a /F",
                        port = GRANDPA_PORT,
                    )])
                    .output()
                    .await
                {
                    let _ = output; // best-effort
                }
                tokio::time::sleep(Duration::from_secs(2)).await;
            }
        }
    }

    // Pick a lightweight default id without contacting Ollama or pulling models.
    let startup_model = preferred_model();

    let root = project_root.as_ref().unwrap();

    // Install dependencies automatically (handles fresh clones)
    {
        let mut s = status.lock().await;
        s.detail = "Installing dependencies...".into();
    }
    let _ = tokio::process::Command::new(&uv_bin)
        .args([
            "sync",
            "--extra",
            "server",
            "--extra",
            "inference-cloud",
            "--extra",
            "inference-google",
        ])
        .stdout(std::process::Stdio::null())
        .stderr(std::process::Stdio::null())
        .current_dir(root)
        .status()
        .await;

    {
        let mut s = status.lock().await;
        s.detail = format!(
            "Starting server with {} from {}...",
            startup_model,
            root.display(),
        );
    }

    let mut cmd = tokio::process::Command::new(&uv_bin);
    cmd.args([
        "run",
        "grandpa",
        "serve",
        "--port",
        &GRANDPA_PORT.to_string(),
        "--model",
        startup_model,
        "--agent",
        "simple",
    ])
    .stdout(std::process::Stdio::null())
    .stderr(std::process::Stdio::piped())
    .current_dir(root);

    // Inject cloud API keys from ~/.grandpa/cloud-keys.env
    for (key, value) in read_cloud_keys() {
        cmd.env(&key, &value);
    }
    let grandpa_child = cmd.spawn();

    match grandpa_child {
        Ok(child) => {
            backend.lock().await.grandpa = Some(ChildHandle { child });
        }
        Err(e) => {
            let mut s = status.lock().await;
            s.error = Some(format!(
                "Could not start grandpa server: {}. \
                 Make sure uv is installed (https://astral.sh/uv) and the Grandpa repo is cloned at {}",
                e,
                root.display(),
            ));
            return;
        }
    }

    let server_url = format!("http://127.0.0.1:{}/health", GRANDPA_PORT);
    let server_ok = wait_for_url(&server_url, Duration::from_secs(45)).await;

    if !server_ok {
        // Try to read stderr from the failed process for a useful error
        let mut stderr_msg = String::new();
        {
            let mut mgr = backend.lock().await;
            if let Some(ref mut h) = mgr.grandpa {
                if let Some(ref mut stderr) = h.child.stderr.take() {
                    use tokio::io::AsyncReadExt;
                    let mut buf = vec![0u8; 4096];
                    if let Ok(n) = stderr.read(&mut buf).await {
                        stderr_msg = String::from_utf8_lossy(&buf[..n]).to_string();
                    }
                }
            }
        }
        let detail = if stderr_msg.is_empty() {
            format!(
                "Grandpa server did not start. Check that:\n\
                 1. uv is installed ({})\n\
                 2. The Grandpa repo is at {}\n\
                 3. Run 'uv sync' in that directory",
                uv_bin,
                root.display(),
            )
        } else {
            format!(
                "Server failed to start: {}",
                summarize_backend_stderr(&stderr_msg)
            )
        };
        let mut s = status.lock().await;
        s.error = Some(detail);
        return;
    }

    {
        let mut s = status.lock().await;
        s.server_ready = true;
        s.phase = "ready".into();
        s.detail = "All systems ready.".into();
    }

    // Model downloads are intentionally user-confirmed through chat/model flows.
}

// ---------------------------------------------------------------------------
// Tauri commands
// ---------------------------------------------------------------------------

fn api_base() -> String {
    format!("http://127.0.0.1:{}", GRANDPA_PORT)
}

#[tauri::command]
async fn get_setup_status(state: tauri::State<'_, SharedStatus>) -> Result<SetupStatus, String> {
    Ok(state.lock().await.clone())
}

#[tauri::command]
fn get_api_base() -> String {
    api_base()
}

#[tauri::command]
async fn start_backend(
    backend: tauri::State<'_, SharedBackend>,
    status: tauri::State<'_, SharedStatus>,
) -> Result<(), String> {
    let b = backend.inner().clone();
    let s = status.inner().clone();
    tauri::async_runtime::spawn(boot_backend(b, s));
    Ok(())
}

#[tauri::command]
async fn stop_backend(backend: tauri::State<'_, SharedBackend>) -> Result<(), String> {
    backend.lock().await.stop_all().await;
    Ok(())
}

#[tauri::command]
async fn floating_backend_status(
    status: tauri::State<'_, SharedStatus>,
) -> Result<FloatingBackendStatus, String> {
    let snapshot = status.lock().await.clone();
    let state = if snapshot.error.is_some() {
        "error"
    } else if snapshot.server_ready {
        "running"
    } else if snapshot.phase == "stopped" {
        "stopped"
    } else {
        "checking"
    };
    Ok(FloatingBackendStatus {
        state: state.into(),
        detail: snapshot.error.unwrap_or_else(|| snapshot.detail.clone()),
        api_base: api_base(),
    })
}

#[tauri::command]
async fn floating_start_backend(
    backend: tauri::State<'_, SharedBackend>,
    status: tauri::State<'_, SharedStatus>,
) -> Result<FloatingBackendStatus, String> {
    {
        let snapshot = status.lock().await.clone();
        if snapshot.server_ready || (snapshot.error.is_none() && snapshot.phase != "stopped") {
            return floating_backend_status(status).await;
        }
    }
    let b = backend.inner().clone();
    let s = status.inner().clone();
    tauri::async_runtime::spawn(boot_backend(b, s));
    floating_backend_status(status).await
}

#[tauri::command]
async fn floating_stop_backend(
    backend: tauri::State<'_, SharedBackend>,
    status: tauri::State<'_, SharedStatus>,
) -> Result<FloatingBackendStatus, String> {
    backend.lock().await.stop_all().await;
    {
        let mut snapshot = status.lock().await;
        snapshot.phase = "stopped".into();
        snapshot.detail = "Grandpa backend is stopped.".into();
        snapshot.ollama_ready = false;
        snapshot.server_ready = false;
        snapshot.model_ready = false;
        snapshot.error = None;
    }
    floating_backend_status(status).await
}

#[tauri::command]
fn floating_open_main_app(app: tauri::AppHandle) -> Result<(), String> {
    if let Some(window) = app.get_webview_window("main") {
        window.show().map_err(|e| e.to_string())?;
        window.set_focus().map_err(|e| e.to_string())?;
        return Ok(());
    }
    Err("Main Grandpa window is not available.".into())
}

#[tauri::command]
fn show_floating_icon(app: tauri::AppHandle) -> Result<(), String> {
    ensure_floating_window(&app, "show command")?;
    Ok(())
}

#[tauri::command]
fn hide_floating_icon(app: tauri::AppHandle) -> Result<(), String> {
    let window = app
        .get_webview_window(FLOATING_WINDOW_LABEL)
        .ok_or("Floating Grandpa window is not available.")?;
    window.hide().map_err(|e| e.to_string())
}

#[tauri::command]
fn floating_interaction_status(app: tauri::AppHandle) -> Result<FloatingInteractionStatus, String> {
    let window = app
        .get_webview_window(FLOATING_WINDOW_LABEL)
        .ok_or("Floating Grandpa window is not available.")?;
    Ok(floating_interaction_status_for_window(&window, false))
}

#[tauri::command]
fn ensure_floating_interactive(app: tauri::AppHandle) -> Result<FloatingInteractionStatus, String> {
    let window = app
        .get_webview_window(FLOATING_WINDOW_LABEL)
        .ok_or("Floating Grandpa window is not available.")?;
    Ok(ensure_floating_interactive_window(
        &window,
        "frontend command",
    ))
}

#[tauri::command]
fn get_floating_position() -> Option<FloatingPosition> {
    read_floating_position_file()
}

#[tauri::command]
fn save_floating_position(position: FloatingPosition) -> Result<(), String> {
    let position = valid_floating_position(position).ok_or("Invalid floating window position.")?;
    let path = floating_position_path();
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent).map_err(|e| e.to_string())?;
    }
    let data = serde_json::to_string_pretty(&position).map_err(|e| e.to_string())?;
    std::fs::write(path, data).map_err(|e| e.to_string())
}

#[tauri::command]
async fn check_health(api_url: String) -> Result<serde_json::Value, String> {
    let url = format!(
        "{}/health",
        if api_url.is_empty() {
            api_base()
        } else {
            api_url
        }
    );
    let resp = reqwest::get(&url)
        .await
        .map_err(|e| format!("Connection failed: {}", e))?;
    resp.json()
        .await
        .map_err(|e| format!("Invalid response: {}", e))
}

#[tauri::command]
async fn fetch_energy(api_url: String) -> Result<serde_json::Value, String> {
    let base = if api_url.is_empty() {
        api_base()
    } else {
        api_url
    };
    let resp = reqwest::get(format!("{}/v1/telemetry/energy", base))
        .await
        .map_err(|e| format!("Connection failed: {}", e))?;
    resp.json()
        .await
        .map_err(|e| format!("Invalid response: {}", e))
}

#[tauri::command]
async fn fetch_telemetry(api_url: String) -> Result<serde_json::Value, String> {
    let base = if api_url.is_empty() {
        api_base()
    } else {
        api_url
    };
    let resp = reqwest::get(format!("{}/v1/telemetry/stats", base))
        .await
        .map_err(|e| format!("Connection failed: {}", e))?;
    resp.json()
        .await
        .map_err(|e| format!("Invalid response: {}", e))
}

#[tauri::command]
async fn fetch_traces(api_url: String, limit: u32) -> Result<serde_json::Value, String> {
    let base = if api_url.is_empty() {
        api_base()
    } else {
        api_url
    };
    let resp = reqwest::get(format!("{}/v1/traces?limit={}", base, limit))
        .await
        .map_err(|e| format!("Connection failed: {}", e))?;
    resp.json()
        .await
        .map_err(|e| format!("Invalid response: {}", e))
}

#[tauri::command]
async fn fetch_trace(api_url: String, trace_id: String) -> Result<serde_json::Value, String> {
    let base = if api_url.is_empty() {
        api_base()
    } else {
        api_url
    };
    let resp = reqwest::get(format!("{}/v1/traces/{}", base, trace_id))
        .await
        .map_err(|e| format!("Connection failed: {}", e))?;
    resp.json()
        .await
        .map_err(|e| format!("Invalid response: {}", e))
}

#[tauri::command]
async fn fetch_learning_stats(api_url: String) -> Result<serde_json::Value, String> {
    let base = if api_url.is_empty() {
        api_base()
    } else {
        api_url
    };
    let resp = reqwest::get(format!("{}/v1/learning/stats", base))
        .await
        .map_err(|e| format!("Connection failed: {}", e))?;
    resp.json()
        .await
        .map_err(|e| format!("Invalid response: {}", e))
}

#[tauri::command]
async fn fetch_learning_policy(api_url: String) -> Result<serde_json::Value, String> {
    let base = if api_url.is_empty() {
        api_base()
    } else {
        api_url
    };
    let resp = reqwest::get(format!("{}/v1/learning/policy", base))
        .await
        .map_err(|e| format!("Connection failed: {}", e))?;
    resp.json()
        .await
        .map_err(|e| format!("Invalid response: {}", e))
}

#[tauri::command]
async fn fetch_memory_stats(api_url: String) -> Result<serde_json::Value, String> {
    let base = if api_url.is_empty() {
        api_base()
    } else {
        api_url
    };
    let resp = reqwest::get(format!("{}/v1/memory/stats", base))
        .await
        .map_err(|e| format!("Connection failed: {}", e))?;
    resp.json()
        .await
        .map_err(|e| format!("Invalid response: {}", e))
}

#[tauri::command]
async fn search_memory(
    api_url: String,
    query: String,
    top_k: u32,
) -> Result<serde_json::Value, String> {
    let base = if api_url.is_empty() {
        api_base()
    } else {
        api_url
    };
    let client = reqwest::Client::new();
    let resp = client
        .post(format!("{}/v1/memory/search", base))
        .json(&serde_json::json!({"query": query, "top_k": top_k}))
        .send()
        .await
        .map_err(|e| format!("Connection failed: {}", e))?;
    resp.json()
        .await
        .map_err(|e| format!("Invalid response: {}", e))
}

#[tauri::command]
async fn fetch_agents(api_url: String) -> Result<serde_json::Value, String> {
    let base = if api_url.is_empty() {
        api_base()
    } else {
        api_url
    };
    let resp = reqwest::get(format!("{}/v1/agents", base))
        .await
        .map_err(|e| format!("Connection failed: {}", e))?;
    resp.json()
        .await
        .map_err(|e| format!("Invalid response: {}", e))
}

#[tauri::command]
async fn fetch_models(api_url: String) -> Result<serde_json::Value, String> {
    let base = if api_url.is_empty() {
        api_base()
    } else {
        api_url
    };
    let resp = reqwest::get(format!("{}/v1/models", base))
        .await
        .map_err(|e| format!("Connection failed: {}", e))?;
    resp.json()
        .await
        .map_err(|e| format!("Invalid response: {}", e))
}

#[tauri::command]
async fn run_grandpa_command(args: Vec<String>) -> Result<String, String> {
    let mut cmd_args = vec!["run".to_string(), "grandpa".to_string()];
    cmd_args.extend(args);
    let uv_bin = resolve_bin("uv");
    let output = tokio::process::Command::new(&uv_bin)
        .args(&cmd_args)
        .output()
        .await
        .map_err(|e| format!("Failed to launch grandpa: {}", e))?;

    if output.status.success() {
        Ok(String::from_utf8_lossy(&output.stdout).to_string())
    } else {
        Err(String::from_utf8_lossy(&output.stderr).to_string())
    }
}

/// Transcribe audio via the speech API endpoint.
#[tauri::command]
async fn transcribe_audio(
    api_url: String,
    audio_data: Vec<u8>,
    filename: String,
) -> Result<serde_json::Value, String> {
    let url = format!("{}/v1/speech/transcribe", api_url);
    let client = reqwest::Client::new();

    let part = reqwest::multipart::Part::bytes(audio_data)
        .file_name(filename)
        .mime_str("audio/webm")
        .map_err(|e| format!("Failed to create multipart: {}", e))?;

    let form = reqwest::multipart::Form::new().part("file", part);

    let resp = client
        .post(&url)
        .multipart(form)
        .send()
        .await
        .map_err(|e| format!("Connection failed: {}", e))?;
    let body: serde_json::Value = resp
        .json()
        .await
        .map_err(|e| format!("Invalid response: {}", e))?;
    Ok(body)
}

// ---------------------------------------------------------------------------
// Cloud API key management
// ---------------------------------------------------------------------------

/// Path to the cloud keys file (~/.grandpa/cloud-keys.env).
fn cloud_keys_path() -> std::path::PathBuf {
    let home = home_dir();
    std::path::PathBuf::from(home)
        .join(".grandpa")
        .join("cloud-keys.env")
}

const ALLOWED_CLOUD_KEY_NAMES: &[&str] = &[
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "GEMINI_API_KEY",
    "OPENROUTER_API_KEY",
];

fn validate_cloud_key(key_name: &str, key_value: &str) -> Result<(), String> {
    if !ALLOWED_CLOUD_KEY_NAMES.contains(&key_name) {
        return Err("Unsupported cloud key name".into());
    }
    if key_value.contains(['\r', '\n', '\0']) {
        return Err("Cloud key contains invalid control characters".into());
    }
    Ok(())
}

/// Read cloud keys from disk and return as key=value pairs.
fn read_cloud_keys() -> Vec<(String, String)> {
    let path = cloud_keys_path();
    let mut keys = Vec::new();
    if let Ok(contents) = std::fs::read_to_string(&path) {
        for line in contents.lines() {
            let line = line.trim();
            if line.is_empty() || line.starts_with('#') {
                continue;
            }
            if let Some((k, v)) = line.split_once('=') {
                let key = k.trim();
                let value = v.trim();
                if validate_cloud_key(key, value).is_ok() {
                    keys.push((key.to_string(), value.to_string()));
                }
            }
        }
    }
    keys
}

/// Save a single cloud API key to the keys file.
#[tauri::command]
async fn save_cloud_key(key_name: String, key_value: String) -> Result<(), String> {
    validate_cloud_key(&key_name, &key_value)?;
    let path = cloud_keys_path();
    // Ensure directory exists
    if let Some(parent) = path.parent() {
        let _ = std::fs::create_dir_all(parent);
    }

    // Read existing keys, update/add the one being saved
    let mut keys: Vec<(String, String)> = read_cloud_keys()
        .into_iter()
        .filter(|(k, _)| k != &key_name)
        .collect();
    if !key_value.is_empty() {
        keys.push((key_name, key_value));
    }

    // Write back
    let content: String = keys
        .iter()
        .map(|(k, v)| format!("{}={}", k, v))
        .collect::<Vec<_>>()
        .join("\n");
    std::fs::write(&path, content + "\n").map_err(|e| format!("Failed to save key: {}", e))?;

    // Set permissions to owner-only (chmod 600)
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        let _ = std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o600));
    }

    // Tell the running server to hot-reload its cloud engine so the user
    // doesn't need to restart the app after entering an API key.
    let reload_url = format!("http://127.0.0.1:{}/v1/cloud/reload", GRANDPA_PORT);
    let _ = reqwest::Client::new()
        .post(&reload_url)
        .timeout(std::time::Duration::from_secs(10))
        .send()
        .await;

    Ok(())
}

/// Get which cloud providers have keys configured (without exposing values).
#[tauri::command]
async fn get_cloud_key_status() -> Result<serde_json::Value, String> {
    let keys = read_cloud_keys();
    let status: Vec<serde_json::Value> = keys
        .iter()
        .map(|(k, v)| serde_json::json!({ "key": k, "set": !v.is_empty() }))
        .collect();
    Ok(serde_json::json!(status))
}

/// Pull a model via Ollama (called from frontend download button).
#[tauri::command]
async fn pull_ollama_model(model_name: String) -> Result<serde_json::Value, String> {
    pull_model(&model_name)
        .await
        .map_err(|e| format!("Failed to pull {}: {}", model_name, e))?;
    Ok(serde_json::json!({"status": "ok", "model": model_name}))
}

/// Delete a model from Ollama.
#[tauri::command]
async fn delete_ollama_model(model_name: String) -> Result<serde_json::Value, String> {
    let url = format!("http://127.0.0.1:{}/api/delete", OLLAMA_PORT);
    let client = reqwest::Client::builder()
        .timeout(Duration::from_secs(30))
        .build()
        .map_err(|e| e.to_string())?;
    let resp = client
        .delete(&url)
        .json(&serde_json::json!({"name": model_name}))
        .send()
        .await
        .map_err(|e| format!("Delete failed: {}", e))?;
    if !resp.status().is_success() {
        return Err(format!("Delete returned status {}", resp.status()));
    }
    Ok(serde_json::json!({"status": "deleted", "model": model_name}))
}

/// Check speech backend health.
#[tauri::command]
async fn speech_health(api_url: String) -> Result<serde_json::Value, String> {
    let url = format!("{}/v1/speech/health", api_url);
    let resp = reqwest::get(&url)
        .await
        .map_err(|e| format!("Connection failed: {}", e))?;
    let body: serde_json::Value = resp
        .json()
        .await
        .map_err(|e| format!("Invalid response: {}", e))?;
    Ok(body)
}

// ---------------------------------------------------------------------------
// Native macOS overlay — NSPanel + WKWebView, entirely bypassing Tauri's
// window management so we get proper always-on-top, transparency, non-
// activating panel behaviour and cross-Space support.
// ---------------------------------------------------------------------------

#[cfg(target_os = "macos")]
mod native_overlay {
    use objc::declare::ClassDecl;
    use objc::runtime::{Class, Object, Sel, BOOL, NO, YES};
    use objc::{class, msg_send, sel, sel_impl};
    use std::sync::atomic::{AtomicUsize, Ordering};

    /// Raw pointer to the NSPanel, stored as usize for atomicity.
    static PANEL_PTR: AtomicUsize = AtomicUsize::new(0);
    /// Raw pointer to the WKWebView inside the panel.
    static WEBVIEW_PTR: AtomicUsize = AtomicUsize::new(0);
    /// Raw pointer to the previously-frontmost NSRunningApplication.
    static PREV_APP: AtomicUsize = AtomicUsize::new(0);

    // CoreGraphics geometry types expected by AppKit.
    #[repr(C)]
    #[derive(Copy, Clone)]
    struct CGPoint {
        x: f64,
        y: f64,
    }
    #[repr(C)]
    #[derive(Copy, Clone)]
    struct CGSize {
        width: f64,
        height: f64,
    }
    #[repr(C)]
    #[derive(Copy, Clone)]
    struct CGRect {
        origin: CGPoint,
        size: CGSize,
    }

    /// Create an autoreleased NSString from a Rust &str.
    unsafe fn nsstring(s: &str) -> *mut Object {
        let obj: *mut Object = msg_send![class!(NSString), alloc];
        msg_send![obj,
            initWithBytes: s.as_ptr()
            length: s.len()
            encoding: 4usize  // NSUTF8StringEncoding
        ]
    }

    // ------------------------------------------------------------------
    // Conversation persistence
    // ------------------------------------------------------------------

    fn conversation_path() -> std::path::PathBuf {
        std::path::PathBuf::from(super::home_dir())
            .join(".grandpa")
            .join("overlay-conversation.json")
    }

    pub fn load_conversation() -> String {
        std::fs::read_to_string(conversation_path()).unwrap_or_else(|_| "[]".into())
    }

    /// Read cloud API keys and return a JSON array of model IDs
    /// whose provider has a key configured.
    fn cloud_models_json() -> String {
        let keys = super::read_cloud_keys();
        let mut models: Vec<&str> = Vec::new();
        for (name, value) in &keys {
            if value.is_empty() {
                continue;
            }
            match name.as_str() {
                "OPENAI_API_KEY" => models.extend(["gpt-4o", "gpt-4o-mini"]),
                "ANTHROPIC_API_KEY" => {
                    models.extend(["claude-sonnet-4-20250514", "claude-haiku-4-20250414"])
                }
                "GEMINI_API_KEY" | "GOOGLE_API_KEY" => {
                    models.extend(["gemini-2.5-flash", "gemini-2.5-pro"])
                }
                _ => {}
            }
        }
        serde_json::to_string(&models).unwrap_or_else(|_| "[]".into())
    }

    fn save_conversation(json: &str) {
        let path = conversation_path();
        if let Some(parent) = path.parent() {
            let _ = std::fs::create_dir_all(parent);
        }
        let _ = std::fs::write(&path, json);
    }

    /// Apply every transparency trick to the WKWebView.
    /// Called once at creation and again after the page finishes loading.
    unsafe fn force_transparent(wv: *mut Object) {
        let clear: *mut Object = msg_send![class!(NSColor), clearColor];
        let _: () = msg_send![wv, _setDrawsBackground: NO];
        let no_num: *mut Object = msg_send![class!(NSNumber), numberWithBool: NO];
        let _: () = msg_send![wv, setValue: no_num forKey: nsstring("drawsBackground")];
        let _: () = msg_send![wv, setUnderPageBackgroundColor: clear];
        // Also inject CSS to nuke any remaining background
        let js = nsstring(
            "document.documentElement.style.background='transparent';\
             document.body.style.background='transparent';",
        );
        let nil: *mut Object = std::ptr::null_mut();
        let _: () = msg_send![wv, evaluateJavaScript: js completionHandler: nil];
    }

    // ------------------------------------------------------------------
    // Public API (must be called on the main thread)
    // ------------------------------------------------------------------

    /// Build the native overlay panel.  Call once during app setup.
    pub unsafe fn create(html: &str, api_port: u16) {
        // --- Custom NSPanel subclass that accepts keyboard input ------
        if Class::get("GrandpaOverlayPanel").is_none() {
            let sup = Class::get("NSPanel").unwrap();
            let mut decl = ClassDecl::new("GrandpaOverlayPanel", sup).unwrap();
            extern "C" fn yes(_: &Object, _: Sel) -> BOOL {
                YES
            }
            decl.add_method(
                sel!(canBecomeKeyWindow),
                yes as extern "C" fn(&Object, Sel) -> BOOL,
            );
            decl.register();
        }

        // --- WKNavigationDelegate — re-apply transparency after load --
        if Class::get("GrandpaOverlayNavDelegate").is_none() {
            let sup = Class::get("NSObject").unwrap();
            let mut decl = ClassDecl::new("GrandpaOverlayNavDelegate", sup).unwrap();
            extern "C" fn did_finish(_: &Object, _: Sel, wv: *mut Object, _nav: *mut Object) {
                unsafe {
                    force_transparent(wv);
                }
            }
            decl.add_method(
                sel!(webView:didFinishNavigation:),
                did_finish as extern "C" fn(&Object, Sel, *mut Object, *mut Object),
            );
            decl.register();
        }

        // --- WKScriptMessageHandler so JS can call hide() ------------
        if Class::get("GrandpaOverlayMsgHandler").is_none() {
            let sup = Class::get("NSObject").unwrap();
            let mut decl = ClassDecl::new("GrandpaOverlayMsgHandler", sup).unwrap();
            extern "C" fn on_msg(_: &Object, _: Sel, _ctrl: *mut Object, msg: *mut Object) {
                unsafe {
                    let body: *mut Object = msg_send![msg, body];
                    if body.is_null() {
                        return;
                    }
                    let c: *const std::os::raw::c_char = msg_send![body, UTF8String];
                    if c.is_null() {
                        return;
                    }
                    if let Ok(s) = std::ffi::CStr::from_ptr(c).to_str() {
                        if s == "hide" {
                            hide();
                        } else if let Some(json) = s.strip_prefix("save:") {
                            save_conversation(json);
                        } else if let Some(coords) = s.strip_prefix("drag:") {
                            drag(coords);
                        }
                    }
                }
            }
            decl.add_method(
                sel!(userContentController:didReceiveScriptMessage:),
                on_msg as extern "C" fn(&Object, Sel, *mut Object, *mut Object),
            );
            decl.register();
        }

        // --- Create the NSPanel --------------------------------------
        let frame = CGRect {
            origin: CGPoint { x: 0.0, y: 0.0 },
            size: CGSize {
                width: 560.0,
                height: 400.0,
            },
        };
        // NSWindowStyleMaskNonactivatingPanel = 1 << 7
        let style: u64 = 1 << 7;

        let cls = Class::get("GrandpaOverlayPanel").unwrap();
        let panel: *mut Object = msg_send![cls, alloc];
        let panel: *mut Object = msg_send![panel,
            initWithContentRect: frame
            styleMask: style
            backing: 2u64       // NSBackingStoreBuffered
            defer: NO
        ];

        // Window level — NSFloatingWindowLevel (3).
        let _: () = msg_send![panel, setLevel: 3_i64];
        // canJoinAllSpaces (1) | fullScreenAuxiliary (1<<8)
        let _: () = msg_send![panel, setCollectionBehavior: 257_u64];
        let _: () = msg_send![panel, setHidesOnDeactivate: NO];
        let _: () = msg_send![panel, setOpaque: NO];
        let _: () = msg_send![panel, setHasShadow: NO];
        let _: () = msg_send![panel, setMovableByWindowBackground: YES];

        let clear: *mut Object = msg_send![class!(NSColor), clearColor];
        let _: () = msg_send![panel, setBackgroundColor: clear];
        let _: () = msg_send![panel, center];

        // --- WKWebView -----------------------------------------------
        let cfg: *mut Object = msg_send![class!(WKWebViewConfiguration), alloc];
        let cfg: *mut Object = msg_send![cfg, init];

        // Attach message handler ("overlay" channel)
        let hcls = Class::get("GrandpaOverlayMsgHandler").unwrap();
        let handler: *mut Object = msg_send![hcls, alloc];
        let handler: *mut Object = msg_send![handler, init];
        let uc: *mut Object = msg_send![cfg, userContentController];
        let _: () = msg_send![uc,
            addScriptMessageHandler: handler
            name: nsstring("overlay")
        ];

        let wv: *mut Object = msg_send![class!(WKWebView), alloc];
        let wv: *mut Object = msg_send![wv,
            initWithFrame: frame
            configuration: cfg
        ];

        // ---- Make the webview fully transparent ----
        force_transparent(wv);

        // Set navigation delegate so we re-apply after page loads
        let nav_cls = Class::get("GrandpaOverlayNavDelegate").unwrap();
        let nav_del: *mut Object = msg_send![nav_cls, alloc];
        let nav_del: *mut Object = msg_send![nav_del, init];
        let _: () = msg_send![wv, setNavigationDelegate: nav_del];

        let _: () = msg_send![panel, setContentView: wv];
        WEBVIEW_PTR.store(wv as usize, Ordering::SeqCst);

        // Inject saved conversation into the HTML template, then load it.
        // Use the API server as the base URL so fetch() is same-origin.
        // Escape "</" so the JSON can't prematurely close the <script> tag.
        // ("\/" is valid JSON — resolves back to "/" when parsed.)
        let saved = load_conversation().replace("</", "<\\/");
        let cloud = cloud_models_json();
        let filled = html
            .replace("__SAVED_MESSAGES__", &saved)
            .replace("__CLOUD_MODELS__", &cloud);
        let base_str = nsstring(&format!("http://127.0.0.1:{}", api_port));
        let base_url: *mut Object = msg_send![class!(NSURL), URLWithString: base_str];
        let _: () = msg_send![wv,
            loadHTMLString: nsstring(&filled)
            baseURL: base_url
        ];

        PANEL_PTR.store(panel as usize, Ordering::SeqCst);
    }

    pub unsafe fn toggle() {
        let ptr = PANEL_PTR.load(Ordering::SeqCst);
        if ptr == 0 {
            return;
        }
        let panel = ptr as *mut Object;
        let vis: BOOL = msg_send![panel, isVisible];
        if vis != NO {
            hide();
        } else {
            show();
        }
    }

    pub unsafe fn show() {
        let ptr = PANEL_PTR.load(Ordering::SeqCst);
        if ptr == 0 {
            return;
        }
        let panel = ptr as *mut Object;

        // Re-apply transparency every time (the webview can reset it)
        let wv_ptr = WEBVIEW_PTR.load(Ordering::SeqCst);
        if wv_ptr != 0 {
            force_transparent(wv_ptr as *mut Object);
        }

        // Remember the currently-frontmost app so we can restore it.
        let ws: *mut Object = msg_send![class!(NSWorkspace), sharedWorkspace];
        let front: *mut Object = msg_send![ws, frontmostApplication];
        if !front.is_null() {
            let _: () = msg_send![front, retain];
            let old = PREV_APP.swap(front as usize, Ordering::SeqCst);
            if old != 0 {
                let _: () = msg_send![(old as *mut Object), release];
            }
        }

        // Activate our process so the panel receives keyboard input.
        let app: *mut Object = msg_send![class!(NSApplication), sharedApplication];
        let _: () = msg_send![app, activateIgnoringOtherApps: YES];
        let nil: *mut Object = std::ptr::null_mut();
        let _: () = msg_send![panel, makeKeyAndOrderFront: nil];

        // Focus the text field inside the webview.
        let wv: *mut Object = msg_send![panel, contentView];
        let js = nsstring("document.getElementById('input').focus()");
        let _: () = msg_send![wv, evaluateJavaScript: js completionHandler: nil];
    }

    /// Move the panel by a screen-space delta (called from JS drag handler).
    unsafe fn drag(coords: &str) {
        let ptr = PANEL_PTR.load(Ordering::SeqCst);
        if ptr == 0 {
            return;
        }
        let panel = ptr as *mut Object;
        let Some((dxs, dys)) = coords.split_once(',') else {
            return;
        };
        let Ok(dx) = dxs.parse::<f64>() else { return };
        let Ok(dy) = dys.parse::<f64>() else { return };
        // NSWindow frame origin is bottom-left; screen Y increases upward,
        // but mouse screenY increases downward, so invert dy.
        let frame: CGRect = msg_send![panel, frame];
        let origin = CGPoint {
            x: frame.origin.x + dx,
            y: frame.origin.y - dy,
        };
        let _: () = msg_send![panel, setFrameOrigin: origin];
    }

    pub unsafe fn hide() {
        let ptr = PANEL_PTR.load(Ordering::SeqCst);
        if ptr == 0 {
            return;
        }
        let panel = ptr as *mut Object;
        let nil: *mut Object = std::ptr::null_mut();
        let _: () = msg_send![panel, orderOut: nil];

        // Give focus back to whatever app was frontmost before.
        let prev = PREV_APP.swap(0, Ordering::SeqCst);
        if prev != 0 {
            let prev_app = prev as *mut Object;
            let _: BOOL = msg_send![prev_app, activateWithOptions: 2_u64];
            let _: () = msg_send![prev_app, release];
        }
    }
}

/// Dispatch a closure onto the main thread via GCD.
#[cfg(target_os = "macos")]
fn on_main_thread(f: impl FnOnce() + Send + 'static) {
    dispatch::Queue::main().exec_async(f);
}

// ---------------------------------------------------------------------------
// Overlay Tauri commands (thin wrappers that dispatch to the main thread)
// ---------------------------------------------------------------------------

#[tauri::command]
async fn get_overlay_conversation() -> Result<String, String> {
    #[cfg(target_os = "macos")]
    {
        return Ok(native_overlay::load_conversation());
    }
    #[cfg(not(target_os = "macos"))]
    Ok("[]".into())
}

#[tauri::command]
async fn toggle_overlay() -> Result<(), String> {
    #[cfg(target_os = "macos")]
    on_main_thread(|| unsafe { native_overlay::toggle() });
    Ok(())
}

#[tauri::command]
async fn hide_overlay() -> Result<(), String> {
    #[cfg(target_os = "macos")]
    on_main_thread(|| unsafe { native_overlay::hide() });
    Ok(())
}

// ---------------------------------------------------------------------------
// App entry point
// ---------------------------------------------------------------------------

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let backend: SharedBackend = Arc::new(Mutex::new(BackendManager::default()));
    let status: SharedStatus = Arc::new(Mutex::new(SetupStatus::default()));

    let boot_backend_ref = backend.clone();
    let boot_status_ref = status.clone();

    tauri::Builder::default()
        .manage(backend.clone())
        .manage(status.clone())
        .plugin(tauri_plugin_notification::init())
        .plugin(tauri_plugin_global_shortcut::Builder::new().build())
        .plugin(tauri_plugin_autostart::init(
            MacosLauncher::LaunchAgent,
            Some(vec!["--hidden"]),
        ))
        .plugin(tauri_plugin_updater::Builder::new().build())
        .plugin(tauri_plugin_process::init())
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_single_instance::init(|app, args, _cwd| {
            if !args_request_hidden(args.iter().map(String::as_str)) {
                if let Some(window) = app.get_webview_window("main") {
                    let _ = window.set_focus();
                }
            }
            if let Err(error) = ensure_floating_window(app, "single-instance activation") {
                eprintln!("Floating diagnostics single-instance ensure failed: {error}");
            }
        }))
        .setup(move |app| {
            let start_hidden = current_launch_requests_hidden();

            // System tray
            let show = MenuItemBuilder::with_id("show", "Show / Hide").build(app)?;
            let show_floating =
                MenuItemBuilder::with_id("show_floating", "Show Floating Icon").build(app)?;
            let hide_floating =
                MenuItemBuilder::with_id("hide_floating", "Hide Floating Icon").build(app)?;
            let health = MenuItemBuilder::with_id("health", "Health: starting...")
                .enabled(false)
                .build(app)?;
            let quit = MenuItemBuilder::with_id("quit", "Quit Grandpa").build(app)?;

            let menu = MenuBuilder::new(app)
                .item(&show)
                .item(&show_floating)
                .item(&hide_floating)
                .separator()
                .item(&health)
                .separator()
                .item(&quit)
                .build()?;

            if let Some(icon) = app.default_window_icon() {
                let _tray = TrayIconBuilder::with_id("main")
                    .icon(icon.clone())
                    .tooltip("Grandpa")
                    .menu(&menu)
                    .on_menu_event(move |app, event| match event.id().as_ref() {
                        "show" => {
                            if let Some(window) = app.get_webview_window("main") {
                                if window.is_visible().unwrap_or(false) {
                                    let _ = window.hide();
                                } else {
                                    let _ = window.show();
                                    let _ = window.set_focus();
                                }
                            }
                        }
                        "show_floating" => {
                            if let Err(error) = ensure_floating_window(app, "tray show") {
                                eprintln!("Floating diagnostics tray show failed: {error}");
                            }
                        }
                        "hide_floating" => {
                            if let Some(window) = app.get_webview_window(FLOATING_WINDOW_LABEL) {
                                let _ = window.hide();
                            }
                        }
                        "quit" => {
                            app.exit(0);
                        }
                        _ => {}
                    })
                    .build(app)?;
            }

            if start_hidden {
                if let Some(window) = app.get_webview_window("main") {
                    let _ = window.hide();
                }
            }

            let floating = ensure_floating_window(app.handle(), "app startup")?;
            #[cfg(debug_assertions)]
            {
                let config = floating_window_config();
                eprintln!("Floating window created");
                eprintln!(
                    "Floating window visible: {}",
                    floating.is_visible().unwrap_or(false)
                );
                eprintln!(
                    "Floating window size: {}x{}",
                    config.collapsed_width, config.collapsed_height
                );
                if let Ok(position) = floating.outer_position() {
                    eprintln!("Floating window position: {},{}", position.x, position.y);
                }
            }

            // Create native macOS overlay panel
            #[cfg(target_os = "macos")]
            unsafe {
                native_overlay::create(include_str!("overlay.html"), GRANDPA_PORT);
            }

            // Register Cmd+Shift+Space to toggle the native overlay.
            // The current global shortcut action is macOS-only; registering it
            // on Windows can conflict with OS/input shortcuts while doing
            // nothing useful.
            #[cfg(target_os = "macos")]
            {
                use tauri_plugin_global_shortcut::{
                    Code, GlobalShortcutExt, Modifiers, Shortcut, ShortcutState,
                };
                let sc = Shortcut::new(Some(Modifiers::META | Modifiers::SHIFT), Code::Space);
                if let Err(e) = app.global_shortcut().on_shortcut(sc, |_app, _sc, ev| {
                    if ev.state == ShortcutState::Pressed {
                        unsafe {
                            native_overlay::toggle();
                        }
                    }
                }) {
                    eprintln!("Warning: could not register Cmd+Shift+Space (non-fatal): {e}");
                }
            }

            // Auto-start backend services on launch
            tauri::async_runtime::spawn(boot_backend(boot_backend_ref, boot_status_ref));

            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            get_setup_status,
            get_api_base,
            start_backend,
            stop_backend,
            floating_backend_status,
            floating_start_backend,
            floating_stop_backend,
            floating_open_main_app,
            show_floating_icon,
            hide_floating_icon,
            floating_interaction_status,
            ensure_floating_interactive,
            get_floating_position,
            save_floating_position,
            check_health,
            fetch_energy,
            fetch_telemetry,
            fetch_traces,
            fetch_trace,
            fetch_learning_stats,
            fetch_learning_policy,
            fetch_memory_stats,
            search_memory,
            fetch_agents,
            fetch_models,
            run_grandpa_command,
            transcribe_audio,
            speech_health,
            pull_ollama_model,
            delete_ollama_model,
            save_cloud_key,
            get_cloud_key_status,
            toggle_overlay,
            hide_overlay,
            get_overlay_conversation,
        ])
        .build(tauri::generate_context!())
        .expect("error while building Grandpa Desktop")
        .run(move |_app, event| {
            if let tauri::RunEvent::ExitRequested { .. } = event {
                let b = backend.clone();
                tauri::async_runtime::spawn(async move {
                    b.lock().await.stop_all().await;
                });
            }
        });
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn cloud_key_validation_accepts_supported_provider_keys() {
        for name in ALLOWED_CLOUD_KEY_NAMES {
            assert!(validate_cloud_key(name, "secret-value").is_ok());
        }
    }

    #[test]
    fn cloud_key_validation_rejects_environment_injection() {
        assert!(validate_cloud_key("PATH", "C:\\malicious").is_err());
        assert!(validate_cloud_key("OPENAI_API_KEY\nPATH", "secret").is_err());
        assert!(validate_cloud_key("OPENAI_API_KEY", "secret\nPATH=C:\\malicious").is_err());
        assert!(validate_cloud_key("OPENAI_API_KEY", "secret\rOTHER=value").is_err());
        assert!(validate_cloud_key("OPENAI_API_KEY", "secret\0suffix").is_err());
    }

    #[test]
    fn floating_window_constants_match_collapsed_and_expanded_sizes() {
        assert_eq!(FLOATING_WINDOW_LABEL, "grandpa-floating");
        assert_eq!(FLOATING_COLLAPSED_WIDTH, 48.0);
        assert_eq!(FLOATING_COLLAPSED_HEIGHT, 48.0);
        assert_eq!(FLOATING_EXPANDED_WIDTH, 300.0);
        assert_eq!(FLOATING_EXPANDED_HEIGHT, 340.0);
    }

    #[test]
    fn floating_window_config_keeps_icon_independent_and_chrome_free() {
        let config = floating_window_config();
        assert!(config.visible);
        assert!(config.always_on_top);
        assert!(config.transparent);
        assert!(config.skip_taskbar);
        assert!(!config.decorations);
        assert!(!config.resizable);
        assert!(!config.shadow);
        assert!(config.focusable);
        assert_eq!(config.collapsed_width, 48.0);
        assert_eq!(config.collapsed_height, 48.0);
    }

    #[test]
    fn floating_autostart_hidden_arg_is_detected() {
        assert!(args_request_hidden(["Grandpa.exe", "--hidden"]));
        assert!(args_request_hidden(["Grandpa.exe", "--hidden", "--other"]));
        assert!(!args_request_hidden(["Grandpa.exe"]));
        assert!(!args_request_hidden(["Grandpa.exe", "--not-hidden"]));
    }

    #[test]
    fn floating_window_url_renders_floating_route_immediately() {
        let WebviewUrl::App(path) = floating_window_url() else {
            panic!("floating window must use the app route");
        };
        let path = path.to_string_lossy();
        assert_eq!(path, "index.html?floating=1");
        assert!(!path.contains("win_chromakey"));
    }

    #[cfg(target_os = "windows")]
    #[test]
    fn floating_interactive_style_removes_click_through_without_losing_existing_layering() {
        let original = WS_EX_TRANSPARENT | WS_EX_LAYERED | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE;
        let repaired = interactive_extended_style(original, true);
        assert_eq!(repaired & WS_EX_TRANSPARENT, 0);
        assert_eq!(repaired & WS_EX_NOACTIVATE, 0);
        assert_ne!(repaired & WS_EX_LAYERED, 0);
        assert_ne!(repaired & WS_EX_TOOLWINDOW, 0);
    }

    #[cfg(target_os = "windows")]
    #[test]
    fn floating_interactive_style_repair_is_idempotent() {
        let original = WS_EX_LAYERED | WS_EX_TOOLWINDOW;
        assert_eq!(interactive_extended_style(original, true), original);
        assert_eq!(
            interactive_extended_style(interactive_extended_style(original, true), true),
            original
        );
    }

    #[cfg(target_os = "windows")]
    #[test]
    fn floating_interactive_style_does_not_add_layering() {
        assert_eq!(interactive_extended_style(0, true) & WS_EX_LAYERED, 0);
        assert_eq!(interactive_extended_style(0, false) & WS_EX_LAYERED, 0);
    }

    #[test]
    fn floating_default_position_stays_inside_lower_right_work_area() {
        let bounds = FloatingBounds {
            x: 0.0,
            y: 0.0,
            width: 1920.0,
            height: 1040.0,
        };
        let position = default_floating_position(bounds, 48.0, 48.0);
        assert!(position.x >= bounds.x);
        assert!(position.y >= bounds.y);
        assert!(position.x + 48.0 <= bounds.x + bounds.width);
        assert!(position.y + 48.0 <= bounds.y + bounds.height);
        assert!(position.x > 1800.0);
        assert!(position.y > 900.0);
    }

    #[test]
    fn floating_position_clamp_restores_valid_saved_position() {
        let bounds = FloatingBounds {
            x: 100.0,
            y: 200.0,
            width: 800.0,
            height: 600.0,
        };
        let saved = FloatingPosition { x: 320.0, y: 420.0 };
        let position = clamp_floating_position(Some(saved), bounds, 48.0, 48.0);
        assert_eq!(position.x, saved.x);
        assert_eq!(position.y, saved.y);
    }

    #[test]
    fn floating_position_clamp_keeps_icon_fully_inside_edges() {
        let bounds = FloatingBounds {
            x: 0.0,
            y: 0.0,
            width: 320.0,
            height: 240.0,
        };
        let position = clamp_floating_position(
            Some(FloatingPosition { x: 272.0, y: 192.0 }),
            bounds,
            48.0,
            48.0,
        );
        assert_eq!(position.x, 272.0);
        assert_eq!(position.y, 192.0);
        assert!(position.x + 48.0 <= bounds.x + bounds.width);
        assert!(position.y + 48.0 <= bounds.y + bounds.height);
    }

    #[test]
    fn floating_bounds_for_position_supports_secondary_monitor() {
        let monitors = [
            FloatingBounds {
                x: 0.0,
                y: 0.0,
                width: 1280.0,
                height: 720.0,
            },
            FloatingBounds {
                x: 1280.0,
                y: 0.0,
                width: 1920.0,
                height: 1080.0,
            },
        ];
        let bounds = bounds_for_position(
            &monitors,
            Some(FloatingPosition {
                x: 1800.0,
                y: 400.0,
            }),
        )
        .expect("secondary monitor should be selected");
        assert_eq!(bounds.x, 1280.0);
        assert_eq!(bounds.width, 1920.0);
    }

    #[test]
    fn floating_position_clamp_resets_offscreen_saved_position() {
        let bounds = FloatingBounds {
            x: 0.0,
            y: 0.0,
            width: 1280.0,
            height: 720.0,
        };
        let position = clamp_floating_position(
            Some(FloatingPosition {
                x: -4000.0,
                y: 40.0,
            }),
            bounds,
            48.0,
            48.0,
        );
        assert_eq!(position.x, 1212.0);
        assert_eq!(position.y, 600.0);
    }

    #[test]
    fn floating_position_validation_rejects_malformed_values() {
        assert!(valid_floating_position(FloatingPosition { x: 20.0, y: 40.0 }).is_some());
        assert!(valid_floating_position(FloatingPosition {
            x: f64::NAN,
            y: 40.0
        })
        .is_none());
        assert!(valid_floating_position(FloatingPosition {
            x: 20.0,
            y: f64::INFINITY
        })
        .is_none());
        assert!(valid_floating_position(FloatingPosition {
            x: 200_000.0,
            y: 40.0
        })
        .is_none());
    }

    #[test]
    fn floating_api_base_uses_localhost_loopback() {
        assert_eq!(api_base(), "http://127.0.0.1:8000");
    }

    #[test]
    fn backend_stderr_summary_extracts_missing_dependency_without_traceback() {
        let stderr = "Traceback (most recent call last):\n  File \"x\", line 1\nModuleNotFoundError: No module named 'numpy'\n";
        let summary = summarize_backend_stderr(stderr);
        assert!(summary.contains("Missing Python dependency: numpy"));
        assert!(!summary.contains("Traceback"));
    }

    #[test]
    fn backend_stderr_summary_uses_last_line_for_other_errors() {
        let summary = summarize_backend_stderr("Traceback...\nRuntimeError: port already in use\n");
        assert_eq!(summary, "port already in use");
    }
}
