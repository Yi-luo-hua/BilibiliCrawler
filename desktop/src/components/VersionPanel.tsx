import { useEffect, useRef, useState } from "react";
import { getVersion } from "@tauri-apps/api/app";
import { openUrl } from "@tauri-apps/plugin-opener";
import { isTauri } from "../lib/tauri";
import { checkFailureMessage, checkForUpdate, isNewerVersion, type DesktopRelease } from "../lib/updates";

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
      setMessage(checkFailureMessage(error, controller.signal.aborted));
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
    <a className="github-star-button" href="https://github.com/Yi-luo-hua/BilibiliCrawler"
      target="_blank" rel="noopener noreferrer" aria-label="Star：去 GitHub 为项目点星"
      title="去 GitHub 为项目点 Star"
      onClick={(event) => {
        if (isTauri()) {
          event.preventDefault();
          void open("https://github.com/Yi-luo-hua/BilibiliCrawler");
        }
      }}>
      <svg className="github-star-icon" width="23" height="23" viewBox="0 0 24 24" aria-hidden="true">
        <path fill="currentColor" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round"
          d="m12 2 3.1 6.3 6.9 1-5 4.9 1.2 6.8-6.2-3.3L5.8 21 7 14.2 2 9.3l6.9-1Z" />
      </svg>
      <svg className="github-star-lettering" width="57" height="30" viewBox="0 0 66 34" aria-hidden="true">
        <g fill="none" stroke="currentColor" strokeWidth="4.2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M17 7C12 3 4 6 5 12C6 17 17 14 18 21C19 28 8 30 3 25" />
          <path d="M28 9 27 23Q27 29 33 26M23 16 34 15" />
          <path d="M48 18C43 12 36 18 38 24C40 30 47 26 48 20M49 17 49 26" />
          <path d="m57 17 0 10M57 22Q60 15 64 17" />
        </g>
      </svg>
    </a>
  </section>;
}
