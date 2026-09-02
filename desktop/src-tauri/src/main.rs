#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use base64::Engine;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::fs;
use std::io::{BufRead, BufReader, Write};
use std::path::{Path, PathBuf};
use std::process::{Child, ChildStdin, Command, Stdio};
use std::sync::Mutex;
use std::thread;
use tauri::{AppHandle, Emitter, Manager, State};

#[cfg(windows)]
use std::os::windows::process::CommandExt;

#[cfg(windows)]
const CREATE_NO_WINDOW: u32 = 0x08000000;
#[cfg(windows)]
const DETACHED_PROCESS: u32 = 0x00000008;

struct SidecarState {
    child: Mutex<Option<Child>>,
    stdin: Mutex<Option<ChildStdin>>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct UiConfig {
    theme: String,
    background_path: String,
    background_opacity: f64,
    background_blur: bool,
    background_mode: String,
    background_version: Option<u64>,
    #[serde(default)]
    llm_base_url: String,
    #[serde(default)]
    llm_model: String,
    #[serde(default)]
    analysis_source: String,
    #[serde(default)]
    analysis_strategy: String,
    #[serde(default)]
    analysis_sample_size: u64,
    #[serde(default)]
    analysis_batch_size: u64,
    #[serde(default)]
    analysis_chart_keys: Vec<String>,
    #[serde(default)]
    analysis_custom_modules: Vec<CustomModule>,
}

/// A user-authored analysis angle. The id indexes results and historical
/// reports, so it is generated once by the UI and never rewritten here.
///
/// There is deliberately no `enabled` flag: `analysis_chart_keys` is the one
/// selection list, and a second source of truth could contradict it.
#[derive(Debug, Clone, Serialize, Deserialize)]
struct CustomModule {
    #[serde(default)]
    id: String,
    #[serde(default)]
    title: String,
    #[serde(default)]
    prompt: String,
}

impl SidecarState {
    fn new() -> Self {
        Self {
            child: Mutex::new(None),
            stdin: Mutex::new(None),
        }
    }
}

fn default_ui_config() -> UiConfig {
    UiConfig {
        theme: "light".to_string(),
        background_path: String::new(),
        background_opacity: 0.22,
        background_blur: true,
        background_mode: "cover".to_string(),
        background_version: None,
        llm_base_url: "https://api.openai.com/v1".to_string(),
        llm_model: String::new(),
        analysis_source: "all".to_string(),
        analysis_strategy: "sample".to_string(),
        analysis_sample_size: 300,
        analysis_batch_size: 80,
        analysis_chart_keys: default_analysis_chart_keys(),
        analysis_custom_modules: Vec::new(),
    }
}

#[tauri::command]
fn read_ui_config() -> Result<UiConfig, String> {
    read_ui_config_from_disk()
}

#[tauri::command]
fn write_ui_config(config: UiConfig) -> Result<UiConfig, String> {
    let config = normalize_ui_config(config);
    save_ui_config(&config)?;
    Ok(config)
}

#[tauri::command]
fn set_background_from_path(source: String) -> Result<UiConfig, String> {
    let source_path = PathBuf::from(source);
    if !source_path.is_file() {
        return Err("选择的背景图片不存在".to_string());
    }

    let ext = source_path
        .extension()
        .and_then(|value| value.to_str())
        .map(|value| value.to_ascii_lowercase())
        .ok_or_else(|| "背景图片缺少文件扩展名".to_string())?;
    if !matches!(ext.as_str(), "png" | "jpg" | "jpeg" | "webp" | "bmp") {
        return Err("只支持 png、jpg、jpeg、webp、bmp 背景图片".to_string());
    }

    let background_dir = user_data_dir()?.join("backgrounds");
    fs::create_dir_all(&background_dir).map_err(|err| err.to_string())?;
    let target = background_dir.join(format!("background.{ext}"));
    if source_path != target {
        fs::copy(&source_path, &target).map_err(|err| err.to_string())?;
    }

    let mut config = read_ui_config_from_disk()?;
    config.background_path = target.to_string_lossy().to_string();
    config.background_mode = "cover".to_string();
    config.background_version = Some(background_version(&target)?);
    let config = normalize_ui_config(config);
    save_ui_config(&config)?;
    Ok(config)
}

#[tauri::command]
fn clear_background() -> Result<UiConfig, String> {
    let mut config = read_ui_config_from_disk()?;
    config.background_path.clear();
    config.background_version = None;
    let config = normalize_ui_config(config);
    save_ui_config(&config)?;
    Ok(config)
}

#[tauri::command]
fn read_background_data_url(path: String) -> Result<String, String> {
    let path = PathBuf::from(path);
    if !path.is_file() {
        return Err("背景图片文件不存在".to_string());
    }
    let mime = background_mime(&path)?;
    let bytes = fs::read(&path).map_err(|err| format!("读取背景图片失败: {err}"))?;
    let encoded = base64::engine::general_purpose::STANDARD.encode(bytes);
    Ok(format!("data:{mime};base64,{encoded}"))
}

#[tauri::command]
fn send_sidecar_request(
    app: AppHandle,
    state: State<SidecarState>,
    request: Value,
) -> Result<(), String> {
    ensure_sidecar(&app, &state)?;
    let mut stdin_guard = state.stdin.lock().map_err(|_| "sidecar stdin lock failed")?;
    let stdin = stdin_guard
        .as_mut()
        .ok_or_else(|| "sidecar stdin is unavailable".to_string())?;
    let line = serde_json::to_string(&request).map_err(|err| err.to_string())?;
    stdin
        .write_all(line.as_bytes())
        .and_then(|_| stdin.write_all(b"\n"))
        .and_then(|_| stdin.flush())
        .map_err(|err| err.to_string())
}

fn ensure_sidecar(app: &AppHandle, state: &State<SidecarState>) -> Result<(), String> {
    // Check if child process is still alive (not just Some)
    let alive = state
        .child
        .lock()
        .map_err(|_| "sidecar child lock failed")?
        .as_mut()
        .map(|child| child.try_wait().map(|status| status.is_none()).unwrap_or(false))
        .unwrap_or(false);

    if alive {
        return Ok(());
    }

    // Process is dead or never started — clean up stale handles
    if let Ok(mut guard) = state.child.lock() {
        *guard = None;
    }
    if let Ok(mut guard) = state.stdin.lock() {
        *guard = None;
    }

    let sidecar = resolve_sidecar_path(app)?;
    let mut command = if sidecar.extension().and_then(|ext| ext.to_str()) == Some("py") {
        let mut cmd = Command::new("python");
        cmd.arg(sidecar);
        cmd
    } else {
        Command::new(sidecar)
    };
    command.stdin(Stdio::piped()).stdout(Stdio::piped()).stderr(Stdio::piped());
    #[cfg(windows)]
    command.creation_flags(CREATE_NO_WINDOW | DETACHED_PROCESS);
    let mut child = command.spawn().map_err(|err| format!("failed to start sidecar: {err}"))?;
    let stdout = child.stdout.take().ok_or("sidecar stdout unavailable")?;
    let stderr = child.stderr.take().ok_or("sidecar stderr unavailable")?;
    let stdin = child.stdin.take().ok_or("sidecar stdin unavailable")?;

    let out_app = app.clone();
    thread::spawn(move || {
        for line in BufReader::new(stdout).lines().flatten() {
            match serde_json::from_str::<Value>(&line) {
                Ok(value) => {
                    let _ = out_app.emit("sidecar-event", value);
                }
                Err(_) => {
                    let _ = out_app.emit(
                        "sidecar-event",
                        serde_json::json!({"kind":"event","event":"log","message":line}),
                    );
                }
            }
        }
    });

    let err_app = app.clone();
    thread::spawn(move || {
        for line in BufReader::new(stderr).lines().flatten() {
            let _ = err_app.emit(
                "sidecar-event",
                serde_json::json!({"kind":"event","event":"log","message":line}),
            );
        }
    });

    *state.stdin.lock().map_err(|_| "sidecar stdin lock failed")? = Some(stdin);
    *state.child.lock().map_err(|_| "sidecar child lock failed")? = Some(child);
    Ok(())
}

fn resolve_sidecar_path(app: &AppHandle) -> Result<PathBuf, String> {
    let mut candidates = Vec::new();
    let manifest_dir = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    let source_sidecar = manifest_dir
        .parent()
        .and_then(|desktop| desktop.parent())
        .map(|repo_root| repo_root.join("backend").join("sidecar.py"));

    #[cfg(debug_assertions)]
    if let Some(path) = source_sidecar.as_ref() {
        candidates.push(path.clone());
    }

    if let Ok(resource_dir) = app.path().resource_dir() {
        candidates.push(resource_dir.join("resources").join("backend").join("sidecar").join("sidecar.exe"));
        candidates.push(resource_dir.join("backend").join("sidecar").join("sidecar.exe"));
        candidates.push(resource_dir.join("backend").join("sidecar.exe"));
    }

    #[cfg(not(debug_assertions))]
    if let Some(path) = source_sidecar.as_ref() {
        candidates.push(path.clone());
    }

    candidates
        .into_iter()
        .find(|path| path.exists())
        .ok_or_else(|| "sidecar executable or backend/sidecar.py was not found".to_string())
}

fn read_ui_config_from_disk() -> Result<UiConfig, String> {
    let path = ui_config_path()?;
    if !path.exists() {
        return Ok(default_ui_config());
    }

    let raw = fs::read_to_string(&path).map_err(|err| err.to_string())?;
    let config: UiConfig = serde_json::from_str(&raw).map_err(|err| err.to_string())?;
    Ok(normalize_ui_config(config))
}

fn save_ui_config(config: &UiConfig) -> Result<(), String> {
    let path = ui_config_path()?;
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent).map_err(|err| err.to_string())?;
    }
    let raw = serde_json::to_string_pretty(config).map_err(|err| err.to_string())?;
    fs::write(path, raw).map_err(|err| err.to_string())
}

