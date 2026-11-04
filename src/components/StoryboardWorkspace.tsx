import { useEffect, useMemo, useState } from "react";
import {
  ArrowLeft,
  CheckCircle2,
  Clapperboard,
  Clock3,
  LoaderCircle,
  Pencil,
  RefreshCw,
  Save,
  ShieldCheck,
  Sparkles,
  X,
} from "lucide-react";
import { generateStoryboard, getScreenplay, getStoryboards, saveStoryboard } from "../lib/api";
import type {
  Project,
  Screenplay,
  Storyboard,
  StoryboardAspectRatio,
  StoryboardGroup,
  StoryboardTargetModel,
} from "../types";

interface StoryboardWorkspaceProps {
  project: Project | null;
  onBack: () => void;
  onOpenScreenplay: () => void;
}

const TARGET_MODELS: Array<{ value: StoryboardTargetModel; label: string }> = [
  { value: "seedance-2.0", label: "Seedance 2.0" },
  { value: "sora-2", label: "Sora 2" },
  { value: "kling-3.0", label: "Kling 3.0" },
  { value: "veo-3.1", label: "Veo 3.1" },
];

type StoryboardSegmentTextField = Exclude<
  keyof StoryboardGroup["segments"][number],
  "startSeconds" | "endSeconds"
>;

function timeLabel(seconds: number) {
  const minutes = Math.floor(seconds / 60);
  const remainder = seconds % 60;
  return `${String(minutes).padStart(2, "0")}:${String(remainder).padStart(2, "0")}`;
}

