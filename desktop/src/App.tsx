import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import {
  BarChart3,
  Clock3,
  Loader2,
  MessageCircle,
  Radio,
  UserRoundCheck
} from "lucide-react";
import logo from "./assets/app_logo.png";
import { BackgroundLayer } from "./components/BackgroundLayer";
import { BottomActionBar } from "./components/BottomActionBar";
import { RightPanel } from "./components/RightPanel";
import { SideNav } from "./components/SideNav";
import { TaskWorkspace } from "./components/TaskWorkspace";
import { TitleBar } from "./components/TitleBar";
import { chooseCsvPath, onSidecarEvent, readBackgroundDataUrl, readConfig, sendSidecar, writeConfig } from "./lib/tauri";
import type { Mode, SidecarEvent, Stats, UIConfig } from "./types";

const timePresetSeconds: Record<string, number> = {
  不限: 0,
  最近1小时: 3600,
  最近3小时: 10800,
  最近6小时: 21600,
  最近12小时: 43200,
  最近1天: 86400,
  最近3天: 259200,
  最近7天: 604800
};

export interface FormsState {
  commentTarget: string;
  includeReplies: boolean;
  commentPages: string;
  sortMode: "time" | "hot";
  dynamicTarget: string;
  keyword: string;
  timeRange: string;
  dynamicPages: string;
}

const initialForms: FormsState = {
  commentTarget: "",
  includeReplies: true,
  commentPages: "100",
  sortMode: "time",
  dynamicTarget: "",
  keyword: "",
  timeRange: "不限",
  dynamicPages: "20"
};

