import {
  ArrowLeft,
  Check,
  CircleAlert,
  Film,
  Image as ImageIcon,
  ListVideo,
  LoaderCircle,
  RefreshCw,
  Save,
  ShieldCheck,
} from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { confirmVideoProductionPlan, getVideoProductionPlan } from "../lib/api";
import type { Project, VideoProductionPlan, VideoProductionPlanItem } from "../types";

interface VideoWorkspaceProps {
  project: Project | null;
  onBack: () => void;
  onOpenAssets: () => void;
  onPlanReady: () => Promise<void>;
}

const KIND_LABEL = { character: "角色", scene: "场景", prop: "道具" } as const;

export function VideoWorkspace({
  project,
  onBack,
  onOpenAssets,
  onPlanReady,
}: VideoWorkspaceProps) {
  const [plan, setPlan] = useState<VideoProductionPlan | null>(null);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const projectId = project?.id;

  const loadPlan = useCallback(async () => {
    if (!projectId) return;
    setLoading(true);
    setError(null);
    try {
      const result = await getVideoProductionPlan(projectId);
      setPlan(result);
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
              <span>保存清单不会调用视频模型，也不会消耗额度。</span>
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

          <footer className="video-next-step">
            <Film size={21} />
            <div><strong>下一步：接入视频模型</strong><p>生产清单确认后，再增加服务商配置、额度确认、顺序生成、失败恢复和视频预览。</p></div>
          </footer>
        </>
      )}
    </main>
  );
}
