import {
  ArrowLeft,
  Check,
  CircleAlert,
  Cloud,
  CloudOff,
  ExternalLink,
  Film,
  Image as ImageIcon,
  ListVideo,
  LoaderCircle,
  Play,
  RefreshCw,
  Save,
  ShieldCheck,
} from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import {
  confirmVideoProductionPlan,
  getAssetTunnelStatus,
  getVideoProductionPlan,
  queueVideoProductionPlan,
  startAssetTunnel,
  stopAssetTunnel,
} from "../lib/api";
import type {
  AssetTunnelStatus,
  Project,
  VideoProductionPlan,
  VideoProductionPlanItem,
} from "../types";

interface VideoWorkspaceProps {
  project: Project | null;
  onBack: () => void;
  onOpenAssets: () => void;
  onOpenApiSettings: () => void;
  onOpenTasks: () => void;
  onPlanReady: () => Promise<void>;
  videoModelConfigured: boolean;
}

const KIND_LABEL = { character: "角色", scene: "场景", prop: "道具" } as const;
const VIDEO_REQUEST_SECONDS = 30;

function countVideoRequests(items: VideoProductionPlanItem[], selectedIds: string[]) {
  const selected = new Set(selectedIds);
  let count = 0;
  let batchSeconds = 0;
  let previous: VideoProductionPlanItem | null = null;

  for (const item of items) {
    if (!selected.has(item.id)) continue;
    const canAppend = previous
      && item.episodeNumber === previous.episodeNumber
      && item.groupIndex === previous.groupIndex + 1
      && item.aspectRatio === previous.aspectRatio
      && item.targetModel === previous.targetModel
      && batchSeconds + item.durationSeconds <= VIDEO_REQUEST_SECONDS;
    if (canAppend) {
      batchSeconds += item.durationSeconds;
    } else {
      count += 1;
      batchSeconds = item.durationSeconds;
    }
    previous = item;
  }
  return count;
}