export function App() {
  const [mode, setMode] = useState<Mode>("comments");
  const [forms, setForms] = useState<FormsState>(initialForms);
  const [config, setConfig] = useState<UIConfig>({
    theme: "light",
    background_path: "",
    background_opacity: 0.22,
    background_blur: true,
    background_mode: "cover",
    background_version: 0
  });
  const [logs, setLogs] = useState<string[]>(["桌面壳已就绪，等待任务。"]);
  const [running, setRunning] = useState(false);
  const [loggedIn, setLoggedIn] = useState(false);
  const [summary, setSummary] = useState("就绪");
  const [stats, setStats] = useState<Stats>({ total: 0, main_comments: 0, replies: 0, total_likes: 0 });
  const [progressPercent, setProgressPercent] = useState(0);
  const [progressStatus, setProgressStatus] = useState("爬取进度");
  const [backgroundDataUrl, setBackgroundDataUrl] = useState("");
  const [stopping, setStopping] = useState(false);
  const [qrImage, setQrImage] = useState<string>("");
  const [showQr, setShowQr] = useState(false);
  const [hasComments, setHasComments] = useState(false);
  const [hasDynamics, setHasDynamics] = useState(false);
  const [configLoaded, setConfigLoaded] = useState(false);

  useEffect(() => {
    readConfig()
      .then((loadedConfig) => {
        setConfig(loadedConfig);
        if (loadedConfig.background_path) {
          readBackgroundDataUrl(loadedConfig.background_path)
            .then(setBackgroundDataUrl)
            .catch((error) => pushLog(`恢复背景失败：${String(error)}`));
        }
        setConfigLoaded(true);
      })
      .catch((error) => {
        const message = `读取界面配置失败：${String(error)}`;
        toast.error(message);
        pushLog(message);
        setConfigLoaded(true);
      });
    const cleanup = onSidecarEvent(handleSidecarEvent);
    sendSidecar("session.status").catch(() => undefined);
    return () => {
      cleanup.then((dispose) => dispose());
    };
  }, []);

  useEffect(() => {
    document.documentElement.dataset.theme = config.theme;
    if (!configLoaded) return;
    writeConfig(config).catch((error) => {
      const message = `保存界面配置失败：${String(error)}`;
      toast.error(message);
      pushLog(message);
    });
  }, [config, configLoaded]);

  const currentHasData = mode === "comments" ? hasComments : mode === "dynamics" ? hasDynamics : false;

  function pushLog(message: string) {
    setLogs((items) => [...items.slice(-300), message]);
  }

  function updateProgress(percent: unknown) {
    if (typeof percent !== "number" || Number.isNaN(percent)) return;
    setProgressPercent(Math.max(0, Math.min(100, Math.round(percent))));
  }

  function handleSidecarEvent(event: SidecarEvent) {
    if (event.kind === "response" && event.ok === false) {
      const message = event.error || "请求失败";
      toast.error(message);
      pushLog(message);
      setRunning(false);
      setStopping(false);
      return;
    }
    if (event.kind !== "event") return;
    switch (event.event) {
      case "ready":
        pushLog("Python sidecar 已连接");
        break;
      case "log":
        if (event.message) pushLog(event.message);
        break;
      case "progress":
        setRunning(event.status === "running");
        updateProgress(event.percent);
        if (event.status === "running") setSummary("任务运行中");
        if (event.status === "running") setProgressStatus("爬取进度");
        if (event.status === "idle") {
          setSummary("就绪");
          setStopping(false);
          setProgressStatus("爬取进度");
        }
        break;
      case "stats":
        setStats(event.stats || {});
        break;
      case "finished":
        setRunning(false);
        setStopping(false);
        setProgressPercent(100);
        setProgressStatus("爬取完成");
        setSummary(`完成：${event.count ?? 0} 条`);
        if (event.mode === "comments") setHasComments(Boolean(event.count));
        if (event.mode === "dynamics") setHasDynamics(Boolean(event.count));
        toast.success(`任务完成，获取 ${event.count ?? 0} 条数据`);
        break;
      case "error":
        setRunning(false);
        setStopping(false);
        setProgressStatus("爬取进度");
        setSummary("任务失败");
        toast.error(event.message || "任务失败");
        if (event.message) pushLog(`错误：${event.message}`);
        break;
      case "qr":
        if (event.image) {
          setQrImage(event.image);
          setShowQr(true);
        }
        break;
      case "login.success":
        setLoggedIn(true);
        setShowQr(false);
        toast.success("扫码登录成功");
        break;
    }
  }

  async function startTask() {
    if (mode === "settings") return;
    const taskName = mode === "comments" ? "评论" : "动态";
    setLogs([`正在启动${taskName}爬取...`]);
    setProgressPercent(0);
    setProgressStatus("爬取进度");
    setStopping(false);
    setSummary("任务运行中");
    setRunning(true);
    if (mode === "comments") {
      if (!forms.commentTarget.trim()) {
        toast.warning("请输入视频、动态、专栏链接或 ID");
        setRunning(false);
        setSummary("就绪");
        return;
      }
      const maxPages = parsePageCount(forms.commentPages, 100, 1, 1000);
      setHasComments(false);
      await sendSidecar("comments.start", {
        input: forms.commentTarget.trim(),
        include_replies: forms.includeReplies,
        max_pages: maxPages,
        sort_mode: forms.sortMode === "time" ? 3 : 2
      });
    } else {
      const uid = parseUid(forms.dynamicTarget);
      if (!uid && !loggedIn) {
        setRunning(false);
        setSummary("就绪");
        toast.warning("爬取关注页动态流需要先扫码登录");
        return;
      }
      const seconds = timePresetSeconds[forms.timeRange] || 0;
      const now = Math.floor(Date.now() / 1000);
      const maxPages = parsePageCount(forms.dynamicPages, 20, 1, 100);
      setHasDynamics(false);
      await sendSidecar("dynamics.start", {
        uid,
        keyword: forms.keyword.trim(),
        max_pages: maxPages,
        start_ts: seconds ? now - seconds : 0,
        end_ts: 0
      });
    }
  }

  async function stopTask() {
    if (stopping) return;
    setStopping(true);
    setSummary("正在停止爬取");
    setProgressStatus("正在停止");
    pushLog("正在停止爬取...");
    toast.info("正在停止爬取");
    await sendSidecar("task.stop");
  }

  async function exportCsv() {
    if (mode === "settings") return;
    const path = await chooseCsvPath(mode === "comments" ? "bilibili_comments.csv" : "bilibili_dynamics.csv");
    if (!path) return;
    await sendSidecar("export.csv", { kind: mode, path });
    toast.success("已发送导出请求");
  }

  async function openQrLogin() {
    setShowQr(true);
    setQrImage("");
    await sendSidecar("qr.login.start");
  }

  function closeQrLogin() {
    setShowQr(false);
    sendSidecar("qr.login.cancel").catch(() => undefined);
  }

  const statCards = useMemo(
    () => [
      { icon: BarChart3, label: mode === "dynamics" ? "动态总数" : "总评论数", value: stats.total ?? 0 },
      { icon: MessageCircle, label: "主评论", value: stats.main_comments ?? "-" },
      { icon: Radio, label: "回复", value: stats.replies ?? "-" },
      { icon: Clock3, label: "点赞", value: stats.total_likes ?? "-" }
    ],
    [mode, stats]
  );

  return (
    <div className="app-root">
      <BackgroundLayer config={config} backgroundDataUrl={backgroundDataUrl} logo={logo} />
      <main className="shell">
        <TitleBar logo={logo} onLog={pushLog} />
        <section className="layout">
          <SideNav mode={mode} onModeChange={setMode} running={running} loggedIn={loggedIn} />
          <TaskWorkspace
            mode={mode}
            forms={forms}
            setForms={setForms}
            config={config}
            setConfig={setConfig}
            setBackgroundDataUrl={setBackgroundDataUrl}
            onQrLogin={openQrLogin}
            loggedIn={loggedIn}
            onLog={pushLog}
          />
          <RightPanel
            summary={summary}
            running={running}
            loggedIn={loggedIn}
            logs={logs}
            statCards={statCards}
            progressPercent={progressPercent}
            progressStatus={progressStatus}
          />
        </section>
        <BottomActionBar
          mode={mode}
          running={running}
          stopping={stopping}
          canExport={currentHasData}
          onStart={startTask}
          onStop={stopTask}
          onExport={exportCsv}
        />
      </main>
      {showQr && (
        <div className="modal-backdrop" onClick={closeQrLogin}>
          <div className="qr-modal" onClick={(event) => event.stopPropagation()}>
            <div className="modal-heading">
              <UserRoundCheck size={22} />
              <div>
                <strong>扫码登录</strong>
                <span>关注页动态流需要登录态</span>
              </div>
            </div>
            {qrImage ? <img src={qrImage} alt="Bilibili 登录二维码" /> : <Loader2 className="spin" size={54} />}
            <button className="ghost-button" onClick={closeQrLogin}>
              关闭
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

function parsePageCount(raw: string, fallback: number, min: number, max: number): number {
  const parsed = Number.parseInt(raw, 10);
  if (!Number.isFinite(parsed)) return fallback;
  return Math.max(min, Math.min(max, parsed));
}

function parseUid(input: string): number | null {
  const trimmed = input.trim();
  if (!trimmed) return null;
  const match = trimmed.match(/space\.bilibili\.com\/(\d+)/);
  if (match) return Number(match[1]);
  if (/^\d+$/.test(trimmed) && Number(trimmed) < 10 ** 12) return Number(trimmed);
  return null;
}