fn normalize_ui_config(mut config: UiConfig) -> UiConfig {
    if config.theme != "dark" {
        config.theme = "light".to_string();
    }
    if config.background_mode != "contain" {
        config.background_mode = "cover".to_string();
    }
    config.background_opacity = config.background_opacity.clamp(0.0, 1.0);
    if !config.background_path.is_empty() && !Path::new(&config.background_path).exists() {
        config.background_path.clear();
        config.background_version = None;
    }
    config.llm_base_url = config.llm_base_url.trim().trim_end_matches('/').to_string();
    if config.llm_base_url.is_empty() {
        config.llm_base_url = "https://api.openai.com/v1".to_string();
    }
    config.llm_model = config.llm_model.trim().to_string();
    if !matches!(config.analysis_source.as_str(), "comments" | "dynamics" | "all") {
        config.analysis_source = "all".to_string();
    }
    if !matches!(config.analysis_strategy.as_str(), "sample" | "full") {
        config.analysis_strategy = "sample".to_string();
    }
    if config.analysis_sample_size == 0 {
        config.analysis_sample_size = 300;
    }
    if config.analysis_batch_size == 0 {
        config.analysis_batch_size = 80;
    }
    config.analysis_sample_size = config.analysis_sample_size.clamp(20, 2000);
    config.analysis_batch_size = config.analysis_batch_size.clamp(20, 200);
    config.analysis_custom_modules = normalize_custom_modules(config.analysis_custom_modules);
    let custom_ids: Vec<String> = config
        .analysis_custom_modules
        .iter()
        .map(|item| item.id.clone())
        .collect();
    config.analysis_chart_keys = normalize_analysis_chart_keys(config.analysis_chart_keys, &custom_ids);
    config
}

