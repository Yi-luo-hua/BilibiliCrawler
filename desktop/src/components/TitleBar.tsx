import { useEffect, useState, type MouseEvent } from "react";
import { Maximize2, Minimize2, Minus, X } from "lucide-react";
import { getCurrentWindow } from "@tauri-apps/api/window";
import { toast } from "sonner";
import { isTauri } from "../lib/tauri";

interface Props {
  logo: string;
  onLog: (message: string) => void;
}

export function TitleBar({ logo, onLog }: Props) {
  const appWindow = isTauri() ? getCurrentWindow() : null;
  const [maximized, setMaximized] = useState(false);

  useEffect(() => {
    appWindow?.isMaximized().then(setMaximized).catch(() => undefined);
  }, [appWindow]);

  async function startDrag(event: MouseEvent<HTMLElement>) {
    if (event.button !== 0) return;
    try {
      await appWindow?.startDragging();
    } catch (error) {
      const message = `窗口拖动失败：${String(error)}`;
      onLog(message);
    }
  }

  async function toggleMaximize() {
    if (!appWindow) return;
    try {
      await appWindow.toggleMaximize();
      setMaximized(await appWindow.isMaximized());
    } catch (error) {
      const message = `窗口最大化失败：${String(error)}`;
      toast.error(message);
      onLog(message);
    }
  }

  async function minimizeWindow() {
    try {
      await appWindow?.minimize();
    } catch (error) {
      const message = `窗口最小化失败：${String(error)}`;
      toast.error(message);
      onLog(message);
    }
  }

  async function closeWindow() {
    try {
      await appWindow?.close();
    } catch (error) {
      const message = `窗口关闭失败：${String(error)}`;
      toast.error(message);
      onLog(message);
    }
  }

  function stopDrag(event: MouseEvent<HTMLElement>) {
    event.stopPropagation();
  }

  return (
    <header className="titlebar" data-tauri-drag-region onMouseDown={startDrag}>
      <div className="brand">
        <img src={logo} alt="" />
        <div>
          <h1>Bilibili Crawler</h1>
          <p>评论 / 动态</p>
        </div>
      </div>
      <div className="window-actions" onMouseDown={stopDrag}>
        <button aria-label="最小化" onClick={minimizeWindow}>
          <Minus size={18} />
        </button>
        <button aria-label={maximized ? "还原窗口" : "最大化"} onClick={toggleMaximize}>
          {maximized ? <Minimize2 size={18} /> : <Maximize2 size={18} />}
        </button>
        <button className="danger" aria-label="关闭" onClick={closeWindow}>
          <X size={18} />
        </button>
      </div>
    </header>
  );
}
