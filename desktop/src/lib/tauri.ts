import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { open, save } from "@tauri-apps/plugin-dialog";
import {
  DEFAULT_ANALYSIS_CHART_KEYS,
  normalizeAnalysisChartKeys,
  normalizeCustomModules,
} from "./analysisCharts";
import { SidecarClient } from "./sidecarClient";
import type {
  SidecarBroadcastEvent,
  SidecarMessage,
  SidecarMethod,
  UIConfig,
} from "../types";

export const isTauri = () => "__TAURI_INTERNALS__" in window;

const sidecarClient = new SidecarClient(async (request) => {
  if (!isTauri()) {
    throw new Error(
      "浏览器预览无法运行 Python sidecar，请使用 Tauri 桌面窗口启动任务。",
    );
  }
  await invoke("send_sidecar_request", { request });
});

export async function sendSidecar(
  method: SidecarMethod,
  params: Record<string, unknown> = {},
) {
  return sidecarClient.request(method, params);
}

export async function sendSidecarWithTimeout(
  method: SidecarMethod,
  params: Record<string, unknown> = {},
  timeoutMs = 10_000,
) {
  return sidecarClient.request(method, params, timeoutMs);
}

export async function onSidecarEvent(
  callback: (event: SidecarBroadcastEvent) => void,
) {
  if (!isTauri()) return () => undefined;
  const unlisten = await listen<SidecarMessage>("sidecar-event", (event) => {
    sidecarClient.accept(event.payload);
    if (event.payload.kind === "event") callback(event.payload);
  });
  return () => {
    sidecarClient.dispose();
    unlisten();
  };
}

export async function chooseBackground(): Promise<string | null> {
  if (!isTauri()) return null;
  const selected = await open({
    multiple: false,
    filters: [
      { name: "Images", extensions: ["png", "jpg", "jpeg", "webp", "bmp"] },
    ],
  });
  if (typeof selected !== "string") return null;
  return selected;
}

export async function chooseCsvPath(
  defaultName: string,
): Promise<string | null> {
  return chooseSavePath(defaultName, [{ name: "CSV", extensions: ["csv"] }]);
}

export async function chooseSavePath(
  defaultName: string,
  filters: Array<{ name: string; extensions: string[] }>,
): Promise<string | null> {
  if (!isTauri()) return null;
  const selected = await save({
    defaultPath: defaultName,
    filters,
  });
  return selected || null;
}

const fallbackConfigKey = "bilibilicrawler-ui-config";

export async function readConfig(): Promise<UIConfig> {
  const defaults: UIConfig = {
    theme: "light",
    background_path: "",
    background_opacity: 0.22,
    background_blur: true,
    background_mode: "cover",
    background_version: 0,
    llm_base_url: "https://api.openai.com/v1",
    llm_model: "",
    analysis_source: "all",
    analysis_strategy: "sample",
    analysis_sample_size: 300,
    analysis_batch_size: 80,
    analysis_chart_keys: [...DEFAULT_ANALYSIS_CHART_KEYS],
    analysis_custom_modules: [],
  };
  if (isTauri()) {
    const loaded = {
      ...defaults,
      ...(await invoke<UIConfig>("read_ui_config")),
    };
    const customModules = normalizeCustomModules(loaded.analysis_custom_modules);
    return {
      ...loaded,
      analysis_custom_modules: customModules,
      analysis_chart_keys: normalizeAnalysisChartKeys(
        loaded.analysis_chart_keys,
        undefined,
        customModules.map((item): string => item.id),
      ),
    };
  }
  const raw = localStorage.getItem(fallbackConfigKey);
  if (!raw) return defaults;
  try {
    const loaded = { ...defaults, ...JSON.parse(raw) };
    const customModules = normalizeCustomModules(loaded.analysis_custom_modules);
    return {
      ...loaded,
      analysis_custom_modules: customModules,
      analysis_chart_keys: normalizeAnalysisChartKeys(
        loaded.analysis_chart_keys,
        undefined,
        customModules.map((item): string => item.id),
      ),
    };
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

export async function readLlmApiKey(): Promise<string> {
  if (!isTauri()) {
    return localStorage.getItem("bilibilicrawler-llm-api-key") ?? "";
  }
  return invoke<string>("read_llm_api_key");
}

export async function writeLlmApiKey(apiKey: string): Promise<void> {
  if (!isTauri()) {
    localStorage.setItem("bilibilicrawler-llm-api-key", apiKey);
    return;
  }
  await invoke("write_llm_api_key", { apiKey });
}