const CUSTOM_MODULE_TITLE_LIMIT: usize = 24;
const CUSTOM_MODULE_PROMPT_LIMIT: usize = 500;
const CUSTOM_MODULE_SAVED_LIMIT: usize = 8;

fn is_custom_module_id(value: &str) -> bool {
    let rest = match value.strip_prefix("custom_") {
        Some(rest) => rest,
        None => return false,
    };
    rest.len() == 6 && rest.chars().all(|ch| ch.is_ascii_digit() || ('a'..='f').contains(&ch))
}

fn truncate_chars(value: &str, limit: usize) -> String {
    value.chars().take(limit).collect()
}

/// Drop entries that could not round-trip: a malformed id would orphan its
/// results, and an empty title or prompt has nothing to run.
fn normalize_custom_modules(modules: Vec<CustomModule>) -> Vec<CustomModule> {
    let mut normalized: Vec<CustomModule> = Vec::new();
    for module in modules {
        let id = module.id.trim().to_ascii_lowercase();
        if !is_custom_module_id(&id) || normalized.iter().any(|item| item.id == id) {
            continue;
        }
        let title = truncate_chars(module.title.trim(), CUSTOM_MODULE_TITLE_LIMIT);
        let prompt = truncate_chars(module.prompt.trim(), CUSTOM_MODULE_PROMPT_LIMIT);
        if title.is_empty() || prompt.is_empty() {
            continue;
        }
        normalized.push(CustomModule { id, title, prompt });
        if normalized.len() >= CUSTOM_MODULE_SAVED_LIMIT {
            break;
        }
    }
    normalized
}

