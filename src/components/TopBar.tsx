import { Bell, CircleUserRound, Settings } from "lucide-react";

interface TopBarProps {
  onSettings: () => void;
}

export function TopBar({ onSettings }: TopBarProps) {
  return (
    <header className="topbar">
      <div className="topbar-drag-region" />
      <button className="icon-button" type="button" aria-label="通知">
        <Bell size={19} strokeWidth={1.8} />
      </button>
      <button className="icon-button" type="button" aria-label="设置" onClick={onSettings}>
        <Settings size={19} strokeWidth={1.8} />
      </button>
      <button className="avatar-button" type="button" aria-label="账户">
        <CircleUserRound size={24} strokeWidth={1.6} />
      </button>
    </header>
  );
}
