import type { TaskMode } from "../types.ts";

export type TaskPhase =
  | "idle"
  | "starting"
  | "running"
  | "stopping"
  | "cancelled"
  | "succeeded"
  | "failed";

export interface TaskState {
  phase: TaskPhase;
  mode: TaskMode | null;
  progressPercent: number;
  progressStatus: string;
  summary: string;
}

export type TaskAction =
  | { type: "reset"; mode?: TaskMode }
  | { type: "session.running"; mode?: TaskMode }
  | { type: "start.requested"; mode: TaskMode }
  | { type: "start.failed"; mode: TaskMode }
  | { type: "stop.requested" }
  | {
      type: "progress";
      status: "running" | "stopping" | "idle";
      mode?: TaskMode;
      percent?: number;
    }
  | { type: "analysis.progress"; message?: string; percent?: number }
  | { type: "finished"; mode: TaskMode; count: number }
  | { type: "cancelled"; mode?: TaskMode }
  | { type: "failed"; mode?: TaskMode };

export const initialTaskState: TaskState = {
  phase: "idle",
  mode: null,
  progressPercent: 0,
  progressStatus: "爬取进度",
  summary: "就绪",
};

export function taskReducer(state: TaskState, action: TaskAction): TaskState {
  switch (action.type) {
    case "reset":
      return {
        ...initialTaskState,
        mode: action.mode ?? state.mode,
        progressStatus: action.mode === "analysis" ? "分析进度" : "爬取进度",
      };
    case "session.running":
      return {
        ...state,
        phase: "running",
        mode: action.mode ?? state.mode,
        summary: "任务运行中",
      };
    case "start.requested":
      return {
        phase: "starting",
        mode: action.mode,
        progressPercent: 0,
        progressStatus: action.mode === "analysis" ? "分析进度" : "爬取进度",
        summary: "任务启动中",
      };
    case "start.failed":
      return {
        ...state,
        phase: "failed",
        mode: action.mode,
        progressPercent: 0,
        progressStatus: action.mode === "analysis" ? "分析进度" : "爬取进度",
        summary: "就绪",
      };
    case "stop.requested":
      return {
        ...state,
        phase: "stopping",
        progressStatus: "正在停止",
        summary: `正在停止${state.mode === "analysis" ? "分析" : "爬取"}`,
      };
    case "progress": {
      const nextMode = action.mode ?? state.mode;
      const nextPercent = clampPercent(action.percent, state.progressPercent);
      if (action.status === "running") {
        return {
          ...state,
          phase: "running",
          mode: nextMode,
          progressPercent: nextPercent,
          progressStatus: nextMode === "analysis" ? "分析进度" : "爬取进度",
          summary: "任务运行中",
        };
      }
      if (action.status === "stopping") {
        return {
          ...state,
          phase: "stopping",
          mode: nextMode,
          progressPercent: nextPercent,
          progressStatus:
            nextMode === "analysis" ? "正在停止分析" : "正在停止爬取",
        };
      }
      if (
        state.phase === "succeeded" ||
        state.phase === "cancelled" ||
        state.phase === "failed"
      ) {
        return state;
      }
      return {
        ...state,
        phase: "idle",
        mode: nextMode,
        progressPercent: nextPercent,
      };
    }
    case "analysis.progress":
      return {
        ...state,
        phase: state.phase === "starting" ? "running" : state.phase,
        progressPercent: clampPercent(action.percent, state.progressPercent),
        progressStatus: action.message || state.progressStatus,
      };
    case "finished":
      return {
        ...state,
        phase: "succeeded",
        mode: action.mode,
        progressPercent: 100,
        progressStatus: action.mode === "analysis" ? "分析完成" : "爬取完成",
        summary:
          action.mode === "analysis"
            ? `分析完成：${action.count} 条`
            : `完成：${action.count} 条`,
      };
    case "cancelled": {
      const nextMode = action.mode ?? state.mode;
      return {
        ...state,
        phase: "cancelled",
        mode: nextMode,
        progressStatus:
          nextMode === "analysis" ? "分析已停止" : "爬取已停止",
        summary: nextMode === "analysis" ? "分析已停止" : "爬取已停止",
      };
    }
    case "failed":
      return {
        ...state,
        phase: "failed",
        mode: action.mode ?? state.mode,
        progressStatus: action.mode === "analysis" ? "分析进度" : "爬取进度",
        summary: action.mode === "analysis" ? "分析失败" : "任务失败",
      };
  }
}

function clampPercent(value: number | undefined, fallback: number): number {
  if (typeof value !== "number" || Number.isNaN(value)) return fallback;
  return Math.max(0, Math.min(100, Math.round(value)));
}
