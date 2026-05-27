import { Download, Play, Square } from "lucide-react";
import type { Mode } from "../types";

interface Props {
  mode: Mode;
  running: boolean;
  stopping: boolean;
  canExport: boolean;
  onStart: () => void;
  onStop: () => void;
  onExport: () => void;
}

export function BottomActionBar({ mode, running, stopping, canExport, onStart, onStop, onExport }: Props) {
  const disabled = mode === "settings";
  return (
    <footer className="action-bar">
      <div>
        <strong>{mode === "comments" ? "评论任务" : mode === "dynamics" ? "动态任务" : "界面设置"}</strong>
        <span>{disabled ? "设置页不运行爬取任务" : "CSV 会通过 Python sidecar 写入本地文件"}</span>
      </div>
      {!disabled && (
        <div className="action-buttons">
          <button className="ghost-button" disabled={!canExport || running} onClick={onExport}>
            <Download size={18} />
            导出 CSV
          </button>
          <button className="ghost-button" disabled={!running || stopping} onClick={onStop}>
            <Square size={18} />
            {stopping ? "停止中" : "停止"}
          </button>
          <button className="primary-button" disabled={running} onClick={onStart}>
            <Play size={20} />
            开始任务
          </button>
        </div>
      )}
    </footer>
  );
}
