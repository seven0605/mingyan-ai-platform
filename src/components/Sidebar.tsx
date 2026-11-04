import {
  Boxes,
  Clapperboard,
  Code2,
  FileText,
  Film,
  FolderKanban,
  LayoutDashboard,
  Library,
  PackageOpen,
  PanelTop,
  Plug,
} from "lucide-react";
import type { ComponentType } from "react";
import type { PageId } from "../types";

interface NavigationItem {
  id: PageId;
  label: string;
  icon: ComponentType<{ size?: number; strokeWidth?: number }>;
  dividerBefore?: boolean;
}

const NAVIGATION: NavigationItem[] = [
  { id: "workspace", label: "创作空间", icon: LayoutDashboard },
  { id: "source", label: "原文与剧本", icon: FileText },
  { id: "storyboard", label: "分镜工作台", icon: Clapperboard },
  { id: "assets", label: "角色·场景·物品", icon: Boxes },
  { id: "prompts", label: "提示词模板", icon: PanelTop },
  { id: "tasks", label: "任务中心", icon: FolderKanban, dividerBefore: true },
  { id: "plugins", label: "插件管理", icon: Plug },
  { id: "api", label: "API 设置", icon: Code2 },
  { id: "library", label: "素材库", icon: Library, dividerBefore: true },
  { id: "export", label: "成片导出", icon: PackageOpen },
];

interface SidebarProps {
  activePage: PageId;
  onNavigate: (page: PageId) => void;
}

export function Sidebar({ activePage, onNavigate }: SidebarProps) {
  return (
    <aside className="sidebar">
      <button className="brand" type="button" onClick={() => onNavigate("workspace")}>
        <img src="/assets/brand-mark.png" alt="明琰AI平台标志" />
        <span>明琰AI平台</span>
      </button>

      <nav className="navigation" aria-label="主导航">
        {NAVIGATION.map(({ id, label, icon: Icon, dividerBefore }) => (
          <div className={dividerBefore ? "navigation-group divider" : "navigation-group"} key={id}>
            <button
              className={activePage === id ? "nav-item active" : "nav-item"}
              type="button"
              onClick={() => onNavigate(id)}
              aria-current={activePage === id ? "page" : undefined}
            >
              <Icon size={19} strokeWidth={1.8} />
              <span>{label}</span>
            </button>
          </div>
        ))}
      </nav>

      <div className="sidebar-footer">
        <Film size={16} strokeWidth={1.7} />
        <span>项目与素材保存在本机</span>
      </div>
    </aside>
  );
}
