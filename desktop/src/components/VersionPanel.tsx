import { useEffect, useRef, useState } from "react";
import { getVersion } from "@tauri-apps/api/app";
import { openUrl } from "@tauri-apps/plugin-opener";
import { isTauri } from "../lib/tauri";
import { checkForUpdate, isNewerVersion, RELEASES_URL, type DesktopRelease } from "../lib/updates";

export function VersionPanel({ running }: { running: boolean }) {
  const [version, setVersion] = useState<string | null>(() => isTauri() ? null : __APP_VERSION__);
  const [busy, setBusy] = useState(false);
  const [release, setRelease] = useState<DesktopRelease | null>(null);
  const [message, setMessage] = useState("");
  const pending = useRef(false);
  const request = useRef<AbortController | null>(null);
  useEffect(() => {
    let active = true;
    if (isTauri()) getVersion().then((value) => { if (active) setVersion(value); })
      .catch(() => { if (active) setMessage("读取版本失败，请重启应用。"); });
    return () => { active = false; request.current?.abort(); };
  }, []);

  async function check() {
    if (!version || pending.current) return;
    pending.current = true;
    setBusy(true);
    setRelease(null);
    setMessage("正在检查更新…");
    const controller = new AbortController();
    request.current = controller;
    const timeout = setTimeout(() => controller.abort(), 15000);
    try {
      const latest = await checkForUpdate(controller.signal);
      if (isNewerVersion(latest.version, version)) {
        setRelease(latest);
        setMessage(latest.downloadUrl ? `发现新版本 v${latest.version}` : `v${latest.version} 安装包尚未就绪，请稍后重试。`);
      } else setMessage("当前已是最新版本。");
    } catch (error) {
      setMessage(controller.signal.aborted ? "检查超时或已取消，请重试。" : `无法检查更新：${error instanceof Error ? error.message : String(error)}`);
    } finally {
      clearTimeout(timeout);
      pending.current = false;
      setBusy(false);
    }
  }

  async function open(url: string) {
    try { await openUrl(url); }
    catch { setMessage("无法打开浏览器，请稍后重试。"); }
  }

  return <section className="version-panel" aria-label="版本与更新">
    <strong>{version ? `当前版本 v${version}` : "正在读取版本…"}</strong>
    {!isTauri() && <p>浏览器预览 · 更新请使用桌面版</p>}
    <button disabled={!isTauri() || !version || busy} onClick={() => void check()}>{busy ? "检查中…" : "检查更新"}</button>
    <p role="status">{message}</p>
    {release && <>
      <details><summary>更新说明</summary><pre>{release.notes}</pre></details>
      {release.downloadUrl && <>
        <button disabled={running} onClick={() => void open(release.downloadUrl!)}>下载安装更新</button>
        <p>{running ? "请等待当前任务结束后更新。" : "在浏览器中下载安装包，退出本应用后运行安装程序。"}</p>
      </>}
    </>}
    {isTauri() && <button onClick={() => void open(release?.url ?? RELEASES_URL)}>查看发布页面</button>}
  </section>;
}
