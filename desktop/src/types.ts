export type Mode = "comments" | "dynamics" | "analysis" | "settings";
export type ThemeMode = "light" | "dark";
export type AnalysisSource = "comments" | "dynamics" | "all";
export type AnalysisStrategy = "sample" | "full";
export type TaskMode = Exclude<Mode, "settings">;
export type SidecarMethod =
  | "session.status"
  | "comments.start"
  | "dynamics.start"
  | "task.stop"
  | "qr.login.start"
  | "qr.login.cancel"
  | "export.csv"
  | "analysis.start"
  | "analysis.latest"
  | "analysis.export";
export type AnalysisChartKey =
  | "sentiment_distribution"
  | "topic_ranking"
  | "time_trend"
  | "level_distribution"
  | "region_map"
  | "word_cloud"
  | "deep_analysis";

export interface UIConfig {
  theme: ThemeMode;
  background_path: string;
  background_opacity: number;
  background_blur: boolean;
  background_mode: "cover" | "contain";
  background_version?: number;
  llm_base_url: string;
  llm_model: string;
  analysis_source: AnalysisSource;
  analysis_strategy: AnalysisStrategy;
  analysis_sample_size: number;
  analysis_batch_size: number;
  analysis_chart_keys: AnalysisChartKey[];
}

export interface Stats {
  total?: number;
  main_comments?: number;
  replies?: number;
  total_likes?: number;
  ip_locations?: number;
  missing_ip_locations?: number;
  ip_location_coverage?: number;
  total_records?: number;
  analyzed_records?: number;
  comments?: number;
  dynamics?: number;
  risk_count?: number;
}

export interface ChartDatum {
  name: string;
  value?: number;
  count?: number;
  likes?: number;
  replies?: number;
  type?: string;
}

export interface DeepAnalysis {
  sociology: string;
  psychology: string;
  philosophy: string;
}

export interface ChartAsset {
  key: AnalysisChartKey;
  filename: string;
  title: string;
  svg?: string;
  data_url?: string;
  file_path?: string;
  mime_type?: string;
}

export interface AnalysisResult {
  summary: string;
  summary_points?: string[];
  overview: Stats;
  sentiment_counts: ChartDatum[];
  topic_counts: ChartDatum[];
  word_counts: ChartDatum[];
  word_cloud_image?: string;
  word_cloud_image_path?: string;
  risk_points: string[];
  insights: string[];
  notable_quotes: string[];
  time_series: ChartDatum[];
  region_counts: ChartDatum[];
  overseas_region_counts: ChartDatum[];
  user_level_counts: ChartDatum[];
  content_type_counts: ChartDatum[];
  engagement_items: ChartDatum[];
  deep_analysis: DeepAnalysis;
  report_markdown: string;
  meta: {
    source: AnalysisSource;
    strategy: AnalysisStrategy;
    model: string;
    total_records: number;
    analyzed_records: number;
    batch_count: number;
    generated_at: string;
    chart_keys: AnalysisChartKey[];
  };
}

export interface SidecarRequest {
  id: string;
  method: SidecarMethod;
  params: Record<string, unknown>;
}

export interface SidecarResponse {
  kind: "response";
  id: string;
  ok: boolean;
  error?: string;
  logged_in?: boolean;
  task_running?: boolean;
  path?: string;
  result?: AnalysisResult;
}

export interface SidecarBroadcastEvent {
  kind: "event";
  event:
    | "ready"
    | "log"
    | "progress"
    | "analysis.progress"
    | "analysis.result"
    | "stats"
    | "finished"
    | "error"
    | "qr"
    | "login.success";
  message?: string;
  mode?: TaskMode;
  status?: "running" | "stopping" | "idle";
  percent?: number;
  image?: string;
  count?: number;
  stats?: Stats;
  result?: AnalysisResult;
  cookies?: Record<string, string>;
}

export type SidecarMessage = SidecarResponse | SidecarBroadcastEvent;
