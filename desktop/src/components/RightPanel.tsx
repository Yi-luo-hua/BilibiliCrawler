import { useEffect, useRef } from "react";
import { LucideIcon, Terminal, UserRoundCheck } from "lucide-react";

interface Props {
  summary: string;
  running: boolean;
  loggedIn: boolean;
  logs: string[];
  statCards: Array<{ icon: LucideIcon; label: string; value: string | number }>;
  progressPercent: number;
  progressStatus: string;
}

export function RightPanel({ summary, running, loggedIn, logs, statCards, progressPercent, progressStatus }: Props) {
  const logRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    logRef.current?.scrollTo({ top: logRef.current.scrollHeight, behavior: "smooth" });
  }, [logs]);

  return (
    <aside className="right-panel">
      <section className="status-card">
        <div className="status-row">
          <span className={running ? "pulse-dot" : "idle-dot"} />
          <div>
            <strong>{summary}</strong>
            <p>{running ? "后台 sidecar 正在执行任务" : "可以启动新的爬取任务"}</p>
          </div>
        </div>
        <div className="login-state">
          <UserRoundCheck size={18} />
          {loggedIn ? "登录态可用" : "未登录"}
        </div>
      </section>
      <section className="stats-grid">
        {statCards.map((item) => {
          const Icon = item.icon;
          return (
            <div className="stat-card" key={item.label}>
              <Icon size={18} />
              <strong>{item.value}</strong>
              <span>{item.label}</span>
            </div>
          );
        })}
      </section>
      <section className="log-panel">
        <div className="log-title">
          <Terminal size={18} />
          <span>运行日志</span>
        </div>
        <div className="log-scroll" ref={logRef}>
          {logs.length ? (
            logs.map((log, index) => <p key={`${index}-${log}`}>{log}</p>)
          ) : (
            <p className="empty-log">暂无运行日志</p>
          )}
        </div>
        <div className="progress-block">
          <div className="progress-meta">
            <span>{progressStatus}</span>
            <strong>{progressPercent}%</strong>
          </div>
          <div className="progress-track" aria-label={`爬取进度 ${progressPercent}%`}>
            <span style={{ width: `${progressPercent}%` }} />
          </div>
        </div>
      </section>
    </aside>
  );
}
