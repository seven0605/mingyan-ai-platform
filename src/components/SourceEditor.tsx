import { ArrowLeft, BrainCircuit, Check, FileText, FileUp, Save, ScrollText, WandSparkles } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import {
  analyzeProject,
  approveScreenplay,
  generateScreenplay,
  generateScriptPlan,
  getProjectAnalysis,
  getProjectSource,
  getScreenplay,
  getScriptPlan,
  refineScreenplayEpisode,
  saveScreenplay,
  saveProjectSource,
} from "../lib/api";
import type {
  Project,
  Screenplay,
  ScreenplayMode,
  ScriptPlan,
  SourceDocument,
  StoryAnalysis,
} from "../types";
import { ScreenplayPanel } from "./ScreenplayPanel";
import { ScriptPlanPanel } from "./ScriptPlanPanel";
import { StoryAnalysisPanel } from "./StoryAnalysisPanel";

interface SourceEditorProps {
  project?: Project;
  onBack: () => void;
  onCreateProject: () => void;
  onAdvanceToStoryboard: () => Promise<void>;
}

function formatCount(value: number) {
  return new Intl.NumberFormat("zh-CN").format(value);
}

export function SourceEditor({
  project,
  onBack,
  onCreateProject,
  onAdvanceToStoryboard,
}: SourceEditorProps) {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [title, setTitle] = useState("");
  const [content, setContent] = useState("");
  const [savedSource, setSavedSource] = useState<SourceDocument | null>(null);
  const [analysis, setAnalysis] = useState<StoryAnalysis | null>(null);
  const [scriptPlan, setScriptPlan] = useState<ScriptPlan | null>(null);
  const [screenplay, setScreenplay] = useState<Screenplay | null>(null);
  const [screenplayMode, setScreenplayMode] = useState<ScreenplayMode>("faithful");
  const [targetSeconds, setTargetSeconds] = useState<60 | 90 | 120 | 180>(120);
  const [episodeCount, setEpisodeCount] = useState(3);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [analyzing, setAnalyzing] = useState(false);
  const [generatingPlan, setGeneratingPlan] = useState(false);
  const [generatingScreenplay, setGeneratingScreenplay] = useState(false);
  const [savingScreenplay, setSavingScreenplay] = useState(false);
  const [approvingScreenplay, setApprovingScreenplay] = useState(false);
  const [refiningEpisode, setRefiningEpisode] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!project) {
      setTitle("");
      setContent("");
      setSavedSource(null);
      setAnalysis(null);
      setScriptPlan(null);
      setScreenplay(null);
      return;
    }

    let active = true;
    setLoading(true);
    setError(null);
    Promise.all([
      getProjectSource(project.id),
      getProjectAnalysis(project.id),
      getScriptPlan(project.id),
      getScreenplay(project.id),
    ])
      .then(([source, savedAnalysis, savedScriptPlan, savedScreenplay]) => {
        if (!active) return;
        setSavedSource(source);
        setAnalysis(savedAnalysis);
        setScriptPlan(savedScriptPlan);
        setScreenplay(savedScreenplay);
        if (savedScreenplay) {
          setScreenplayMode(savedScreenplay.adaptationMode);
          setTargetSeconds(savedScreenplay.targetSeconds as 60 | 90 | 120 | 180);
          setEpisodeCount(savedScreenplay.episodeCount);
        }
        setTitle(source?.title ?? project.name);
        setContent(source?.content ?? "");
      })
      .catch((loadError: unknown) => {
        if (!active) return;
        setError(loadError instanceof Error ? loadError.message : "原文加载失败");
      })
      .finally(() => {
        if (active) setLoading(false);
      });

    return () => {
      active = false;
    };
  }, [project]);

  if (!project) {
    return (
      <main className="source-empty">
        <ScrollText size={34} strokeWidth={1.5} />
        <h1>请先创建一个视频项目</h1>
        <p>原文会保存在对应项目中，之后可继续生成剧本和分镜。</p>
        <button className="button primary" type="button" onClick={onCreateProject}>
          新建项目
        </button>
      </main>
    );
  }

  const hasChanges = title !== (savedSource?.title ?? project.name) || content !== (savedSource?.content ?? "");
  const currentCharCount = content.length;
  const currentChapterCount = content.match(/^(?:第[^\n]{1,16}[章节回卷部]|楔子|序章|番外)\s*$/gm)?.length ?? 0;
  const analysisStale = Boolean(
    analysis && savedSource && analysis.sourceUpdatedAt !== savedSource.updatedAt,
  );
  const scriptPlanStale = Boolean(
    scriptPlan && savedSource && scriptPlan.sourceUpdatedAt !== savedSource.updatedAt,
  );
  const screenplayStale = Boolean(
    screenplay
      && savedSource
      && (
        screenplay.sourceUpdatedAt !== savedSource.updatedAt
        || screenplay.planUpdatedAt !== scriptPlan?.updatedAt
      ),
  );

  const importFile = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) return;
    setError(null);
    try {
      const text = await file.text();
      setTitle(file.name.replace(/\.txt$/i, ""));
      setContent(text);
    } catch {
      setError("无法读取这个文件，请确认它是 UTF-8 文本。 ");
    } finally {
      event.target.value = "";
    }
  };

  const save = async () => {
    if (!title.trim() || !content.trim()) return;
    setSaving(true);
    setError(null);
    try {
      const source = await saveProjectSource(project.id, title.trim(), content);
      setSavedSource(source);
      setTitle(source.title);
      setContent(source.content);
    } catch (saveError: unknown) {
      setError(saveError instanceof Error ? saveError.message : "原文保存失败");
    } finally {
      setSaving(false);
    }
  };

  const runAnalysis = async () => {
    if (!savedSource || hasChanges) return;
    setAnalyzing(true);
    setError(null);
    try {
      setAnalysis(await analyzeProject(project.id));
    } catch (analysisError: unknown) {
      setError(analysisError instanceof Error ? analysisError.message : "结构分析失败");
    } finally {
      setAnalyzing(false);
    }
  };

  const runScriptPlan = async () => {
    if (!savedSource || hasChanges) return;
    setGeneratingPlan(true);
    setError(null);
    try {
      setScriptPlan(await generateScriptPlan(project.id));
    } catch (planError: unknown) {
      setError(planError instanceof Error ? planError.message : "AI 剧本策划生成失败");
    } finally {
      setGeneratingPlan(false);
    }
  };

  const runScreenplay = async () => {
    if (!savedSource || hasChanges || !scriptPlan || scriptPlanStale) return;
    setGeneratingScreenplay(true);
    setError(null);
    try {
      setScreenplay(await generateScreenplay(project.id, {
        adaptationMode: screenplayMode,
        targetSeconds,
        episodeCount,
      }));
    } catch (screenplayError: unknown) {
      setError(screenplayError instanceof Error ? screenplayError.message : "逐场剧本生成失败");
    } finally {
      setGeneratingScreenplay(false);
    }
  };

  const saveScreenplayDraft = async (draft: Screenplay) => {
    setSavingScreenplay(true);
    setError(null);
    try {
      setScreenplay(await saveScreenplay(project.id, draft));
    } catch (saveError: unknown) {
      const error = saveError instanceof Error ? saveError : new Error("逐场剧本保存失败");
      setError(error.message);
      throw error;
    } finally {
      setSavingScreenplay(false);
    }
  };

  const approveCurrentScreenplay = async () => {
    setApprovingScreenplay(true);
    setError(null);
    try {
      setScreenplay(await approveScreenplay(project.id));
      await onAdvanceToStoryboard();
    } catch (approveError: unknown) {
      const error = approveError instanceof Error ? approveError : new Error("逐场剧本确认失败");
      setError(error.message);
      throw error;
    } finally {
      setApprovingScreenplay(false);
    }
  };

  const refineEpisode = async (episodeNumber: number) => {
    setRefiningEpisode(episodeNumber);
    setError(null);
    try {
      setScreenplay(await refineScreenplayEpisode(project.id, episodeNumber));
    } catch (refineError: unknown) {
      const error = refineError instanceof Error ? refineError : new Error("单集 AI 定稿失败");
      setError(error.message);
      throw error;
    } finally {
      setRefiningEpisode(null);
    }
  };

  return (
    <main className="source-editor-page">
      <header className="source-heading">
        <div>
          <button className="source-back" type="button" onClick={onBack}>
            <ArrowLeft size={16} /> 返回创作空间
          </button>
          <h1>原文与剧本</h1>
          <p>{project.name} · 原文导入与整理</p>
        </div>
        <div className="source-actions">
          <input
            ref={fileInputRef}
            className="visually-hidden"
            type="file"
            accept=".txt,text/plain"
            onChange={importFile}
          />
          <button className="button secondary" type="button" onClick={() => fileInputRef.current?.click()}>
            <FileUp size={17} /> 导入 TXT
          </button>
          <button
            className="button primary"
            type="button"
            disabled={!hasChanges || !title.trim() || !content.trim() || saving}
            onClick={save}
          >
            {saving ? <Save size={17} /> : <Check size={17} />}
            {saving ? "正在保存…" : hasChanges ? "保存原文" : "已保存"}
          </button>
        </div>
      </header>

      {error ? <div className="service-alert source-alert" role="alert">{error}</div> : null}

      <div className="source-layout">
        <section className="source-document" aria-label="原文编辑器">
          <label className="source-title-field">
            <span>原文标题</span>
            <input value={title} onChange={(event) => setTitle(event.target.value)} disabled={loading} />
          </label>
          <textarea
            className="source-textarea"
            aria-label="原文内容"
            value={content}
            onChange={(event) => setContent(event.target.value)}
            disabled={loading}
            placeholder={loading ? "正在加载原文…" : "导入 TXT 文件，或在这里粘贴小说原文。"}
            spellCheck={false}
          />
        </section>

        <aside className="source-inspector">
          <h2>文本概览</h2>
          <div className="source-stat">
            <span>字符数</span>
            <strong>{formatCount(currentCharCount)}</strong>
          </div>
          <div className="source-stat">
            <span>识别章节</span>
            <strong>{currentChapterCount} 章</strong>
          </div>
          <div className="source-stat">
            <span>保存状态</span>
            <strong className={hasChanges ? "status-pending" : "status-saved"}>
              {hasChanges ? "有未保存修改" : "已保存到本机"}
            </strong>
          </div>
          <div className="source-next-step">
            <BrainCircuit size={19} />
            <div>
              <strong>本地结构初筛</strong>
              <p>提取人物、场景和章节锚点；正文不会离开这台电脑。</p>
              <button
                className="analysis-run-button"
                type="button"
                disabled={!savedSource || hasChanges || analyzing}
                onClick={runAnalysis}
              >
                {analyzing ? "正在分析…" : analysis ? "重新分析" : "开始分析"}
              </button>
            </div>
          </div>
          <div className="source-next-step script-generation-step">
            <WandSparkles size={19} />
            <div>
              <strong>AI 剧本策划</strong>
              <p>把已保存原文发送给配置的文本模型，生成人物关系、场次和改编建议。</p>
              <button
                className="analysis-run-button"
                type="button"
                disabled={!savedSource || hasChanges || generatingPlan}
                onClick={runScriptPlan}
              >
                {generatingPlan ? "正在生成，请稍候…" : scriptPlan ? "重新生成策划" : "生成剧本策划"}
              </button>
            </div>
          </div>
          <div className="source-next-step screenplay-generation-step">
            <FileText size={19} />
            <div>
              <strong>逐场剧本</strong>
              <p>按所选模式和时长生成完整场景、动作、对白、原文依据与连续性记录。</p>
              <div className="screenplay-config-grid">
                <label>
                  <span>改编模式</span>
                  <select
                    value={screenplayMode}
                    onChange={(event) => setScreenplayMode(event.target.value as ScreenplayMode)}
                  >
                    <option value="faithful">忠实改编</option>
                    <option value="commercial">商业短剧强化</option>
                  </select>
                </label>
                <label>
                  <span>单集时长</span>
                  <select
                    value={targetSeconds}
                    onChange={(event) => setTargetSeconds(Number(event.target.value) as 60 | 90 | 120 | 180)}
                  >
                    <option value={60}>60 秒</option>
                    <option value={90}>90 秒</option>
                    <option value={120}>120 秒</option>
                    <option value={180}>180 秒</option>
                  </select>
                </label>
                <label>
                  <span>分集数量</span>
                  <select value={episodeCount} onChange={(event) => setEpisodeCount(Number(event.target.value))}>
                    {[1, 2, 3, 4, 5].map((value) => <option value={value} key={value}>{value} 集</option>)}
                  </select>
                </label>
              </div>
              <button
                className="analysis-run-button"
                type="button"
                disabled={!savedSource || hasChanges || !scriptPlan || scriptPlanStale || generatingScreenplay}
                onClick={runScreenplay}
              >
                {generatingScreenplay ? "正在生成完整剧本…" : screenplay ? "重新生成逐场剧本" : "生成逐场剧本"}
              </button>
              {!scriptPlan || scriptPlanStale ? <small>请先生成与当前原文一致的 AI 剧本策划。</small> : null}
            </div>
          </div>
        </aside>
      </div>

      {analysis ? <StoryAnalysisPanel analysis={analysis} stale={analysisStale} /> : null}
      {scriptPlan ? <ScriptPlanPanel plan={scriptPlan} stale={scriptPlanStale} /> : null}
      {screenplay ? (
        <ScreenplayPanel
          key={screenplay.updatedAt}
          screenplay={screenplay}
          stale={screenplayStale}
          saving={savingScreenplay}
          approving={approvingScreenplay}
          refiningEpisode={refiningEpisode}
          onSave={saveScreenplayDraft}
          onApprove={approveCurrentScreenplay}
          onRefineEpisode={refineEpisode}
        />
      ) : null}
    </main>
  );
}