export function VideoWorkspace({
  project,
  onBack,
  onOpenAssets,
  onOpenApiSettings,
  onOpenTasks,
  onPlanReady,
  videoModelConfigured,
}: VideoWorkspaceProps) {
  const [plan, setPlan] = useState<VideoProductionPlan | null>(null);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [tunnel, setTunnel] = useState<AssetTunnelStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [tunnelBusy, setTunnelBusy] = useState(false);
  const [queueing, setQueueing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const projectId = project?.id;

  const loadPlan = useCallback(async () => {
    if (!projectId) return;
    setLoading(true);
    setError(null);
    try {
      const [result, tunnelResult] = await Promise.all([
        getVideoProductionPlan(projectId),
        getAssetTunnelStatus(),
      ]);
      setPlan(result);
      setTunnel(tunnelResult);
      setSelectedIds(result.current ? result.selectedItemIds : []);
      setActiveId((current) => (
        current && result.items.some((item) => item.id === current)
          ? current
          : result.items[0]?.id ?? null
      ));
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "视频生产预检读取失败");
    } finally {
      setLoading(false);
    }
  }, [projectId]);

  useEffect(() => {
    if (!projectId) {
      setLoading(false);
      return;
    }
    void loadPlan();
  }, [loadPlan, projectId]);

  const activeItem = plan?.items.find((item) => item.id === activeId) ?? null;
  const readyItems = plan?.items.filter((item) => item.ready) ?? [];
  const blockedCount = (plan?.items.length ?? 0) - readyItems.length;
  const requestCount = countVideoRequests(plan?.items ?? [], selectedIds);

  const toggleItem = (item: VideoProductionPlanItem) => {
    if (!item.ready) return;
    setSelectedIds((current) => (
      current.includes(item.id)
        ? current.filter((id) => id !== item.id)
        : [...current, item.id]
    ));
  };

  const savePlan = async () => {
    if (!project || !selectedIds.length) return;
    setSaving(true);
    setError(null);
    try {
      const saved = await confirmVideoProductionPlan(project.id, selectedIds);
      setPlan(saved);
      setSelectedIds(saved.selectedItemIds);
      await onPlanReady();
    } catch (saveError) {
      setError(saveError instanceof Error ? saveError.message : "视频生产清单保存失败");
    } finally {
      setSaving(false);
    }
  };

  const changeTunnel = async (start: boolean) => {
    if (!project) return;
    setTunnelBusy(true);
    setError(null);
    try {
      setTunnel(
        start
          ? await startAssetTunnel(project.id)
          : await stopAssetTunnel(project.id),
      );
    } catch (tunnelError) {
      setError(tunnelError instanceof Error ? tunnelError.message : "临时素材通道操作失败");
    } finally {
      setTunnelBusy(false);
    }
  };

  const queueVideos = async () => {
    if (!project) return;
    setQueueing(true);
    setError(null);
    try {
      await queueVideoProductionPlan(project.id);
      onOpenTasks();
    } catch (queueError) {
      setError(queueError instanceof Error ? queueError.message : "视频任务提交失败");
    } finally {
      setQueueing(false);
    }
  };

  if (!project) {
    return (
      <main className="source-empty">
        <Film size={30} />
        <h1>还没有可制作视频的项目</h1>
        <p>先返回创作空间选择项目。</p>
        <button className="button secondary" type="button" onClick={onBack}>返回创作空间</button>
      </main>
    );
  }

  return (
    <main className="video-page">
      <header className="video-page-heading">
        <div>
          <button className="source-back" type="button" onClick={onBack}>
            <ArrowLeft size={16} /> 返回创作空间
          </button>
          <h1>视频生产工作台</h1>
          <p>{project.name} · 分镜组、资产参考与视频提示词生产预检</p>
        </div>
        <div className={plan?.current ? "video-plan-status current" : "video-plan-status"}>
          <ShieldCheck size={17} />
          {plan?.current ? `生产清单已确认 ${plan.selectedItemIds.length} 组` : "尚未确认生产清单"}
        </div>
      </header>

      {error ? <div className="source-alert">{error}</div> : null}

      {loading ? (
        <section className="video-loading"><LoaderCircle className="spinning" size={24} /> 正在整理视频生产资料…</section>
      ) : !plan ? (
        <section className="video-gate">
          <CircleAlert size={28} />
          <div><h2>暂时无法建立视频生产清单</h2><p>请先完成分镜和一致性资产。</p></div>
          <button className="button primary" type="button" onClick={onOpenAssets}>返回资产工作台</button>
        </section>
      ) : (
        <>
          {plan.confirmedAt && !plan.current ? (
            <div className="video-stale-warning" role="alert">
              分镜或资产已发生变化，旧生产清单已过期，请重新选择并保存。
            </div>
          ) : null}

          <section className="video-summary" aria-label="视频生产预检摘要">
            <div><span>镜头组总数</span><strong>{plan.items.length}</strong></div>
            <div><span>可进入生产</span><strong>{readyItems.length}</strong></div>
            <div><span>存在缺失项</span><strong>{blockedCount}</strong></div>
            <div><span>本次已选择</span><strong>{selectedIds.length}</strong></div>
          </section>

          <section className="video-plan-toolbar">
            <div>
              <strong>视频生产预检</strong>
              <span>保存清单不消耗额度；生成时连续分镜自动合并，每条固定 30 秒并按条计费。</span>
            </div>
            <button className="button secondary compact" type="button" onClick={() => void loadPlan()}>
              <RefreshCw size={15} /> 刷新预检
            </button>
            <button
              className="button secondary compact"
              type="button"
              disabled={!readyItems.length}
              onClick={() => setSelectedIds(readyItems.map((item) => item.id))}
            >
              <Check size={15} /> 选择全部可用项
            </button>
            <button
              className="button primary compact"
              type="button"
              disabled={!selectedIds.length || saving}
              onClick={savePlan}
            >
              {saving ? <LoaderCircle className="spinning" size={15} /> : <Save size={15} />}
              {saving ? "正在保存…" : `保存生产清单 ${selectedIds.length}`}
            </button>
          </section>

          <div className="video-plan-layout">
            <aside className="video-group-list" aria-label="分镜组生产列表">
              {plan.items.map((item) => {
                const selected = selectedIds.includes(item.id);
                return (
                  <div className={`video-group-row${activeId === item.id ? " active" : ""}${item.ready ? "" : " blocked"}`} key={item.id}>
                    <input
                      type="checkbox"
                      checked={selected}
                      disabled={!item.ready}
                      aria-label={`选择第 ${item.episodeNumber} 集镜头组 ${item.groupIndex}`}
                      onChange={() => toggleItem(item)}
                    />
                    <button type="button" onClick={() => setActiveId(item.id)}>
                      <span><b>第 {item.episodeNumber} 集 · 组 {item.groupIndex}</b><small>{item.durationSeconds} 秒 · {item.aspectRatio} · {item.targetModel}</small></span>
                      <em className={item.ready ? "ready" : ""}>{item.ready ? `${item.assetReferences.length} 项参考` : `${item.blockingReasons.length} 项待补`}</em>
                    </button>
                  </div>
                );
              })}
            </aside>

            <article className="video-plan-detail">
              {activeItem ? (
                <>
                  <header>
                    <div>
                      <span>第 {activeItem.episodeNumber} 集《{activeItem.episodeTitle}》</span>
                      <h2>镜头组 {activeItem.groupIndex} · 第 {activeItem.sceneIndex} 场</h2>
                      <p>{activeItem.purpose}</p>
                    </div>
                    <strong className={activeItem.ready ? "ready" : "blocked"}>{activeItem.ready ? "可进入生产" : "存在缺失项"}</strong>
                  </header>

                  {activeItem.blockingReasons.length ? (
                    <section className="video-blockers">
                      <h3><CircleAlert size={16} /> 生成前必须处理</h3>
                      {activeItem.blockingReasons.map((reason) => <p key={reason}>{reason}</p>)}
                    </section>
                  ) : null}

                  <section className="video-reference-section">
                    <h3><ImageIcon size={16} /> 自动关联的主参考图</h3>
                    {activeItem.assetReferences.length ? (
                      <div className="video-reference-grid">
                        {activeItem.assetReferences.map((reference) => (
                          <div key={reference.assetId}>
                            <img src={reference.imageUrl} alt={`${reference.name}主参考图`} loading="lazy" />
                            <span><b>{reference.name}</b><small>{KIND_LABEL[reference.kind]} · {reference.direct ? "直接命中" : "场次关联"}</small></span>
                          </div>
                        ))}
                      </div>
                    ) : <p className="video-empty-reference">当前镜头没有可用的资产主参考图。</p>}
                  </section>

                  <section className="video-prompt-section">
                    <h3><ListVideo size={16} /> 将要提交的视频提示词</h3>
                    <pre>{activeItem.prompt}</pre>
                  </section>
                </>
              ) : <div className="video-no-selection"><ListVideo size={26} />请选择一个镜头组查看生产资料</div>}
            </article>
          </div>

          <section className={tunnel?.running ? "video-tunnel-card running" : "video-tunnel-card"}>
            <div className="video-tunnel-icon">
              {tunnel?.running ? <Cloud size={22} /> : <CloudOff size={22} />}
            </div>
            <div>
              <strong>{tunnel?.running ? "临时素材通道运行中" : "临时素材公网通道"}</strong>
              <p>
                {tunnel?.running
                  ? `仅开放本清单的 ${tunnel.exposedAssetCount} 项参考素材；视频任务结束后立即关闭。`
                  : tunnel?.installed
                    ? "已检测到 cloudflared；确认生产清单后可开启随机令牌保护的临时 HTTPS 通道。"
                    : "尚未检测到 cloudflared。安装完成前不会开放任何本地素材。"}
              </p>
              {tunnel?.running && tunnel.publicUrl ? <small>{tunnel.publicUrl}</small> : null}
              {tunnel?.running ? <small className="warning">{tunnel.warning}</small> : null}
              {tunnel?.error ? <small className="error">{tunnel.error}</small> : null}
            </div>
            {!tunnel?.installed ? (
              <a
                className="button secondary compact"
                href="https://developers.cloudflare.com/tunnel/downloads/"
                target="_blank"
                rel="noreferrer"
              >
                官方安装说明 <ExternalLink size={14} />
              </a>
            ) : (
              <button
                className={tunnel.running ? "button secondary compact" : "button primary compact"}
                type="button"
                disabled={tunnelBusy || (!tunnel.running && (!plan.current || !selectedIds.length))}
                onClick={() => void changeTunnel(!tunnel.running)}
              >
                {tunnelBusy ? <LoaderCircle className="spinning" size={15} /> : tunnel.running ? <CloudOff size={15} /> : <Cloud size={15} />}
                {tunnelBusy ? "正在处理…" : tunnel.running ? "立即关闭" : "开启临时通道"}
              </button>
            )}
          </section>

          <footer className="video-next-step">
            <Film size={21} />
            <div>
              <strong>{videoModelConfigured ? "视频模型已配置" : "下一步：配置视频模型"}</strong>
              <p>{videoModelConfigured ? `已选 ${selectedIds.length} 个分镜组，预计提交 ${requestCount} 条 30 秒视频；素材通道会自动开启并关闭。` : "先保存服务商、模型和密钥，并进行不会消耗额度的模型列表测试。"}</p>
            </div>
            <div className="video-next-actions">
              <button className="button secondary compact" type="button" onClick={onOpenApiSettings}>
                {videoModelConfigured ? "查看配置" : "配置视频模型"}
              </button>
              {videoModelConfigured ? (
                <button
                  className="button primary compact"
                  type="button"
                  disabled={queueing || !plan.current || !selectedIds.length || !tunnel?.installed}
                  onClick={() => void queueVideos()}
                >
                  {queueing ? <LoaderCircle className="spinning" size={15} /> : <Play size={15} />}
                  {queueing ? "正在提交…" : `生成 ${requestCount} 条30秒视频（按条计费）`}
                </button>
              ) : null}
            </div>
          </footer>
        </>
      )}
    </main>
  );
}
