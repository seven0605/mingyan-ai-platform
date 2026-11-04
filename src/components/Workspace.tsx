import {
  Box,
  ChevronRight,
  CircleCheck,
  Clapperboard,
  Cpu,
  FileText,
  Image,
  MoreHorizontal,
  Play,
  Plus,
  ScrollText,
  Video,
} from "lucide-react";
import { useEffect, useState, type ComponentType } from "react";
import { getProjectTasks } from "../lib/api";
import type { Project, ProjectStage, ProjectTask } from "../types";

const STAGES: Array<{
  id: ProjectStage;
  label: string;
  icon: ComponentType<{ size?: number; strokeWidth?: number }>;
}> = [
  { id: "text", label: "文本", icon: FileText },
  { id: "script", label: "剧本", icon: ScrollText },
  { id: "storyboard", label: "分镜", icon: Clapperboard },
  { id: "assets", label: "资产", icon: Box },
  { id: "video", label: "视频", icon: Video },
];

function formatUpdatedAt(value: string) {
  const date = new Date(value);
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

interface WorkspaceProps {
  projects: Project[];
  currentProject?: Project;
  loading: boolean;
  backendError: string | null;
  onCreateProject: () => void;
  onSelectProject: (id: string) => void;
  onUpdateStage: (stage: ProjectStage) => void;
  onContinueProject: () => void;
  onOpenApiSettings: () => void;
  onOpenTasks: () => void;
  textModelConfigured: boolean;
  imageModelConfigured: boolean;
}

export function Workspace({
  projects,
  currentProject,
  loading,
  backendError,
  onCreateProject,
  onSelectProject,
  onUpdateStage,
  onContinueProject,
  onOpenApiSettings,
  onOpenTasks,
  textModelConfigured,
  imageModelConfigured,
}: WorkspaceProps) {
  const [latestTask, setLatestTask] = useState<ProjectTask | null>(null);

  useEffect(() => {
    if (!currentProject) {
      setLatestTask(null);
      return;
    }
    let active = true;
    getProjectTasks(currentProject.id)
      .then((tasks) => {
        if (active) setLatestTask(tasks[0] ?? null);
      })
      .catch(() => {
        if (active) setLatestTask(null);
      });
    return () => {
      active = false;
    };
  }, [currentProject?.id]);

  return (
    <main className="workspace">
      <div className="workspace-heading">
        <div>
          <h1>创作空间</h1>
          <p>从文本到成片的 AI 视频创作工作台</p>
        </div>
        <button className="button primary create-button" type="button" onClick={onCreateProject}>
          <Plus size={19} />
          新建项目
        </button>
      </div>

      {backendError ? (
        <div className="service-alert" role="alert">
          本地服务未连接：{backendError}
        </div>
      ) : null}

      {loading ? (
        <section className="empty-project loading-project">
          <h2>正在连接本地服务…</h2>
          <p>项目、素材和任务将保存在这台电脑上。</p>
        </section>
      ) : currentProject ? (
        <section className="current-project" aria-label="当前项目">
          <div className="project-mark-wrap">
            <img src="/assets/brand-mark.png" alt="" />
          </div>
          <div className="current-project-copy">
            <span>当前项目</span>
            <h2>{currentProject.name}</h2>
            <p>{currentProject.description} · 更新于 {formatUpdatedAt(currentProject.updatedAt)}</p>
          </div>
          <button className="button primary continue-button" type="button" onClick={onContinueProject}>
            <Play size={17} fill="currentColor" />
            继续创作
          </button>
          <button className="icon-button bordered" type="button" aria-label="更多操作">
            <MoreHorizontal size={19} />
          </button>
          <div className="film-ribbon" aria-hidden="true" />
        </section>
      ) : (
        <section className="empty-project">
          <img src="/assets/brand-mark.png" alt="" />
          <h2>创建你的第一个视频项目</h2>
          <p>从一段文字开始，逐步完成剧本、分镜、素材和视频。</p>
          <button className="button primary" type="button" onClick={onCreateProject}>
            <Plus size={18} />
            新建项目
          </button>
        </section>
      )}

      <section className="workflow-section">
        <h2>创作流程</h2>
        <div className="workflow" aria-label="创作流程阶段">
          {STAGES.map(({ id, label, icon: Icon }, index) => (
            <div className="workflow-item" key={id}>
              <button
                className={currentProject?.stage === id ? "stage-button active" : "stage-button"}
                type="button"
                onClick={() => onUpdateStage(id)}
                disabled={!currentProject}
              >
                <Icon size={21} strokeWidth={1.8} />
                <span>{label}</span>
              </button>
              {index < STAGES.length - 1 ? <ChevronRight className="stage-arrow" size={22} /> : null}
            </div>
          ))}
        </div>
      </section>

      <section className="recent-section">
        <div className="section-heading-row">
          <h2>最近项目</h2>
          <button className="text-button" type="button">
            查看全部 <ChevronRight size={15} />
          </button>
        </div>
        <div className="project-rail">
          {projects.slice(0, 5).map((project) => (
            <button
              className={project.id === currentProject?.id ? "project-card selected" : "project-card"}
              type="button"
              key={project.id}
              onClick={() => onSelectProject(project.id)}
            >
              <div className="project-thumbnail">
                <div className="thumbnail-film" />
              </div>
              <strong>{project.name}</strong>
              <span>更新于 {formatUpdatedAt(project.updatedAt)}</span>
            </button>
          ))}
          <button className="project-card add-card" type="button" onClick={onCreateProject}>
            <span className="add-project-icon"><Plus size={22} /></span>
            <strong>新建项目</strong>
            <span>开始新的创作</span>
          </button>
        </div>
      </section>

      <div className="overview-grid">
        <section className="overview-panel">
          <div className="section-heading-row">
            <h2>任务动态</h2>
            <button className="text-button" type="button" onClick={onOpenTasks}>
              查看任务中心 <ChevronRight size={15} />
            </button>
          </div>
          <div className="activity-list">
            <div className="activity-row">
              <span className={latestTask ? "activity-icon" : "activity-icon running"}>
                {latestTask ? <CircleCheck size={15} /> : <Play size={14} />}
              </span>
              <span>{latestTask?.title ?? "等待开始第一个生成任务"}</span>
              <em>{latestTask ? "已完成" : "空闲"}</em>
            </div>
            <div className="activity-row">
              <span className="activity-icon"><CircleCheck size={15} /></span>
              <span>项目数据已保存到本机</span>
              <em>已完成</em>
            </div>
          </div>
        </section>

        <section className="overview-panel">
          <div className="section-heading-row">
            <h2>模型连接状态</h2>
            <button className="text-button" type="button" onClick={onOpenApiSettings}>
              前往配置 <ChevronRight size={15} />
            </button>
          </div>
          <div className="connection-list">
            {[
              { label: "视频生成模型", icon: Video, configured: false },
              { label: "图像生成模型", icon: Image, configured: imageModelConfigured },
              { label: "文本与剧本模型", icon: Cpu, configured: textModelConfigured },
            ].map(({ label, icon: ConnectionIcon, configured }) => {
              return (
                <div className="connection-row" key={label}>
                  <ConnectionIcon size={17} strokeWidth={1.7} />
                  <span>{label}</span>
                  <em className={configured ? "connected" : undefined}>
                    {configured ? "已配置" : "未配置"}
                  </em>
                </div>
              );
            })}
          </div>
        </section>
      </div>
    </main>
  );
}
