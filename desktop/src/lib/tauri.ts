import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { open, save } from "@tauri-apps/plugin-dialog";
import type { SidecarEvent, UIConfig } from "../types";

export const isTauri = () => "__TAURI_INTERNALS__" in window;

export async function sendSidecar(method: string, params: Record<string, unknown> = {}) {
  const request = {
    id: crypto.randomUUID(),
    method,
    params
  };
  if (!isTauri()) {
    console.info("sidecar request skipped in browser preview", request);
    return request.id;
  }
  await invoke("send_sidecar_request", { request });
  return request.id;
}

export async function onSidecarEvent(callback: (event: SidecarEvent) => void) {
  if (!isTauri()) return () => undefined;
  return listen<SidecarEvent>("sidecar-event", (event) => callback(event.payload));
}

export async function chooseBackground(): Promise<string | null> {
  if (!isTauri()) return null;
  const selected = await open({
    multiple: false,
    filters: [{ name: "Images", extensions: ["png", "jpg", "jpeg", "webp", "bmp"] }]
  });
  if (typeof selected !== "string") return null;
  return selected;
}

export async function chooseCsvPath(defaultName: string): Promise<string | null> {
  if (!isTauri()) return null;
  const selected = await save({
    defaultPath: defaultName,
    filters: [{ name: "CSV", extensions: ["csv"] }]
  });
  return selected || null;
}

const fallbackConfigKey = "bilibili-crawler-ui-config";

export async function readConfig(): Promise<UIConfig> {
  const defaults: UIConfig = {
    theme: "light",
    background_path: "",
    background_opacity: 0.22,
    background_blur: true,
    background_mode: "cover",
    background_version: 0
  };
  if (isTauri()) {
    return { ...defaults, ...(await invoke<UIConfig>("read_ui_config")) };
  }
  const raw = localStorage.getItem(fallbackConfigKey);
  if (!raw) return defaults;
  try {
    return { ...defaults, ...JSON.parse(raw) };
  } catch {
    return defaults;
  }
}

export async function writeConfig(config: UIConfig): Promise<UIConfig> {
  if (isTauri()) {
    return invoke<UIConfig>("write_ui_config", { config });
  }
  localStorage.setItem(fallbackConfigKey, JSON.stringify(config));
  return config;
}

export async function setBackgroundFromPath(path: string): Promise<UIConfig> {
  if (!isTauri()) throw new Error("背景设置只在桌面应用中可用");
  return invoke<UIConfig>("set_background_from_path", { source: path });
}

export async function clearBackground(): Promise<UIConfig> {
  if (!isTauri()) {
    localStorage.removeItem(fallbackConfigKey);
    return readConfig();
  }
  return invoke<UIConfig>("clear_background");
}

export async function readBackgroundDataUrl(path: string): Promise<string> {
  if (!isTauri()) return path;
  return invoke<string>("read_background_data_url", { path });
}