export function StoryboardWorkspace({
  project,
  onBack,
  onOpenScreenplay,
}: StoryboardWorkspaceProps) {
  const [screenplay, setScreenplay] = useState<Screenplay | null>(null);
  const [storyboards, setStoryboards] = useState<Storyboard[]>([]);
  const [selectedEpisode, setSelectedEpisode] = useState(1);
  const [targetModel, setTargetModel] = useState<StoryboardTargetModel>("seedance-2.0");
  const [aspectRatio, setAspectRatio] = useState<StoryboardAspectRatio>("16:9");
  const [loading, setLoading] = useState(true);
  const [generating, setGenerating] = useState(false);
  const [editingGroup, setEditingGroup] = useState<StoryboardGroup | null>(null);
  const [savingEdit, setSavingEdit] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    if (!project) {
      setLoading(false);
      return;
    }
    setLoading(true);
    setError(null);
    Promise.all([getScreenplay(project.id), getStoryboards(project.id)])
      .then(([screenplayResult, storyboardResult]) => {
        if (!active) return;
        setScreenplay(screenplayResult);
        setStoryboards(storyboardResult);
        if (screenplayResult?.episodes.length) {
          setSelectedEpisode(screenplayResult.episodes[0].episodeNumber);
        }
      })
      .catch((loadError: unknown) => {
        if (!active) return;
        setError(loadError instanceof Error ? loadError.message : "分镜数据读取失败");
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [project]);

  const selectedStoryboard = useMemo(
    () => storyboards.find((item) => item.episodeNumber === selectedEpisode) ?? null,
    [selectedEpisode, storyboards],
  );
  const selectedScreenplayEpisode = screenplay?.episodes.find(
    (episode) => episode.episodeNumber === selectedEpisode,
  );
  const storyboardIsCurrent = Boolean(
    selectedStoryboard && screenplay && selectedStoryboard.screenplayUpdatedAt === screenplay.updatedAt,
  );
  const canGenerate = screenplay?.status === "approved" && !generating;

  useEffect(() => {
    if (!selectedStoryboard) return;
    setTargetModel(selectedStoryboard.targetModel);
    setAspectRatio(selectedStoryboard.aspectRatio);
  }, [selectedStoryboard]);

  async function handleGenerate() {
    if (!project || !canGenerate) return;
    setGenerating(true);
    setError(null);
    try {
      const generated = await generateStoryboard(project.id, selectedEpisode, {
        targetModel,
        aspectRatio,
      });
      setStoryboards((current) => [
        ...current.filter((item) => item.episodeNumber !== generated.episodeNumber),
        generated,
      ].sort((a, b) => a.episodeNumber - b.episodeNumber));
      setEditingGroup(null);
    } catch (generationError) {
      setError(
        generationError instanceof Error ? generationError.message : "分镜生成失败",
      );
    } finally {
      setGenerating(false);
    }
  }

  function startEditing(group: StoryboardGroup) {
    setEditingGroup(structuredClone(group));
    setError(null);
  }

  function updateEditingGroup<K extends keyof StoryboardGroup>(
    field: K,
    value: StoryboardGroup[K],
  ) {
    setEditingGroup((current) => current ? { ...current, [field]: value } : current);
  }

  function updateEditingSegment(
    segmentIndex: number,
    field: StoryboardSegmentTextField,
    value: string,
  ) {
    setEditingGroup((current) => {
      if (!current) return current;
      return {
        ...current,
        segments: current.segments.map((segment, index) => (
          index === segmentIndex ? { ...segment, [field]: value } : segment
        )),
      };
    });
  }

  async function handleSaveGroup() {
    if (!project || !selectedStoryboard || !editingGroup) return;
    setSavingEdit(true);
    setError(null);
    try {
      const nextStoryboard = {
        ...selectedStoryboard,
        groups: selectedStoryboard.groups.map((group) => (
          group.index === editingGroup.index ? editingGroup : group
        )),
      };
      const saved = await saveStoryboard(project.id, selectedEpisode, nextStoryboard);
      setStoryboards((current) => current.map((storyboard) => (
        storyboard.episodeNumber === saved.episodeNumber ? saved : storyboard
      )));
      setEditingGroup(null);
    } catch (saveError) {
      setError(saveError instanceof Error ? saveError.message : "分镜保存失败");
    } finally {
      setSavingEdit(false);
    }
  }

  if (!project) {
    return (
      <main className="source-empty">
        <Clapperboard size={30} />
        <h1>还没有可制作分镜的项目</h1>
        <p>先返回创作空间选择项目。</p>
        <button className="button secondary" type="button" onClick={onBack}>返回创作空间</button>
      </main>
    );
  }

  return (
    <main className="storyboard-page">
      <header className="storyboard-page-heading">
        <div>
          <button className="source-back" type="button" onClick={onBack}>
            <ArrowLeft size={16} /> 返回创作空间
          </button>
          <h1>工业级分镜工作台</h1>
          <p>{project.name} · 已确认剧本转时间码、表演、运镜与视频提示词</p>
        </div>
        <div className="storyboard-heading-status">
          <ShieldCheck size={17} />
          {screenplay?.status === "approved" ? "剧本已确认" : "等待剧本确认"}
        </div>
      </header>

      {error ? <div className="source-alert">{error}</div> : null}

      {loading ? (
        <section className="storyboard-loading"><LoaderCircle className="spinning" size={24} /> 正在读取分镜工程…</section>
      ) : screenplay?.status !== "approved" ? (
        <section className="storyboard-gate">
          <ShieldCheck size={28} />
          <div>
            <h2>分镜入口已锁定</h2>
            <p>只有时长与原著忠实度均通过、并人工确认的剧本才能进入分镜。</p>
          </div>
          <button className="button primary" type="button" onClick={onOpenScreenplay}>返回确认剧本</button>
        </section>
      ) : (
        <>
          <section className="storyboard-controls">
            <div className="storyboard-episode-tabs" aria-label="选择剧集">
              {screenplay.episodes.map((episode) => {
                const ready = storyboards.some(
                  (item) => item.episodeNumber === episode.episodeNumber && item.screenplayUpdatedAt === screenplay.updatedAt,
                );
                return (
                  <button
                    className={episode.episodeNumber === selectedEpisode ? "active" : ""}
                    key={episode.episodeNumber}
                    type="button"
                    onClick={() => {
                      setSelectedEpisode(episode.episodeNumber);
                      setEditingGroup(null);
                    }}
                  >
                    <span>第 {episode.episodeNumber} 集</span>
                    <strong>{episode.title}</strong>
                    <small>{episode.estimatedSeconds} 秒 {ready ? "· 已生成" : "· 待生成"}</small>
                  </button>
                );
              })}
            </div>
            <div className="storyboard-generate-panel">
              <label>
                <span>目标模型</span>
                <select value={targetModel} onChange={(event) => setTargetModel(event.target.value as StoryboardTargetModel)}>
                  {TARGET_MODELS.map((model) => <option key={model.value} value={model.value}>{model.label}</option>)}
                </select>
              </label>
              <label>
                <span>画幅</span>
                <select value={aspectRatio} onChange={(event) => setAspectRatio(event.target.value as StoryboardAspectRatio)}>
                  <option value="16:9">16:9 横屏</option>
                  <option value="9:16">9:16 竖屏</option>
                </select>
              </label>
              <button className="button primary" type="button" disabled={!canGenerate} onClick={handleGenerate}>
                {generating ? <LoaderCircle className="spinning" size={16} /> : selectedStoryboard ? <RefreshCw size={16} /> : <Sparkles size={16} />}
                {generating ? "正在编排分镜…" : selectedStoryboard ? "重新生成本集" : "生成本集分镜"}
              </button>
            </div>
          </section>

          {selectedStoryboard ? (
            <>
              <section className="storyboard-summary">
                <div><Clock3 size={17} /><span>总时长</span><strong>{selectedStoryboard.totalSeconds} 秒</strong></div>
                <div><Clapperboard size={17} /><span>镜头组</span><strong>{selectedStoryboard.groups.length} 组</strong></div>
                <div><CheckCircle2 size={17} /><span>结构校验</span><strong>{storyboardIsCurrent ? "已通过" : "剧本已更新"}</strong></div>
                <p>{selectedStoryboard.styleBible}</p>
              </section>

              <section className="storyboard-group-list">
                {selectedStoryboard.groups.map((group) => (
                  <article
                    className={editingGroup?.index === group.index ? "storyboard-group editing" : "storyboard-group"}
                    key={group.index}
                  >
                    <header>
                      <div className="storyboard-group-number">{String(group.index).padStart(2, "0")}</div>
                      <div>
                        <span>{timeLabel(group.startSeconds)}—{timeLabel(group.endSeconds)} · {group.durationSeconds} 秒 · 第 {group.sceneIndex} 场</span>
                        {editingGroup?.index === group.index ? (
                          <label className="storyboard-edit-field storyboard-edit-purpose">
                            <span>镜头组目标</span>
                            <textarea
                              value={editingGroup.purpose}
                              onChange={(event) => updateEditingGroup("purpose", event.target.value)}
                            />
                          </label>
                        ) : <h2>{group.purpose}</h2>}
                        <p>{group.metadata}</p>
                      </div>
                      <div className="storyboard-group-actions">
                        <em>{group.hookType}</em>
                        {editingGroup?.index === group.index ? (
                          <>
                            <button
                              className="storyboard-icon-action save"
                              type="button"
                              disabled={savingEdit}
                              onClick={handleSaveGroup}
                              aria-label={`保存第 ${group.index} 组`}
                            >
                              {savingEdit ? <LoaderCircle className="spinning" size={15} /> : <Save size={15} />}
                            </button>
                            <button
                              className="storyboard-icon-action"
                              type="button"
                              disabled={savingEdit}
                              onClick={() => setEditingGroup(null)}
                              aria-label={`取消编辑第 ${group.index} 组`}
                            >
                              <X size={15} />
                            </button>
                          </>
                        ) : (
                          <button
                            className="storyboard-icon-action"
                            type="button"
                            onClick={() => startEditing(group)}
                            aria-label={`编辑第 ${group.index} 组`}
                          >
                            <Pencil size={15} />
                          </button>
                        )}
                      </div>
                    </header>

                    <div className="storyboard-lock-grid">
                      <section>
                        <b>空间锁定</b>
                        {editingGroup?.index === group.index ? (
                          <textarea
                            value={editingGroup.spatialRelations}
                            onChange={(event) => updateEditingGroup("spatialRelations", event.target.value)}
                            aria-label="空间锁定"
                          />
                        ) : <p>{group.spatialRelations}</p>}
                      </section>
                      <section>
                        <b>首帧顺接</b>
                        {editingGroup?.index === group.index ? (
                          <textarea
                            value={editingGroup.firstFrameLock}
                            onChange={(event) => updateEditingGroup("firstFrameLock", event.target.value)}
                            aria-label="首帧顺接"
                          />
                        ) : <p>{group.firstFrameLock}</p>}
                      </section>
                      <section>
                        <b>情绪转折</b>
                        {editingGroup?.index === group.index ? (
                          <textarea
                            value={editingGroup.emotionalTurn}
                            onChange={(event) => updateEditingGroup("emotionalTurn", event.target.value)}
                            aria-label="情绪转折"
                          />
                        ) : <p>{group.emotionalTurn}</p>}
                      </section>
                    </div>

                    <div className="storyboard-segments">
                      {group.segments.map((segment, index) => (
                        <div className="storyboard-segment" key={`${group.index}-${index}`}>
                          <time>{segment.startSeconds}s—{segment.endSeconds}s</time>
                          {editingGroup?.index === group.index ? (
                            <>
                              <div className="storyboard-segment-edit-main">
                                {([
                                  ["camera", "镜头"],
                                  ["action", "动作"],
                                  ["motionVisual", "运动视觉"],
                                ] as const).map(([field, label]) => (
                                  <label className="storyboard-edit-field" key={field}>
                                    <span>{label}</span>
                                    <textarea
                                      value={editingGroup.segments[index][field]}
                                      onChange={(event) => updateEditingSegment(index, field, event.target.value)}
                                    />
                                  </label>
                                ))}
                              </div>
                              <div className="storyboard-segment-edit-detail">
                                {([
                                  ["expression", "表演"],
                                  ["environment", "环境"],
                                  ["effects", "特效"],
                                  ["sound", "声音"],
                                ] as const).map(([field, label]) => (
                                  <label className="storyboard-edit-field" key={field}>
                                    <span>{label}</span>
                                    <textarea
                                      value={editingGroup.segments[index][field]}
                                      onChange={(event) => updateEditingSegment(index, field, event.target.value)}
                                    />
                                  </label>
                                ))}
                              </div>
                            </>
                          ) : (
                            <>
                              <div>
                                <strong>{segment.camera}</strong>
                                <p>{segment.action}</p>
                                <small>{segment.motionVisual}</small>
                              </div>
                              <dl>
                                <div><dt>表演</dt><dd>{segment.expression}</dd></div>
                                <div><dt>环境</dt><dd>{segment.environment}</dd></div>
                                <div><dt>声音</dt><dd>{segment.sound}</dd></div>
                              </dl>
                            </>
                          )}
                        </div>
                      ))}
                    </div>

                    <footer>
                      {editingGroup?.index === group.index ? (
                        <>
                          <label className="storyboard-edit-field">
                            <span>镜头语言</span>
                            <textarea
                              value={editingGroup.cameraLanguage}
                              onChange={(event) => updateEditingGroup("cameraLanguage", event.target.value)}
                            />
                          </label>
                          <label className="storyboard-edit-field">
                            <span>可复制视频提示词</span>
                            <textarea
                              className="storyboard-prompt-input"
                              value={editingGroup.videoPrompt}
                              onChange={(event) => updateEditingGroup("videoPrompt", event.target.value)}
                            />
                          </label>
                          <label className="storyboard-edit-field storyboard-negative">
                            <span>负面约束</span>
                            <textarea
                              value={editingGroup.negativePrompt}
                              onChange={(event) => updateEditingGroup("negativePrompt", event.target.value)}
                            />
                          </label>
                        </>
                      ) : (
                        <>
                          <div><b>镜头语言</b><p>{group.cameraLanguage}</p></div>
                          <div><b>可复制视频提示词</b><p>{group.videoPrompt}</p></div>
                          <div className="storyboard-negative"><b>负面约束</b><p>{group.negativePrompt}</p></div>
                        </>
                      )}
                    </footer>
                  </article>
                ))}
              </section>
            </>
          ) : (
            <section className="storyboard-empty-state">
              <Sparkles size={28} />
              <h2>第 {selectedEpisode} 集还没有分镜</h2>
              <p>{selectedScreenplayEpisode?.estimatedSeconds} 秒剧本将自动拆成不超过 15 秒的连续镜头组。</p>
            </section>
          )}
        </>
      )}
    </main>
  );
}
