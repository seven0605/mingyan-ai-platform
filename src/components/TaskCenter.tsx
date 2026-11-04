import { useEffect, useMemo, useState } from "react";
import {
  AlertCircle,
  ArrowLeft,
  CheckCircle2,
  Clock3,
  FolderKanban,
  Image as ImageIcon,
  LoaderCircle,
  PauseCircle,
  RefreshCw,
  RotateCcw,
  Video,
  X,
} from "lucide-react";
import { getProjectTasks, resumeProjectTasks, retryProjectTask } from "../lib/api";
import type { Project, ProjectTask } from "../types";

interface TaskCenterProps {
  project?: Project;
  onBack: () => void;
  onOpenAssets: () => void;
}

type TaskFilter = "all" | "image" | "video";

const ASSET_KIND_LABEL = {
  character: "角色",
  scene: "场景",
  prop: "物品",
} as const;

const TASK_STATUS_META = {
  queued: { label: "排队中", icon: Clock3 },
  running: { label: "生成中", icon: LoaderCircle },
  completed: { label: "已完成", icon: CheckCircle2 },
  failed: { label: "失败", icon: AlertCircle },
  interrupted: { label: "可恢复", icon: PauseCircle },
} as const;

function formatTaskTime(value: string) {
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

export function TaskCenter({ project, onBack, onOpenAssets }: TaskCenterProps) {
  const [tasks, setTasks] = useState<ProjectTask[]>([]);
  const [filter, setFilter] = useState<TaskFilter>("all");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [previewTask, setPreviewTask] = useState<ProjectTask | null>(null);
  const [actingId, setActingId] = useState<string | null>(null);

  const loadTasks = async (quiet = false) => {
    if (!project) {
      setTasks([]);
      return;
    }
    if (!quiet) setLoading(true);
    setError(null);
    try {
      setTasks(await getProjectTasks(project.id));
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "任务记录读取失败");
    } finally {
      if (!quiet) setLoading(false);
    }
  };

  useEffect(() => {
    void loadTasks();
  }, [project?.id]);

  const hasActiveTasks = tasks.some((task) => task.status === "queued" || task.status === "running");

  useEffect(() => {
    if (!project || !hasActiveTasks) return;
    const timer = window.setInterval(() => void loadTasks(true), 2000);
    return () => window.clearInterval(timer);
  }, [project?.id, hasActiveTasks]);

  const filteredTasks = useMemo(() => {
    if (filter === "video") return [];
    return tasks;
  }, [filter, tasks]);

  const completedCount = tasks.filter((task) => task.status === "completed").length;
  const activeCount = tasks.filter((task) => task.status === "queued" || task.status === "running").length;
  const failedCount = tasks.filter((task) => task.status === "failed").length;
  const interruptedCount = tasks.filter((task) => task.status === "interrupted").length;

  const handleRetry = async (task: ProjectTask) => {
    if (!project) return;
    setActingId(task.id);
    setError(null);
    try {
      await retryProjectTask(project.id, task.id);
      await loadTasks(true);
    } catch (retryError) {
      setError(retryError instanceof Error ? retryError.message : "任务重试失败");
    } finally {
      setActingId(null);
    }
  };

  const handleResume = async () => {
    if (!project) return;
    setActingId("resume");
    setError(null);
    try {
      await resumeProjectTasks(project.id);
      await loadTasks(true);
    } catch (resumeError) {
      setError(resumeError instanceof Error ? resumeError.message : "队列恢复失败");
    } finally {
      setActingId(null);
    }
  };

  return (
    <main className="task-page">
      <header className="task-page-heading">
        <div>
          <button className="text-action" type="button" onClick={onBack}>
            <ArrowLeft size={15} /> 返回创作空间
          </button>
          <h1>任务中心</h1>
          <p>集中查看图像与视频生成记录；刷新和预览不会调用模型或消耗额度。</p>
        </div>
        <div className="task-heading-actions">
          {interruptedCount ? (
            <button className="button primary compact" type="button" onClick={handleResume} disabled={actingId !== null}>
              {actingId === "resume" ? <LoaderCircle className="spinning" size={15} /> : <RotateCcw size={15} />}
              恢复队列（可能消耗额度）
            </button>
          ) : null}
          <button className="button secondary compact" type="button" onClick={() => void loadTasks()} disabled={!project || loading}>
            <RefreshCw className={loading ? "spinning" : ""} size={15} />
            {loading ? "正在刷新…" : "刷新记录"}
          </button>
        </div>
      </header>

      {!project ? (
        <section className="task-empty">
          <FolderKanban size={28} />
          <h2>请先选择项目</h2>
          <p>任务记录按项目保存在本机。</p>
        </section>
      ) : (
        <>
          <section className="task-summary" aria-label="任务统计">
            <div><span>全部任务</span><strong>{tasks.length}</strong></div>
            <div><span>已完成</span><strong>{completedCount}</strong></div>
            <div><span>执行中</span><strong>{activeCount}</strong></div>
            <div><span>需处理</span><strong>{failedCount + interruptedCount}</strong></div>
          </section>

          <section className="task-board">
            <header>
              <div>
                <h2>{project.name}</h2>
                <span>本机任务记录</span>
              </div>
              <nav className="task-filters" aria-label="任务类型筛选">
                <button className={filter === "all" ? "active" : ""} type="button" onClick={() => setFilter("all")}>全部</button>
                <button className={filter === "image" ? "active" : ""} type="button" onClick={() => setFilter("image")}>图像</button>
                <button className={filter === "video" ? "active" : ""} type="button" onClick={() => setFilter("video")}>视频</button>
              </nav>
            </header>

            {error ? <div className="form-error task-error">{error}</div> : null}
            {loading && !tasks.length ? (
              <div className="task-loading"><LoaderCircle className="spinning" size={22} /> 正在读取任务记录…</div>
            ) : filteredTasks.length ? (
              <div className="task-list" role="table" aria-label="生成任务记录">
                <div className="task-list-head" role="row">
                  <span>任务</span><span>状态</span><span>模型 / 任务号</span><span>创建时间</span><span>结果</span>
                </div>
                {filteredTasks.map((task) => {
                  const statusMeta = TASK_STATUS_META[task.status];
                  const StatusIcon = statusMeta.icon;
                  return (
                  <article className="task-row" role="row" key={task.id}>
                    <div className="task-name-cell">
                      <span className="task-type-icon"><ImageIcon size={17} /></span>
                      <div>
                        <strong>{task.title}</strong>
                        <span>{ASSET_KIND_LABEL[task.assetKind]}资产 · 第 {task.attemptCount} 次执行</span>
                        {task.error ? <small>{task.error}</small> : null}
                      </div>
                    </div>
                    <span className={`task-status ${task.status}`}>
                      <StatusIcon className={task.status === "running" ? "spinning" : ""} size={14} />
                      {statusMeta.label}
                    </span>
                    <div className="task-model-cell"><strong>{task.model}</strong><span>{task.providerTaskId || "无服务商任务号"}</span></div>
                    <span className="task-time"><Clock3 size={13} /> {formatTaskTime(task.createdAt)}</span>
                    {task.status === "completed" && task.resultUrl ? (
                      <button className="task-preview-button" type="button" onClick={() => setPreviewTask(task)}>查看结果</button>
                    ) : task.status === "failed" ? (
                      <button className="task-preview-button retry" type="button" disabled={actingId !== null} onClick={() => handleRetry(task)}>
                        {actingId === task.id ? "重试中…" : "重试（消耗额度）"}
                      </button>
                    ) : (
                      <span className="task-no-result">—</span>
                    )}
                  </article>
                  );
                })}
              </div>
            ) : (
              <div className="task-empty compact">
                {filter === "video" ? <Video size={25} /> : <ImageIcon size={25} />}
                <h2>{filter === "video" ? "尚无视频任务" : "尚无生成任务"}</h2>
                <p>{filter === "video" ? "视频模型接入后，生成记录会显示在这里。" : "完成第一张资产参考图后，记录会自动出现在这里。"}</p>
                {filter !== "video" ? <button className="button secondary compact" type="button" onClick={onOpenAssets}>前往资产工作台</button> : null}
              </div>
            )}
          </section>
        </>
      )}

      {previewTask ? (
        <div className="task-preview-lightbox" role="dialog" aria-modal="true" aria-label={`${previewTask.title}预览`} onClick={() => setPreviewTask(null)}>
          <div className="task-preview-panel" onClick={(event) => event.stopPropagation()}>
            <header>
              <div><strong>{previewTask.title}</strong><span>{previewTask.model} · {previewTask.cost === null ? "无费用记录" : `费用记录 ${previewTask.cost}`}</span></div>
              <button type="button" aria-label="关闭任务结果预览" onClick={() => setPreviewTask(null)} autoFocus><X size={20} /></button>
            </header>
            <img src={previewTask.resultUrl} alt={`${previewTask.title}生成结果`} />
          </div>
        </div>
      ) : null}
    </main>
  );
}
