import { Activity, BrainCircuit, KeyRound, MessageCircle, Settings, UserRoundCheck } from "lucide-react";
import clsx from "clsx";
import type { Mode } from "../types";

interface Props {
  mode: Mode;
  running: boolean;
  loggedIn: boolean;
  onQrLogin: () => void;
  onModeChange: (mode: Mode) => void;
}

const items = [
  { mode: "comments" as const, label: "评论爬取", icon: MessageCircle },
  { mode: "dynamics" as const, label: "动态爬取", icon: Activity },
  { mode: "analysis" as const, label: "舆论分析", icon: BrainCircuit },
  { mode: "settings" as const, label: "界面设置", icon: Settings }
];

export function SideNav({ mode, running, loggedIn, onQrLogin, onModeChange }: Props) {
  return (
    <aside className="side-nav">
      <div className="account-block">
        <div className="account-pill">
          <UserRoundCheck size={18} />
          <span>{loggedIn ? "已登录" : "未登录"}</span>
        </div>
        {!loggedIn ? (
          <button className="login-button side-login-button" onClick={onQrLogin}>
            <KeyRound size={17} />
            <span>扫码登录</span>
          </button>
        ) : null}
      </div>
      <nav>
        {items.map((item) => {
          const Icon = item.icon;
          return (
            <button key={item.mode} className={clsx("nav-item", mode === item.mode && "active")} disabled={running && item.mode !== mode} onClick={() => onModeChange(item.mode)}>
              <Icon size={20} />
              <span>{item.label}</span>
            </button>
          );
        })}
      </nav>
    </aside>
  );
}
