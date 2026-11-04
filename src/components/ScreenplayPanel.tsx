import {
  BadgeCheck,
  Clock3,
  FileCheck2,
  ListChecks,
  Pencil,
  Save,
  ScrollText,
  Sparkles,
  X,
} from "lucide-react";
import { useState } from "react";
import type { Screenplay, ScreenplayOrigin } from "../types";

interface ScreenplayPanelProps {
  screenplay: Screenplay;
  stale: boolean;
  saving: boolean;
  approving: boolean;
  refiningEpisode: number | null;
  onSave: (screenplay: Screenplay) => Promise<void>;
  onApprove: () => Promise<void>;
  onRefineEpisode: (episodeNumber: number) => Promise<void>;
}

const originLabels: Record<ScreenplayOrigin, string> = {
  source: "原著事实",
  translation: "合理转译",
  suggestion: "建议补全",
};

function formatGeneratedAt(value: string) {
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

export function ScreenplayPanel({
  screenplay,
  stale,
  saving,
  approving,
  refiningEpisode,
  onSave,
  onApprove,
  onRefineEpisode,
}: ScreenplayPanelProps) {
  const [activeEpisodeNumber, setActiveEpisodeNumber] = useState(
    screenplay.episodes[0]?.episodeNumber ?? 1,
  );
  const [draft, setDraft] = useState(screenplay);
  const [editing, setEditing] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const episode =
    draft.episodes.find((item) => item.episodeNumber === activeEpisodeNumber)
    ?? draft.episodes[0];
  const timingOutsideTolerance = draft.episodes.filter(
    (item) => Math.abs(item.estimatedSeconds - item.targetSeconds) > 10,
  );
  const fidelityPending = draft.episodes.filter(
    (item) => item.fidelityStatus !== "passed",
  );

  if (!episode) return null;

  const updateBeat = (
    sceneIndex: number,
    beatIndex: number,
    field: "speaker" | "text" | "estimatedSeconds",
    value: string | number,
  ) => {
    setDraft((current) => ({
      ...current,
      episodes: current.episodes.map((currentEpisode) => (
        currentEpisode.episodeNumber !== episode.episodeNumber
          ? currentEpisode
          : {
              ...currentEpisode,
              scenes: currentEpisode.scenes.map((scene) => (
                scene.index !== sceneIndex
                  ? scene
                  : {
                      ...scene,
                      beats: scene.beats.map((beat, index) => {
                        if (index !== beatIndex) return beat;
                        if (field === "estimatedSeconds") {
                          return { ...beat, estimatedSeconds: Number(value) };
                        }
                        return { ...beat, [field]: String(value) };
                      }),
                    }
              )),
            }
      )),
    }));
    setDirty(true);
    setActionError(null);
  };

  const cancelEditing = () => {
    setDraft(screenplay);
    setEditing(false);
    setDirty(false);
    setActionError(null);
  };

  const saveEditing = async () => {
    const hasBlankBeat = draft.episodes.some((item) =>
      item.scenes.some((scene) => scene.beats.some((beat) => !beat.text.trim())),
    );
    if (hasBlankBeat) {
      setActionError("动作、对白或旁白内容不能为空。");
      return;
    }
    try {
      setActionError(null);
      await onSave(draft);
      setEditing(false);
      setDirty(false);
    } catch (error: unknown) {
      setActionError(error instanceof Error ? error.message : "剧本保存失败");
    }
  };

  const approveDraft = async () => {
    try {
      setActionError(null);
      await onApprove();
    } catch (error: unknown) {
      setActionError(error instanceof Error ? error.message : "剧本确认失败");
    }
  };

  const refineEpisode = async () => {
    try {
      setActionError(null);
      await onRefineEpisode(episode.episodeNumber);
    } catch (error: unknown) {
      setActionError(error instanceof Error ? error.message : "单集 AI 定稿失败");
    }
  };

  return (
    <section className="screenplay-panel" aria-label="逐场剧本结果">
      <header className="screenplay-heading">
        <div>
          <div className="screenplay-title-line">
            <h2>逐场剧本</h2>
            <span className={`screenplay-status ${screenplay.status}`}>
              {screenplay.status === "approved" ? "已人工确认" : "编辑草稿"}
            </span>
          </div>
          <p>
            {screenplay.model} · {screenplay.adaptationMode === "faithful" ? "忠实改编" : "商业短剧强化"}
            {" · "}更新于 {formatGeneratedAt(screenplay.updatedAt)}
          </p>
        </div>
        <div className="screenplay-heading-actions">
          {stale ? <span className="analysis-stale">原文或策划已更新，需要重新生成</span> : null}
          {editing ? (
            <>
              <button className="button secondary compact" type="button" disabled={saving} onClick={cancelEditing}>
                <X size={15} /> 取消
              </button>
              <button className="button primary compact" type="button" disabled={!dirty || saving} onClick={saveEditing}>
                <Save size={15} /> {saving ? "保存中…" : "保存并重算"}
              </button>
            </>
          ) : (
            <>
              <button className="button secondary compact" type="button" disabled={stale || approving} onClick={() => setEditing(true)}>
                <Pencil size={15} /> 编辑剧本
              </button>
              <button
                className="button primary compact"
                type="button"
                disabled={
                  stale
                  || saving
                  || approving
                  || screenplay.status === "approved"
                  || timingOutsideTolerance.length > 0
                  || fidelityPending.length > 0
                }
                onClick={approveDraft}
              >
                <BadgeCheck size={15} /> {approving ? "确认中…" : "确认并进入分镜"}
              </button>
            </>
          )}
        </div>
      </header>

      <div className="screenplay-workflow-note">
        <div>
          {editing ? (
            <span>可修改每条画面、对白、旁白及秒数；保存后由本地服务重新汇总场次与单集时长。</span>
          ) : timingOutsideTolerance.length > 0 ? (
            <span>
              第 {timingOutsideTolerance.map((item) => item.episodeNumber).join("、")} 集尚未进入目标时长 ±10 秒，暂不能确认。
            </span>
          ) : fidelityPending.length > 0 ? (
            <span>
              第 {fidelityPending.map((item) => item.episodeNumber).join("、")} 集尚未通过原著忠实度复核。
            </span>
          ) : screenplay.status === "approved" ? (
            <span>本版已确认，可以进入分镜拆解；再次编辑并保存会恢复为草稿。</span>
          ) : (
            <span>全部剧集已通过时长与忠实度检查，可以人工确认。</span>
          )}
          {actionError ? <strong role="alert">{actionError}</strong> : null}
        </div>
        <button
          className="button secondary compact screenplay-refine-button"
          type="button"
          disabled={
            editing
            || stale
            || saving
            || approving
            || refiningEpisode !== null
            || screenplay.status === "approved"
          }
          onClick={refineEpisode}
        >
          <Sparkles size={14} />
          {refiningEpisode === episode.episodeNumber
            ? `正在定稿第 ${episode.episodeNumber} 集…`
            : Math.abs(episode.estimatedSeconds - episode.targetSeconds) > 10
              ? "AI压缩并复核本集"
              : "AI复核本集"}
        </button>
      </div>

      <div className="screenplay-episode-tabs" role="tablist" aria-label="剧集选择">
        {draft.episodes.map((item) => (
          <button
            className={item.episodeNumber === episode.episodeNumber ? "active" : ""}
            type="button"
            role="tab"
            aria-selected={item.episodeNumber === episode.episodeNumber}
            key={item.episodeNumber}
            onClick={() => setActiveEpisodeNumber(item.episodeNumber)}
          >
            <span>
              第 {item.episodeNumber} 集 · {
                item.fidelityStatus === "passed"
                  ? "忠实度通过"
                  : item.fidelityStatus === "review"
                    ? "需人工复核"
                    : "待复核"
              }
            </span>
            <strong>{item.title}</strong>
            <small>{item.estimatedSeconds}s / {item.targetSeconds}s</small>
          </button>
        ))}
      </div>

      <div className="screenplay-episode-overview">
        <div>
          <span>原文范围</span>
          <strong>{episode.sourceRange}</strong>
        </div>
        <div>
          <span>本集任务</span>
          <p>{episode.objective}</p>
        </div>
        <div>
          <span>核心冲突</span>
          <p>{episode.centralConflict}</p>
        </div>
        <div>
          <span>状态变化</span>
          <p>{episode.stateChange}</p>
        </div>
      </div>

      <div className="screenplay-scene-list">
        {episode.scenes.map((scene) => (
          <article className="screenplay-scene" key={`${episode.episodeNumber}-${scene.index}`}>
            <header>
              <div className="screenplay-scene-index">{String(scene.index).padStart(2, "0")}</div>
              <div>
                <h3>{scene.heading}</h3>
                <p>{scene.characters.join("、")}{scene.props.length ? ` · 道具：${scene.props.join("、")}` : ""}</p>
              </div>
              <span><Clock3 size={14} /> {scene.estimatedSeconds}s</span>
            </header>

            <div className="screenplay-scene-purpose">
              <p><b>目标</b>{scene.objective}</p>
              <p><b>阻力</b>{scene.obstacle}</p>
            </div>

            <div className={`screenplay-beats ${editing ? "editing" : ""}`}>
              {scene.beats.map((beat, index) => (
                <div className={`screenplay-beat ${beat.kind}`} key={`${scene.index}-${index}`}>
                  <div className="screenplay-beat-body">
                    {beat.kind === "action" ? <span className="screenplay-beat-label">画面</span> : null}
                    {beat.kind !== "action" && !editing ? <strong>{beat.speaker || "旁白"}</strong> : null}
                    {editing && beat.kind !== "action" ? (
                      <input
                        aria-label={`第 ${episode.episodeNumber} 集第 ${scene.index} 场第 ${index + 1} 条说话人`}
                        className="screenplay-speaker-input"
                        value={beat.speaker}
                        onChange={(event) => updateBeat(scene.index, index, "speaker", event.target.value)}
                      />
                    ) : null}
                    {editing ? (
                      <textarea
                        aria-label={`第 ${episode.episodeNumber} 集第 ${scene.index} 场第 ${index + 1} 条内容`}
                        value={beat.text}
                        rows={2}
                        onChange={(event) => updateBeat(scene.index, index, "text", event.target.value)}
                      />
                    ) : <p>{beat.text}</p>}
                  </div>
                  <div className="screenplay-beat-meta">
                    <span className={`origin-${beat.origin}`}>{originLabels[beat.origin]}</span>
                    <span>{beat.sourceRef}</span>
                    {editing ? (
                      <label className="screenplay-seconds-input">
                        <input
                          aria-label={`第 ${episode.episodeNumber} 集第 ${scene.index} 场第 ${index + 1} 条秒数`}
                          type="number"
                          min={1}
                          max={120}
                          value={beat.estimatedSeconds}
                          onChange={(event) => updateBeat(scene.index, index, "estimatedSeconds", event.target.value)}
                        />
                        秒
                      </label>
                    ) : <span>{beat.estimatedSeconds}s</span>}
                  </div>
                </div>
              ))}
            </div>

            <footer><FileCheck2 size={14} /> <b>场次结果</b>{scene.result}</footer>
          </article>
        ))}
      </div>

      <div className="screenplay-ending-grid">
        <section>
          <h3><ScrollText size={16} /> 本集收束</h3>
          <p><b>结束状态</b>{episode.endingState}</p>
          {episode.hook ? <p><b>结尾钩子</b>{episode.hook}</p> : null}
        </section>
        <section>
          <h3><ListChecks size={16} /> 质量与连续性</h3>
          <ul>
            {episode.qualityNotes.map((note, index) => <li key={`${index}-${note}`}>{note}</li>)}
            {episode.fidelityNotes.length ? episode.fidelityNotes.map((note, index) => (
              <li className={`fidelity-${episode.fidelityStatus}`} key={`fidelity-${index}-${note}`}>
                忠实度复核：{note}
              </li>
            )) : <li className="fidelity-unchecked">忠实度复核：尚未执行。</li>}
            {draft.continuityNotes.map((note, index) => <li key={`continuity-${index}-${note}`}>{note}</li>)}
          </ul>
        </section>
      </div>
    </section>
  );
}
