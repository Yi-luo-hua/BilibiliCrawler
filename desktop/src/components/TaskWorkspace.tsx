import { CSSProperties, Dispatch, SetStateAction } from "react";
import { ImagePlus, RotateCcw } from "lucide-react";
import { toast } from "sonner";
import { chooseBackground, clearBackground, readBackgroundDataUrl, setBackgroundFromPath } from "../lib/tauri";
import type { Mode, UIConfig } from "../types";
import type { FormsState } from "../App";

interface Props {
  mode: Mode;
  forms: FormsState;
  setForms: Dispatch<SetStateAction<FormsState>>;
  config: UIConfig;
  setConfig: Dispatch<SetStateAction<UIConfig>>;
  setBackgroundDataUrl: Dispatch<SetStateAction<string>>;
  onLog: (message: string) => void;
}

const timeOptions = ["不限", "最近1小时", "最近3小时", "最近6小时", "最近12小时", "最近1天", "最近3天", "最近7天"];

export function TaskWorkspace({
  mode,
  forms,
  setForms,
  config,
  setConfig,
  setBackgroundDataUrl,
  onLog
}: Props) {
  const patch = (data: Partial<FormsState>) => setForms((prev) => ({ ...prev, ...data }));
  const backgroundPercent = Math.max(0, Math.min(100, Math.round(config.background_opacity * 100)));

  async function handleChooseBackground() {
    try {
      const path = await chooseBackground();
      if (!path) return;
      const nextConfig = await setBackgroundFromPath(path);
      const dataUrl = await readBackgroundDataUrl(nextConfig.background_path);
      await preloadImage(dataUrl);
      setBackgroundDataUrl(dataUrl);
      setConfig(nextConfig);
      toast.success("背景已应用");
      onLog("背景图已复制到安装目录并成功应用");
    } catch (error) {
      const message = `设置背景失败：${String(error)}`;
      toast.error(message);
      onLog(message);
      try {
        const fallbackConfig = await clearBackground();
        setBackgroundDataUrl("");
        setConfig(fallbackConfig);
      } catch {
        // Keep the previous in-memory config if cleanup also fails.
      }
    }
  }

  async function handleClearBackground() {
    try {
      const nextConfig = await clearBackground();
      setBackgroundDataUrl("");
      setConfig(nextConfig);
      toast.success("已恢复默认背景");
      onLog("已恢复默认背景");
    } catch (error) {
      const message = `恢复默认背景失败：${String(error)}`;
      toast.error(message);
      onLog(message);
    }
  }

  if (mode === "settings") {
    return (
      <section className="workspace">
        <PanelTitle title="界面设置" subtitle="背景、主题和玻璃层级" />
        <div className="settings-grid">
          <label className="field">
            <span>主题</span>
            <select value={config.theme} onChange={(event) => setConfig((c) => ({ ...c, theme: event.target.value as UIConfig["theme"] }))}>
              <option value="light">浅色</option>
              <option value="dark">暗色</option>
            </select>
          </label>
          <label className="field">
            <span>背景透明度 {backgroundPercent}%</span>
            <input
              className="range-control"
              type="range"
              min={0}
              max={100}
              value={backgroundPercent}
              style={{ "--range-percent": `${backgroundPercent}%` } as CSSProperties}
              onChange={(event) => setConfig((c) => ({ ...c, background_opacity: Number(event.target.value) / 100 }))}
            />
          </label>
          <label className="check-row">
            <input type="checkbox" checked={config.background_blur} onChange={(event) => setConfig((c) => ({ ...c, background_blur: event.target.checked }))} />
            <span>背景模糊</span>
          </label>
          <div className="settings-actions">
            <button className="accent-button settings-action-button" onClick={handleChooseBackground}>
              <ImagePlus size={18} />
              <span>选择背景</span>
            </button>
            <button className="ghost-button settings-action-button" onClick={handleClearBackground}>
              <RotateCcw size={18} />
              <span>恢复默认</span>
            </button>
          </div>
        </div>
      </section>
    );
  }

  if (mode === "dynamics") {
    return (
      <section className="workspace">
        <PanelTitle title="动态爬取" subtitle="用户空间可未登录尝试，关注流需要扫码登录" />
        <div className="form-grid">
          <label className="field wide">
            <span>用户 / 空间</span>
            <input
              value={forms.dynamicTarget}
              onChange={(event) => patch({ dynamicTarget: event.target.value })}
              placeholder="用户 UID / space.bilibili.com/xxx；留空则爬关注页动态流"
            />
          </label>
          <label className="field wide">
            <span>关键词</span>
            <input value={forms.keyword} onChange={(event) => patch({ keyword: event.target.value })} placeholder="按关键词筛选动态内容，留空不过滤" />
          </label>
          <label className="field">
            <span>时间范围</span>
            <select value={forms.timeRange} onChange={(event) => patch({ timeRange: event.target.value })}>
              {timeOptions.map((item) => (
                <option key={item}>{item}</option>
              ))}
            </select>
          </label>
          <label className="field">
            <span>最大页数</span>
            <input
              type="text"
              inputMode="numeric"
              pattern="[0-9]*"
              value={forms.dynamicPages}
              onChange={(event) => patch({ dynamicPages: event.target.value.replace(/\D/g, "") })}
            />
          </label>
        </div>
      </section>
    );
  }

  return (
    <section className="workspace">
      <PanelTitle title="评论爬取" subtitle="支持视频 BV/AV、动态 t.bilibili、专栏 cv 链接" />
      <div className="form-grid">
        <label className="field wide">
          <span>链接 / ID</span>
          <input value={forms.commentTarget} onChange={(event) => patch({ commentTarget: event.target.value })} placeholder="视频 BV/AV、动态链接、专栏 CV 号或链接" />
        </label>
        <label className="field">
          <span>最大页数</span>
          <input
            type="text"
            inputMode="numeric"
            pattern="[0-9]*"
            value={forms.commentPages}
            onChange={(event) => patch({ commentPages: event.target.value.replace(/\D/g, "") })}
          />
        </label>
        <label className="check-row">
          <input type="checkbox" checked={forms.includeReplies} onChange={(event) => patch({ includeReplies: event.target.checked })} />
          <span>包含子评论 / 回复</span>
        </label>
        <label className="field">
          <span>排序模式</span>
          <select value={forms.sortMode} onChange={(event) => patch({ sortMode: event.target.value as FormsState["sortMode"] })}>
            <option value="time">按时间</option>
            <option value="hot">按热度</option>
          </select>
        </label>
      </div>
    </section>
  );
}

function preloadImage(src: string): Promise<void> {
  return new Promise((resolve, reject) => {
    if (!src) {
      reject(new Error("背景图片路径为空"));
      return;
    }
    const image = new Image();
    image.onload = () => resolve();
    image.onerror = () => reject(new Error("背景图片复制成功，但 WebView 无法加载该图片"));
    image.src = src;
  });
}

function PanelTitle({ title, subtitle }: { title: string; subtitle: string }) {
  return (
    <div className="panel-title">
      <h2>{title}</h2>
      <p>{subtitle}</p>
    </div>
  );
}