fn default_analysis_chart_keys() -> Vec<String> {
    [
        "sentiment_distribution",
        "topic_ranking",
        "time_trend",
        "level_distribution",
        "region_map",
        "word_cloud",
        "deep_analysis",
    ]
    .iter()
    .map(|value| value.to_string())
    .collect()
}

fn normalize_analysis_chart_keys(keys: Vec<String>, custom_ids: &[String]) -> Vec<String> {
    let defaults = default_analysis_chart_keys();
    let mut normalized = Vec::new();
    for key in keys {
        // Custom ids pass only when the module still exists: a deleted module
        // must not keep a selection alive that nothing can render.
        let allowed = defaults.iter().any(|item| item == &key)
            || custom_ids.iter().any(|item| item == &key);
        if allowed && !normalized.iter().any(|item| item == &key) {
            normalized.push(key);
        }
    }
    if normalized.is_empty() {
        defaults
    } else {
        normalized
    }
}

#[derive(Debug, Serialize, Deserialize)]
struct Credentials {
    api_key: String,
}

fn credentials_path() -> Result<PathBuf, String> {
    Ok(user_data_dir()?.join("config").join("credentials.json"))
}

#[tauri::command]
fn read_llm_api_key() -> Result<String, String> {
    let path = credentials_path()?;
    if !path.exists() {
        return Ok(String::new());
    }
    let raw = fs::read_to_string(&path).map_err(|err| err.to_string())?;
    let creds: Credentials = serde_json::from_str(&raw).map_err(|err| err.to_string())?;
    Ok(creds.api_key)
}

#[tauri::command]
fn write_llm_api_key(api_key: String) -> Result<(), String> {
    let path = credentials_path()?;
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent).map_err(|err| err.to_string())?;
    }
    let creds = Credentials {
        api_key: api_key.trim().to_string(),
    };
    let raw = serde_json::to_string(&creds).map_err(|err| err.to_string())?;
    fs::write(&path, raw).map_err(|err| err.to_string())?;
    hide_file(&path);
    Ok(())
}

#[cfg(windows)]
fn hide_file(path: &Path) {
    let _ = std::process::Command::new("attrib")
        .arg("+h")
        .arg(path)
        .output();
}

#[cfg(not(windows))]
fn hide_file(_path: &Path) {}

fn background_version(path: &Path) -> Result<u64, String> {
    let metadata = fs::metadata(path).map_err(|err| err.to_string())?;
    let modified = metadata.modified().map_err(|err| err.to_string())?;
    let millis = modified
        .duration_since(std::time::UNIX_EPOCH)
        .map_err(|err| err.to_string())?
        .as_millis();
    Ok(millis.min(u128::from(u64::MAX)) as u64)
}

fn background_mime(path: &Path) -> Result<&'static str, String> {
    let ext = path
        .extension()
        .and_then(|value| value.to_str())
        .map(|value| value.to_ascii_lowercase())
        .ok_or_else(|| "背景图片缺少文件扩展名".to_string())?;
    match ext.as_str() {
        "png" => Ok("image/png"),
        "jpg" | "jpeg" => Ok("image/jpeg"),
        "webp" => Ok("image/webp"),
        "bmp" => Ok("image/bmp"),
        _ => Err("只支持 png、jpg、jpeg、webp、bmp 背景图片".to_string()),
    }
}

fn ui_config_path() -> Result<PathBuf, String> {
    Ok(user_data_dir()?.join("config").join("ui.json"))
}

