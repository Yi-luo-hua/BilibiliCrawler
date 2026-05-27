export type Mode = "comments" | "dynamics" | "settings";
export type ThemeMode = "light" | "dark";

export interface UIConfig {
  theme: ThemeMode;
  background_path: string;
  background_opacity: number;
  background_blur: boolean;
  background_mode: "cover" | "contain";
  background_version?: number;
}

export interface Stats {
  total?: number;
  main_comments?: number;
  replies?: number;
  total_likes?: number;
}

export interface SidecarEvent {
  kind: "event" | "response";
  event?: string;
  ok?: boolean;
  id?: string;
  message?: string;
  mode?: Mode;
  status?: string;
  percent?: number;
  image?: string;
  count?: number;
  stats?: Stats;
  error?: string;
  cookies?: Record<string, string>;
}