fn user_data_dir() -> Result<PathBuf, String> {
    if cfg!(debug_assertions) {
        let manifest_dir = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
        if let Some(repo_root) = manifest_dir.parent().and_then(|desktop| desktop.parent()) {
            return Ok(repo_root.join(".install-test").join("user-data"));
        }
    }

    let exe = std::env::current_exe().map_err(|err| err.to_string())?;
    let install_dir = exe
        .parent()
        .ok_or_else(|| "无法确定安装目录".to_string())?;
    Ok(install_dir.join("user-data"))
}

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_fs::init())
        .plugin(tauri_plugin_log::Builder::new().build())
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_process::init())
        .manage(SidecarState::new())
        .invoke_handler(tauri::generate_handler![
            send_sidecar_request,
            read_ui_config,
            write_ui_config,
            set_background_from_path,
            clear_background,
            read_background_data_url,
            read_llm_api_key,
            write_llm_api_key
        ])
        .on_window_event(|window, event| {
            if matches!(event, tauri::WindowEvent::CloseRequested { .. }) {
                if let Some(state) = window.try_state::<SidecarState>() {
                    if let Ok(mut child_guard) = state.child.lock() {
                        if let Some(child) = child_guard.as_mut() {
                            let _ = child.kill();
                        }
                    }
                }
            }
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}

#[cfg(test)]
mod tests {
    use super::*;

    fn module(id: &str, title: &str, prompt: &str) -> CustomModule {
        CustomModule {
            id: id.to_string(),
            title: title.to_string(),
            prompt: prompt.to_string(),
        }
    }

    #[test]
    fn custom_ids_survive_the_whitelist_round_trip() {
        let ids = vec!["custom_a1b2c3".to_string()];
        let keys = vec!["topic_ranking".to_string(), "custom_a1b2c3".to_string()];
        assert_eq!(normalize_analysis_chart_keys(keys.clone(), &ids), keys);
    }

    #[test]
    fn a_custom_id_without_its_module_is_dropped() {
        // Nothing can render a selection whose module is gone, so it must not
        // survive in the saved configuration.
        let keys = vec!["topic_ranking".to_string(), "custom_a1b2c3".to_string()];
        assert_eq!(
            normalize_analysis_chart_keys(keys, &[]),
            vec!["topic_ranking".to_string()]
        );
    }

    #[test]
    fn an_empty_selection_falls_back_to_built_ins_only() {
        let ids = vec!["custom_a1b2c3".to_string()];
        assert_eq!(
            normalize_analysis_chart_keys(Vec::new(), &ids),
            default_analysis_chart_keys()
        );
    }

    #[test]
    fn malformed_modules_are_dropped_rather_than_repaired() {
        let modules = vec![
            module("custom_A1B2C3", " 标题 ", " 提示 "),
            module("custom_zzzzzz", "标题", "提示"),
            module("custom_a1b2c", "标题", "提示"),
            module("deep_analysis", "标题", "提示"),
            module("custom_b2c3d4", "", "提示"),
            module("custom_c3d4e5", "标题", "  "),
        ];
        let normalized = normalize_custom_modules(modules);
        let ids: Vec<&str> = normalized.iter().map(|item| item.id.as_str()).collect();
        assert_eq!(ids, vec!["custom_a1b2c3"]);
        assert_eq!(normalized[0].title, "标题");
        assert_eq!(normalized[0].prompt, "提示");
    }

    #[test]
    fn an_unknown_enabled_field_is_ignored_rather_than_rejected() {
        // Configurations written before the flag was dropped must still load.
        let module: CustomModule = serde_json::from_str(
            r#"{"id":"custom_a1b2c3","title":"标题","prompt":"提示","enabled":false}"#,
        )
        .expect("legacy entry should deserialize");
        assert_eq!(normalize_custom_modules(vec![module]).len(), 1);
    }

    #[test]
    fn fields_are_truncated_by_characters_not_bytes() {
        let long_title = "标".repeat(60);
        let long_prompt = "提".repeat(900);
        let normalized = normalize_custom_modules(vec![module("custom_a1b2c3", &long_title, &long_prompt)]);
        assert_eq!(normalized[0].title.chars().count(), CUSTOM_MODULE_TITLE_LIMIT);
        assert_eq!(normalized[0].prompt.chars().count(), CUSTOM_MODULE_PROMPT_LIMIT);
    }

    #[test]
    fn duplicate_ids_keep_only_the_first_and_the_count_is_capped() {
        let mut modules = vec![
            module("custom_a1b2c3", "先来的", "提示"),
            module("custom_a1b2c3", "后来的", "提示"),
        ];
        for index in 0..10 {
            modules.push(module(&format!("custom_00000{index}"), "标题", "提示"));
        }
        let normalized = normalize_custom_modules(modules);
        assert_eq!(normalized[0].title, "先来的");
        assert_eq!(normalized.len(), CUSTOM_MODULE_SAVED_LIMIT);
    }
}
