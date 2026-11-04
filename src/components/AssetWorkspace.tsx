import {
  ArrowLeft,
  Boxes,
  BookOpenText,
  Calculator,
  Check,
  CheckCircle2,
  Crown,
  Cuboid,
  Image as ImageIcon,
  ImageOff,
  ListChecks,
  LoaderCircle,
  Map,
  Palette,
  RefreshCw,
  Save,
  ShieldCheck,
  Sparkles,
  UserRound,
  X,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import {
  confirmAssetBatchPlan,
  extractAssetLibrary,
  generateAssetReferenceImage,
  getAssetBatchPlan,
  getAssetLibrary,
  getProjectTasks,
  getScreenplay,
  getStoryboards,
  queueAssetBatchPlan,
  saveAssetLibrary,
  setPrimaryAssetReferenceImage,
} from "../lib/api";
import {
  assetAspectRatio,
  assetStandardSignature,
  COSTUME_ERA_OPTIONS,
  DEFAULT_ASSET_STANDARD,
  VISUAL_STANDARD_OPTIONS,
} from "../lib/assetStandards";
import {
  compileAssetPrompt,
  type CompiledAssetPrompt,
} from "../lib/assetPromptCompiler";
import type {
  AssetBatchPlan,
  AssetItem,
  AssetKind,
  AssetLibrary,
  AssetVisualStandard,
  CostumeEra,
  Project,
  ProjectTask,
  Screenplay,
  Storyboard,
} from "../types";

interface AssetWorkspaceProps {
  project: Project | null;
  onBack: () => void;
  onOpenScreenplay: () => void;
  onOpenApiSettings: () => void;
  onAssetsReady: () => Promise<void>;
  imageModelConfigured: boolean;
}

const KIND_META: Record<AssetKind, { label: string; icon: typeof UserRound }> = {
  character: { label: "角色", icon: UserRound },
  scene: { label: "场景", icon: Map },
  prop: { label: "物品", icon: Cuboid },
};

function latestStoryboardTime(storyboards: Storyboard[]) {
  return storyboards.reduce<string | null>(
    (latest, item) => (!latest || item.updatedAt > latest ? item.updatedAt : latest),
    null,
  );
}

function itemReady(item: AssetItem) {
  return Boolean(
    item.description.trim()
    && item.visualAnchor.trim()
    && item.continuityNotes.trim()
    && item.referencePrompt.trim(),
  );
}

function promptUsesCurrentStandard(item: AssetItem, settings: AssetLibrary["standard"]) {
  return item.promptStandardSignature === assetStandardSignature(settings);
}

function editableLibrarySignature(library: AssetLibrary | null) {
  return JSON.stringify(library ? {
    items: library.items,
    standard: library.standard ?? DEFAULT_ASSET_STANDARD,
  } : null);
}

function formatCost(value: number) {
  return value.toLocaleString("zh-CN", { maximumFractionDigits: 4 });
}

export function AssetWorkspace({
  project,
  onBack,
  onOpenScreenplay,
  onOpenApiSettings,
  onAssetsReady,
  imageModelConfigured,
}: AssetWorkspaceProps) {
  const [screenplay, setScreenplay] = useState<Screenplay | null>(null);
  const [storyboards, setStoryboards] = useState<Storyboard[]>([]);
  const [library, setLibrary] = useState<AssetLibrary | null>(null);
  const [savedSignature, setSavedSignature] = useState("");
  const [kind, setKind] = useState<AssetKind>("character");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [extracting, setExtracting] = useState(false);
  const [saving, setSaving] = useState(false);
  const [generatingId, setGeneratingId] = useState<string | null>(null);
  const [previewImageId, setPreviewImageId] = useState<string | null>(null);
  const [lightboxOpen, setLightboxOpen] = useState(false);
  const [settingPrimary, setSettingPrimary] = useState(false);
  const [promptPreview, setPromptPreview] = useState<{
    assetId: string;
    compiled: CompiledAssetPrompt;
  } | null>(null);
  const [batchPlan, setBatchPlan] = useState<AssetBatchPlan | null>(null);
  const [batchTasks, setBatchTasks] = useState<ProjectTask[]>([]);
  const [batchOpen, setBatchOpen] = useState(false);
  const [batchSelectedIds, setBatchSelectedIds] = useState<string[]>([]);
  const [batchReviewId, setBatchReviewId] = useState<string | null>(null);
  const [batchReviewedIds, setBatchReviewedIds] = useState<string[]>([]);
  const [batchAcknowledged, setBatchAcknowledged] = useState(false);
  const [batchSaving, setBatchSaving] = useState(false);
  const [batchQueueing, setBatchQueueing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!project) {
      setLoading(false);
      setScreenplay(null);
      setStoryboards([]);
      setLibrary(null);
      setBatchPlan(null);
      setBatchTasks([]);
      return;
    }
    let active = true;
    setLoading(true);
    setError(null);
    Promise.all([
      getScreenplay(project.id),
      getStoryboards(project.id),
      getAssetLibrary(project.id),
      getAssetBatchPlan(project.id),
      getProjectTasks(project.id),
    ])
      .then(([screenplayResult, storyboardResult, libraryResult, batchPlanResult, taskResult]) => {
        if (!active) return;
        setScreenplay(screenplayResult);
        setStoryboards(storyboardResult);
        setLibrary(libraryResult);
        setSavedSignature(editableLibrarySignature(libraryResult));
        setSelectedId(libraryResult?.items[0]?.id ?? null);
        setBatchPlan(batchPlanResult);
        setBatchTasks(taskResult);
      })
      .catch((loadError: unknown) => {
        if (active) {
          setError(loadError instanceof Error ? loadError.message : "资产工作台读取失败");
        }
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [project]);

  const currentStoryboardUpdatedAt = useMemo(
    () => latestStoryboardTime(storyboards),
    [storyboards],
  );
  const filteredItems = useMemo(
    () => library?.items.filter((item) => item.kind === kind) ?? [],
    [kind, library],
  );
  const selectedItem = filteredItems.find((item) => item.id === selectedId) ?? filteredItems[0] ?? null;
  const primaryImage = selectedItem?.referenceImages.find(
    (image) => image.id === selectedItem.primaryReferenceImageId,
  ) ?? selectedItem?.referenceImages[0] ?? null;
  const previewImage = selectedItem?.referenceImages.find(
    (image) => image.id === previewImageId,
  ) ?? primaryImage;
  const previewVersion = previewImage
    ? (selectedItem?.referenceImages.findIndex((image) => image.id === previewImage.id) ?? -1) + 1
    : 0;
  const dirty = Boolean(library && editableLibrarySignature(library) !== savedSignature);
  const activeStandard = library?.standard ?? DEFAULT_ASSET_STANDARD;
  const selectedStandard = VISUAL_STANDARD_OPTIONS.find(
    (option) => option.id === activeStandard.visualStandard,
  ) ?? VISUAL_STANDARD_OPTIONS[0];
  const selectedCostumeEra = COSTUME_ERA_OPTIONS.find(
    (option) => option.id === activeStandard.costumeEra,
  ) ?? COSTUME_ERA_OPTIONS[0];
  const confirmedCount = library?.items.filter((item) => item.status === "confirmed").length ?? 0;
  const generatedCount = library?.items.filter((item) => item.referenceImages.length > 0).length ?? 0;
  const stalePromptCount = library?.items.filter(
    (item) => !promptUsesCurrentStandard(item, activeStandard),
  ).length ?? 0;
  const eligibleBatchItems = useMemo(
    () => library?.items.filter((item) => (
      item.status === "confirmed"
      && itemReady(item)
      && promptUsesCurrentStandard(item, activeStandard)
    )) ?? [],
    [activeStandard, library],
  );
  const selectedBatchItems = useMemo(() => {
    const selected = new Set(batchSelectedIds);
    return library?.items.filter((item) => selected.has(item.id)) ?? [];
  }, [batchSelectedIds, library]);
  const batchReviewItem = library?.items.find((item) => item.id === batchReviewId) ?? selectedBatchItems[0] ?? null;
  const batchCostSamples = useMemo(
    () => library?.items.flatMap((item) => item.referenceImages)
      .map((image) => image.cost)
      .filter((cost): cost is number => cost !== null) ?? [],
    [library],
  );
  const estimatedUnitCost = batchCostSamples.length
    ? batchCostSamples.reduce((total, cost) => total + cost, 0) / batchCostSamples.length
    : null;
  const estimatedTotalCost = estimatedUnitCost === null
    ? null
    : estimatedUnitCost * selectedBatchItems.length;
  const reviewedSet = useMemo(() => new Set(batchReviewedIds), [batchReviewedIds]);
  const allSelectedReviewed = selectedBatchItems.length > 0
    && selectedBatchItems.every((item) => reviewedSet.has(item.id));
  const batchSelectionMatchesPlan = Boolean(
    batchPlan?.current
    && batchPlan.items.length === selectedBatchItems.length
    && batchPlan.items.every((item) => batchSelectedIds.includes(item.assetId)),
  );
  const latestBatchId = batchTasks.find((task) => task.batchId)?.batchId;
  const latestBatchTasks = latestBatchId
    ? batchTasks.filter((task) => task.batchId === latestBatchId)
    : [];
  const latestBatchCompleted = latestBatchTasks.filter((task) => task.status === "completed").length;
  const latestBatchActive = latestBatchTasks.filter((task) => task.status === "queued" || task.status === "running").length;
  const latestBatchNeedsAction = latestBatchTasks.length - latestBatchCompleted - latestBatchActive;
  const libraryCurrent = Boolean(
    library
    && screenplay
    && library.screenplayUpdatedAt === screenplay.updatedAt
    && library.storyboardUpdatedAt === currentStoryboardUpdatedAt,
  );

  const handleExtract = async () => {
    if (!project) return;
    setExtracting(true);
    setError(null);
    try {
      const result = await extractAssetLibrary(project.id);
      setLibrary(result);
      setSavedSignature(editableLibrarySignature(result));
      const firstCharacter = result.items.find((item) => item.kind === "character");
      setKind(firstCharacter?.kind ?? result.items[0]?.kind ?? "character");
      setSelectedId(firstCharacter?.id ?? result.items[0]?.id ?? null);
      setBatchPlan((current) => current ? { ...current, current: false } : current);
      await onAssetsReady();
    } catch (extractError) {
      setError(extractError instanceof Error ? extractError.message : "资产整理失败");
    } finally {
      setExtracting(false);
    }
  };

  const updateSelected = (field: keyof AssetItem, value: string) => {
    if (!selectedItem) return;
    setPromptPreview(null);
    setLibrary((current) => current ? {
      ...current,
      items: current.items.map((item) => (
        item.id === selectedItem.id
          ? {
              ...item,
              [field]: value,
              ...(["description", "visualAnchor", "continuityNotes", "referencePrompt"].includes(field)
                ? { promptStandardSignature: "" }
                : {}),
            }
          : item
      )),
    } : current);
  };

  const updateStandard = (
    field: "visualStandard" | "costumeEra",
    value: AssetVisualStandard | CostumeEra,
  ) => {
    setPromptPreview(null);
    setLibrary((current) => current ? {
      ...current,
      standard: { ...(current.standard ?? DEFAULT_ASSET_STANDARD), [field]: value },
    } : current);
    setError(null);
  };

  const handlePreviewPrompt = () => {
    if (!selectedItem) return;
    setError(null);
    setPromptPreview({
      assetId: selectedItem.id,
      compiled: compileAssetPrompt(selectedItem, activeStandard),
    });
  };

  const handleApplyPrompt = () => {
    if (!selectedItem || promptPreview?.assetId !== selectedItem.id) return;
    setLibrary((current) => current ? {
      ...current,
      items: current.items.map((item) => (
        item.id === selectedItem.id
          ? {
              ...item,
              referencePrompt: promptPreview.compiled.prompt,
              promptStandardSignature: assetStandardSignature(activeStandard),
              status: "draft",
            }
          : item
      )),
    } : current);
    setPromptPreview(null);
    setError(null);
  };

  const handleApplyAllPrompts = () => {
    if (!library || !stalePromptCount) return;
    const signature = assetStandardSignature(activeStandard);
    setLibrary({
      ...library,
      items: library.items.map((item) => ({
        ...item,
        referencePrompt: compileAssetPrompt(item, activeStandard).prompt,
        promptStandardSignature: signature,
        status: "draft",
      })),
    });
    setPromptPreview(null);
    setBatchPlan((current) => current ? { ...current, current: false } : current);
    setError(null);
  };

  const toggleConfirmation = () => {
    if (!selectedItem) return;
    if (selectedItem.status === "draft") {
      if (!itemReady(selectedItem)) {
        setError("请先补全说明、视觉锚点、连续性约束和生图提示词，再确认资产");
        return;
      }
      if (!promptUsesCurrentStandard(selectedItem, activeStandard)) {
        setError("请先预览并应用当前资产标准生成的完整提示词，再确认资产");
        return;
      }
    }
    setError(null);
    updateSelected(
      "status",
      selectedItem.status === "confirmed" ? "draft" : "confirmed",
    );
  };

  const handleSave = async () => {
    if (!project || !library) return;
    setSaving(true);
    setError(null);
    try {
      const result = await saveAssetLibrary(project.id, library);
      setLibrary(result);
      setSavedSignature(editableLibrarySignature(result));
      setBatchPlan((current) => current ? { ...current, current: false } : current);
    } catch (saveError) {
      setError(saveError instanceof Error ? saveError.message : "资产保存失败");
    } finally {
      setSaving(false);
    }
  };

  const handleGenerate = async () => {
    if (!project || !selectedItem) return;
    if (!imageModelConfigured) {
      setError("请先在 API 设置中配置并测试图像生成模型");
      return;
    }
    if (dirty) {
      setError("生图前请先保存当前资产文字修改");
      return;
    }
    if (selectedItem.status !== "confirmed") {
      setError("请先确认资产文字规范再生成参考图");
      return;
    }
    setGeneratingId(selectedItem.id);
    setError(null);
    try {
      const result = await generateAssetReferenceImage(project.id, selectedItem.id);
      setLibrary(result);
      setSavedSignature(editableLibrarySignature(result));
      setBatchPlan((current) => current ? { ...current, current: false } : current);
      const updatedItem = result.items.find((item) => item.id === selectedItem.id);
      setPreviewImageId(updatedItem?.referenceImages[updatedItem.referenceImages.length - 1]?.id ?? null);
    } catch (generationError) {
      setError(generationError instanceof Error ? generationError.message : "参考图生成失败");
    } finally {
      setGeneratingId(null);
    }
  };

  const handleSetPrimary = async () => {
    if (!project || !selectedItem || !previewImage) return;
    if (dirty) {
      setError("请先保存资产文字修改，再切换主参考图");
      return;
    }
    setSettingPrimary(true);
    setError(null);
    try {
      const result = await setPrimaryAssetReferenceImage(
        project.id,
        selectedItem.id,
        previewImage.id,
      );
      setLibrary(result);
      setSavedSignature(editableLibrarySignature(result));
      setBatchPlan((current) => current ? { ...current, current: false } : current);
    } catch (primaryError) {
      setError(primaryError instanceof Error ? primaryError.message : "主参考图设置失败");
    } finally {
      setSettingPrimary(false);
    }
  };

  const openBatchPlan = () => {
    if (dirty) {
      setError("请先保存当前资产修改，再建立批量生产清单");
      return;
    }
    const savedIds = batchPlan?.current
      ? batchPlan.items.map((item) => item.assetId).filter((id) => eligibleBatchItems.some((item) => item.id === id))
      : [];
    const defaultIds = eligibleBatchItems
      .filter((item) => item.referenceImages.length === 0)
      .map((item) => item.id);
    const nextIds = savedIds.length ? savedIds : (defaultIds.length ? defaultIds : eligibleBatchItems.map((item) => item.id));
    setBatchSelectedIds(nextIds);
    setBatchReviewedIds(savedIds);
    setBatchReviewId(nextIds[0] ?? eligibleBatchItems[0]?.id ?? library?.items[0]?.id ?? null);
    setBatchAcknowledged(false);
    setBatchOpen(true);
    setError(null);
  };

  const toggleBatchSelection = (assetId: string) => {
    setBatchSelectedIds((current) => current.includes(assetId)
      ? current.filter((id) => id !== assetId)
      : [...current, assetId]);
    setBatchAcknowledged(false);
  };

  const selectBatchItems = (items: AssetItem[]) => {
    setBatchSelectedIds(items.map((item) => item.id));
    setBatchReviewId(items[0]?.id ?? null);
    setBatchAcknowledged(false);
  };

  const handleConfirmBatchPlan = async () => {
    if (!project || !selectedBatchItems.length || !allSelectedReviewed || !batchAcknowledged) return;
    setBatchSaving(true);
    setError(null);
    try {
      const result = await confirmAssetBatchPlan(project.id, selectedBatchItems.map((item) => item.id));
      setBatchPlan(result);
      setBatchSelectedIds(result.items.map((item) => item.assetId));
      setBatchReviewedIds(result.items.map((item) => item.assetId));
      setBatchAcknowledged(false);
    } catch (batchError) {
      setError(batchError instanceof Error ? batchError.message : "批量生产清单保存失败");
    } finally {
      setBatchSaving(false);
    }
  };

  const handleQueueBatchPlan = async () => {
    if (!project || !batchSelectionMatchesPlan || !batchAcknowledged) return;
    setBatchQueueing(true);
    setError(null);
    try {
      const queuedTasks = await queueAssetBatchPlan(project.id);
      setBatchTasks((current) => [...queuedTasks, ...current]);
      setBatchAcknowledged(false);
      setBatchOpen(false);
    } catch (queueError) {
      setError(queueError instanceof Error ? queueError.message : "生成队列创建失败");
    } finally {
      setBatchQueueing(false);
    }
  };

  return (
    <main className="asset-page">
      <header className="asset-page-heading">
        <div>
          <button className="text-action" type="button" onClick={onBack}>
            <ArrowLeft size={15} /> 返回创作空间
          </button>
          <h1>一致性资产工作台</h1>
          <p>{project?.name ?? "未选择项目"} · 从已确认剧本整理角色、场景与物品视觉规范</p>
        </div>
        <div className={`asset-page-status ${screenplay?.status === "approved" ? "ready" : ""}`}>
          <CheckCircle2 size={16} />
          {screenplay?.status === "approved" ? "剧本已确认" : "等待剧本确认"}
        </div>
      </header>

      {loading ? (
        <section className="asset-gate"><LoaderCircle className="spinning" size={24} /> 正在读取资产工程…</section>
      ) : !project ? (
        <section className="asset-gate">
          <Boxes size={30} />
          <h2>请先选择项目</h2>
          <p>资产库会按项目分别保存在本机。</p>
        </section>
      ) : screenplay?.status !== "approved" ? (
        <section className="asset-gate">
          <Boxes size={30} />
          <h2>需要已确认剧本</h2>
          <p>角色、场景和物品必须以人工确认后的剧本为权威来源。</p>
          <button className="button primary" type="button" onClick={onOpenScreenplay}>返回确认剧本</button>
        </section>
      ) : !library ? (
        <section className="asset-gate asset-empty">
          <Sparkles size={32} />
          <h2>建立第一版一致性资产库</h2>
          <p>本步骤只整理剧本和现有分镜中的资产信息，不调用生图接口，也不会消耗图片额度。</p>
          <button className="button primary" type="button" disabled={extracting} onClick={handleExtract}>
            {extracting ? <LoaderCircle className="spinning" size={17} /> : <Boxes size={17} />}
            {extracting ? "正在整理…" : "从剧本整理资产"}
          </button>
          {error ? <div className="form-error">{error}</div> : null}
        </section>
      ) : (
        <>
          <section className="asset-toolbar">
            <div className="asset-kind-tabs" role="tablist" aria-label="资产类型">
              {(Object.entries(KIND_META) as [AssetKind, (typeof KIND_META)[AssetKind]][]).map(([id, meta]) => {
                const Icon = meta.icon;
                const count = library.items.filter((item) => item.kind === id).length;
                return (
                  <button
                    className={kind === id ? "active" : ""}
                    type="button"
                    role="tab"
                    aria-selected={kind === id}
                    onClick={() => {
                      setKind(id);
                      setSelectedId(library.items.find((item) => item.kind === id)?.id ?? null);
                      setPromptPreview(null);
                      setPreviewImageId(null);
                      setLightboxOpen(false);
                    }}
                    key={id}
                  >
                    <Icon size={16} /> {meta.label}<span>{count}</span>
                  </button>
                );
              })}
            </div>
            <div className="asset-toolbar-actions">
              <span className={libraryCurrent ? "asset-version current" : "asset-version stale"}>
                {libraryCurrent ? "与当前剧本/分镜同步" : "剧本或分镜已变化，请重新整理"}
              </span>
              <button className="button secondary compact" type="button" disabled={extracting || dirty} onClick={handleExtract}>
                {extracting ? <LoaderCircle className="spinning" size={15} /> : <RefreshCw size={15} />}
                重新整理
              </button>
              <button
                className="button secondary compact"
                type="button"
                disabled={!stalePromptCount}
                onClick={handleApplyAllPrompts}
                title="按当前视觉标准和朝代重编人物、场景与物品提示词；所有资产会恢复为待确认"
              >
                <Sparkles size={15} />
                {stalePromptCount ? `重编全部提示词 ${stalePromptCount}` : "提示词已是当前标准"}
              </button>
              <button
                className="button secondary compact"
                type="button"
                disabled={dirty || !eligibleBatchItems.length}
                onClick={openBatchPlan}
                title={dirty ? "请先保存资产修改" : "只保存生产清单，不会立即生成图片"}
              >
                <ListChecks size={15} />
                {batchPlan?.current ? `生产清单 ${batchPlan.items.length}` : "批量生产预检"}
              </button>
              <button className="button primary compact" type="button" disabled={!dirty || saving} onClick={handleSave}>
                {saving ? <LoaderCircle className="spinning" size={15} /> : <Save size={15} />}
                {saving ? "保存中" : "保存资产"}
              </button>
            </div>
          </section>

          <section className="asset-standard-panel" aria-labelledby="asset-standard-title">
            <header>
              <div>
                <Palette size={18} />
                <div>
                  <h2 id="asset-standard-title">资产生成标准</h2>
                  <p>视觉风格与历史服饰分层保存，后续可据此编译角色、场景和物品提示词。</p>
                </div>
              </div>
              <span>项目级配置</span>
            </header>
            <div className="asset-standard-options" role="radiogroup" aria-label="视觉资产标准">
              {VISUAL_STANDARD_OPTIONS.map((option) => (
                <button
                  className={option.id === activeStandard.visualStandard ? "active" : ""}
                  type="button"
                  role="radio"
                  aria-checked={option.id === activeStandard.visualStandard}
                  onClick={() => updateStandard("visualStandard", option.id)}
                  key={option.id}
                >
                  <strong>{option.shortLabel}</strong>
                  <span>{option.id === activeStandard.visualStandard ? "已选择" : "选择"}</span>
                </button>
              ))}
            </div>
            <div className="asset-standard-detail">
              <div className="asset-standard-description">
                <strong>{selectedStandard.label}</strong>
                <p>{selectedStandard.summary}</p>
                <small>{selectedStandard.layout}</small>
              </div>
              {selectedStandard.compatibleWithChineseCostume ? (
                <label className="asset-costume-selector">
                  <span><BookOpenText size={15} /> 中国古代服饰知识</span>
                  <select
                    value={activeStandard.costumeEra}
                    onChange={(event) => updateStandard("costumeEra", event.target.value as CostumeEra)}
                  >
                    {COSTUME_ERA_OPTIONS.map((option) => (
                      <option value={option.id} key={option.id}>{option.label}</option>
                    ))}
                  </select>
                  <small className={`asset-costume-coverage ${selectedCostumeEra.detail}`}>
                    {selectedCostumeEra.detail === "detailed"
                      ? "精细规则：含形制、阶级、配色、面料、头饰、配饰与禁忌。"
                      : selectedCostumeEra.detail === "foundation"
                        ? "基础占位：原资料未提供同等级完整字典，正式生成前需要继续补充。"
                        : "尚未指定朝代；不会自动套用具体朝代服饰。"}
                  </small>
                </label>
              ) : (
                <div className="asset-costume-independent">
                  <BookOpenText size={16} />
                  <p>该标准使用独立的西方时代规则，不叠加中国古代服饰知识。</p>
                </div>
              )}
            </div>
            <footer>切换标准只修改项目配置，不会改写现有资产提示词、确认状态或参考图；点击“保存资产”后生效。</footer>
          </section>

          <section className="asset-summary">
            <div><span>资产总数</span><strong>{library.items.length}</strong></div>
            <div><span>已确认</span><strong>{confirmedCount}</strong></div>
            <div><span>待完善</span><strong>{library.items.length - confirmedCount}</strong></div>
            <div><span>已有参考图</span><strong>{generatedCount}</strong></div>
            <p>
              {latestBatchTasks.length
                ? `最近批次 ${latestBatchTasks.length} 项：已完成 ${latestBatchCompleted}，执行中 ${latestBatchActive}，待处理 ${latestBatchNeedsAction}。`
                : batchPlan?.current
                ? `已确认 ${batchPlan.items.length} 项生产清单；当前阶段尚未排队或消耗额度。`
                : batchPlan
                  ? "已有生产清单因资产发生变化而过期，请重新审查确认。"
                  : imageModelConfigured
                    ? "图像模型已连接；可先建立批量生产清单，审查不会消耗额度。"
                    : "图像模型尚未配置，请先前往 API 设置。"}
            </p>
          </section>

          {error ? <div className="form-error asset-error">{error}</div> : null}

          <section className="asset-workspace">
            <aside className="asset-catalog" aria-label={`${KIND_META[kind].label}资产列表`}>
              <header>
                <h2>{KIND_META[kind].label}资产</h2>
                <span>{filteredItems.length} 项</span>
              </header>
              <div className="asset-catalog-list">
                {filteredItems.map((item) => {
                  const Icon = KIND_META[item.kind].icon;
                  const active = selectedItem?.id === item.id;
                  return (
                    <button
                      className={active ? "asset-catalog-item active" : "asset-catalog-item"}
                      type="button"
                      onClick={() => {
                        setSelectedId(item.id);
                        setPromptPreview(null);
                        setPreviewImageId(null);
                        setLightboxOpen(false);
                      }}
                      key={item.id}
                    >
                      <span className="asset-catalog-icon"><Icon size={18} /></span>
                      <span><strong>{item.name}</strong><small>{item.appearances.length} 个出现场次</small></span>
                      {item.status === "confirmed" ? <Check size={15} className="confirmed" /> : <span className="draft-dot" />}
                    </button>
                  );
                })}
              </div>
            </aside>

            {selectedItem ? (
              <article className="asset-editor">
                <header>
                  <div>
                    <span>{KIND_META[selectedItem.kind].label}资产</span>
                    <h2>{selectedItem.name}</h2>
                  </div>
                  <button
                    className={selectedItem.status === "confirmed" ? "asset-confirm confirmed" : "asset-confirm"}
                    type="button"
                    onClick={toggleConfirmation}
                  >
                    <CheckCircle2 size={16} />
                    {selectedItem.status === "confirmed" ? "已确认" : "确认资产"}
                  </button>
                </header>

                <div className="asset-source-strip">
                  <span>出现场次</span>
                  <p>{selectedItem.appearances.join("、") || "暂无"}</p>
                  <span>原文依据</span>
                  <p>{selectedItem.sourceRefs.join("、") || "暂无"}</p>
                </div>

                <div className="asset-editor-grid">
                  <label>
                    <span>剧本说明</span>
                    <textarea value={selectedItem.description} onChange={(event) => updateSelected("description", event.target.value)} />
                  </label>
                  <label>
                    <span>视觉锚点</span>
                    <textarea value={selectedItem.visualAnchor} onChange={(event) => updateSelected("visualAnchor", event.target.value)} placeholder="例如：年龄、脸型、发型、服装层级、材质、标志性细节" />
                  </label>
                  <label>
                    <span>连续性约束</span>
                    <textarea value={selectedItem.continuityNotes} onChange={(event) => updateSelected("continuityNotes", event.target.value)} />
                  </label>
                  <div className="asset-prompt-field">
                    <div className="asset-prompt-heading">
                      <label htmlFor={`asset-prompt-${selectedItem.id}`}>生图基础提示词</label>
                      <span>{promptUsesCurrentStandard(selectedItem, activeStandard) ? "已按当前标准编译" : "待按当前标准重编"}</span>
                      <button type="button" onClick={handlePreviewPrompt}>
                        <Sparkles size={14} /> 预览标准化提示词
                      </button>
                    </div>
                    <textarea
                      id={`asset-prompt-${selectedItem.id}`}
                      value={selectedItem.referencePrompt}
                      onChange={(event) => updateSelected("referencePrompt", event.target.value)}
                    />
                  </div>
                </div>

                <footer className="asset-generation-state">
                  {previewImage ? (
                    <button
                      className="asset-reference-preview"
                      type="button"
                      aria-label={`打开${selectedItem.name}参考图版本 ${previewVersion} 大图预览`}
                      onClick={() => setLightboxOpen(true)}
                    >
                      <img src={previewImage.url} alt={`${selectedItem.name}参考图版本 ${previewVersion}`} />
                      <span className={previewImage.id === primaryImage?.id ? "primary" : ""}>
                        {previewImage.id === primaryImage?.id ? "主参考图" : `版本 V${previewVersion}`}
                      </span>
                    </button>
                  ) : (
                    <div className="asset-image-placeholder"><ImageOff size={24} /></div>
                  )}
                  <div className="asset-generation-copy">
                    <strong>{previewImage ? `参考图版本 V${previewVersion}` : "参考图尚未生成"}</strong>
                    {previewImage ? (
                      <p>
                        {selectedItem.referenceImages.length} 个版本 · {previewImage.aspectRatio} · {previewImage.resolution}
                        {previewImage.cost === null ? "" : ` · 费用记录 ${previewImage.cost}`}
                      </p>
                    ) : (
                      <p>确认文字规范并保存后，可调用 TT Image 2.5 生成第一版参考图。</p>
                    )}
                    {selectedItem.referenceImages.length ? (
                      <div className="asset-version-history" aria-label="参考图历史版本">
                        {selectedItem.referenceImages.map((image, index) => {
                          const isPrimary = image.id === primaryImage?.id;
                          const isActive = image.id === previewImage?.id;
                          return (
                            <button
                              className={isActive ? "active" : ""}
                              type="button"
                              aria-label={`查看版本 ${index + 1}${isPrimary ? "（主参考图）" : ""}`}
                              onClick={() => {
                                setPreviewImageId(image.id);
                                setLightboxOpen(true);
                              }}
                              key={image.id}
                            >
                              <img src={image.url} alt="" loading="lazy" />
                              <span>V{index + 1}</span>
                              {isPrimary ? <Crown size={11} /> : null}
                            </button>
                          );
                        })}
                      </div>
                    ) : null}
                  </div>
                  <div className="asset-generation-actions">
                    {previewImage && previewImage.id !== primaryImage?.id ? (
                      <button
                        className="button secondary compact"
                        type="button"
                        disabled={dirty || settingPrimary}
                        onClick={handleSetPrimary}
                      >
                        {settingPrimary ? <LoaderCircle className="spinning" size={15} /> : <Crown size={15} />}
                        {settingPrimary ? "正在设置…" : "设为主参考图"}
                      </button>
                    ) : null}
                    {!imageModelConfigured ? (
                      <button className="button secondary compact" type="button" onClick={onOpenApiSettings}>
                        <ImageIcon size={15} /> 配置图像模型
                      </button>
                    ) : (
                      <button
                        className="button primary compact"
                        type="button"
                        disabled={Boolean(generatingId) || settingPrimary || dirty || selectedItem.status !== "confirmed" || !promptUsesCurrentStandard(selectedItem, activeStandard)}
                        onClick={handleGenerate}
                        title={dirty
                          ? "请先保存资产修改"
                          : selectedItem.status !== "confirmed"
                            ? "请先确认资产"
                            : !promptUsesCurrentStandard(selectedItem, activeStandard)
                              ? "请先按当前资产标准重编提示词"
                              : "本操作会消耗一次生图额度"}
                      >
                        {generatingId === selectedItem.id ? <LoaderCircle className="spinning" size={15} /> : <Sparkles size={15} />}
                        {generatingId === selectedItem.id
                          ? "正在生成…"
                          : selectedItem.referenceImages.length
                            ? "重新生成（消耗额度）"
                            : "生成参考图（消耗额度）"}
                      </button>
                    )}
                    {generatingId === selectedItem.id ? <small>通常需要 20 秒—2 分钟，请勿重复点击</small> : null}
                  </div>
                </footer>
                {promptPreview?.assetId === selectedItem.id ? (
                  <div
                    className="asset-prompt-preview"
                    role="dialog"
                    aria-modal="true"
                    aria-labelledby="asset-prompt-preview-title"
                    onClick={() => setPromptPreview(null)}
                  >
                    <div className="asset-prompt-preview-panel" onClick={(event) => event.stopPropagation()}>
                      <header>
                        <div>
                          <strong id="asset-prompt-preview-title">{selectedItem.name} · 标准化提示词预览</strong>
                          <span>
                            {promptPreview.compiled.standardLabel}
                            {promptPreview.compiled.eraLabel ? ` · ${promptPreview.compiled.eraLabel}` : ""}
                          </span>
                        </div>
                        <button type="button" aria-label="关闭提示词预览" onClick={() => setPromptPreview(null)} autoFocus>
                          <X size={20} />
                        </button>
                      </header>
                      {promptPreview.compiled.warnings.length ? (
                        <div className="asset-prompt-warnings">
                          {promptPreview.compiled.warnings.map((warning) => <p key={warning}>{warning}</p>)}
                        </div>
                      ) : null}
                      <div className="asset-prompt-comparison">
                        <section>
                          <h3>当前提示词</h3>
                          <pre>{selectedItem.referencePrompt || "当前没有提示词"}</pre>
                        </section>
                        <section>
                          <h3>标准化预览</h3>
                          <pre>{promptPreview.compiled.prompt}</pre>
                        </section>
                      </div>
                      <footer>
                        <p>应用只会替换本资产的提示词，并撤销“已确认”状态；参考图不会改变，仍需手动保存。</p>
                        <div>
                          <button className="button secondary compact" type="button" onClick={() => setPromptPreview(null)}>关闭</button>
                          <button className="button primary compact" type="button" onClick={handleApplyPrompt}>
                            <Check size={15} /> 应用到本资产
                          </button>
                        </div>
                      </footer>
                    </div>
                  </div>
                ) : null}
                {lightboxOpen && previewImage ? (
                  <div
                    className="asset-image-lightbox"
                    role="dialog"
                    aria-modal="true"
                    aria-label={`${selectedItem.name}参考图大图预览`}
                    onClick={() => setLightboxOpen(false)}
                  >
                    <div className="asset-image-lightbox-panel" onClick={(event) => event.stopPropagation()}>
                      <header>
                        <div>
                          <strong>{selectedItem.name} · 版本 V{previewVersion}</strong>
                          <span>{previewImage.aspectRatio} · {previewImage.resolution}{previewImage.id === primaryImage?.id ? " · 主参考图" : ""}</span>
                        </div>
                        <button type="button" aria-label="关闭大图预览" onClick={() => setLightboxOpen(false)} autoFocus>
                          <X size={20} />
                        </button>
                      </header>
                      <img src={previewImage.url} alt={`${selectedItem.name}参考图版本 ${previewVersion} 大图`} />
                    </div>
                  </div>
                ) : null}
              </article>
            ) : (
              <div className="asset-no-selection"><Boxes size={28} />当前分类没有资产</div>
            )}
          </section>
          {batchOpen ? (
            <div
              className="asset-batch-dialog"
              role="dialog"
              aria-modal="true"
              aria-labelledby="asset-batch-title"
              onClick={() => setBatchOpen(false)}
            >
              <div className="asset-batch-panel" onClick={(event) => event.stopPropagation()}>
                <header>
                  <div>
                    <strong id="asset-batch-title">批量资产生产预检</strong>
                    <span>选择资产、逐项审查提示词并保存生产清单；本步骤不会生成图片。</span>
                  </div>
                  <button type="button" aria-label="关闭批量生产预检" onClick={() => setBatchOpen(false)} autoFocus>
                    <X size={20} />
                  </button>
                </header>

                <section className="asset-batch-summary" aria-label="批量生产估算">
                  <div><ListChecks size={17} /><span>已选择</span><strong>{selectedBatchItems.length} 项</strong></div>
                  <div><Sparkles size={17} /><span>预计消耗</span><strong>{selectedBatchItems.length} 次</strong></div>
                  <div>
                    <Calculator size={17} />
                    <span>预计费用记录</span>
                    <strong>{estimatedTotalCost === null ? "暂无估算" : formatCost(estimatedTotalCost)}</strong>
                  </div>
                  <p>
                    {estimatedUnitCost === null
                      ? "项目尚无可用费用样本；清单仍可保存，实际费用以服务商任务结果为准。"
                      : `基于 ${batchCostSamples.length} 条本机历史记录，平均每张 ${formatCost(estimatedUnitCost)}；实际费用以服务商返回为准。`}
                  </p>
                </section>

                {batchSelectionMatchesPlan ? (
                  <div className="asset-batch-saved">
                    <ShieldCheck size={16} />
                    当前 {batchPlan?.items.length} 项清单已确认并保存；尚未进入生成队列，也未消耗额度。
                  </div>
                ) : null}

                <div className="asset-batch-body">
                  <section className="asset-batch-list" aria-label="资产生产选择">
                    <header>
                      <div>
                        <strong>资产选择</strong>
                        <span>{eligibleBatchItems.length} 项已确认可加入清单</span>
                      </div>
                      <div>
                        <button type="button" onClick={() => selectBatchItems(eligibleBatchItems.filter((item) => !item.referenceImages.length))}>仅选未生成</button>
                        <button type="button" onClick={() => selectBatchItems(eligibleBatchItems)}>选择全部</button>
                      </div>
                    </header>
                    <div className="asset-batch-rows">
                      {library.items.map((item) => {
                        const eligible = item.status === "confirmed"
                          && itemReady(item)
                          && promptUsesCurrentStandard(item, activeStandard);
                        const selected = batchSelectedIds.includes(item.id);
                        const reviewed = reviewedSet.has(item.id);
                        return (
                          <div
                            className={`asset-batch-row${batchReviewItem?.id === item.id ? " active" : ""}${eligible ? "" : " disabled"}`}
                            key={item.id}
                          >
                            <input
                              type="checkbox"
                              checked={selected}
                              disabled={!eligible}
                              aria-label={`${selected ? "从生产清单移除" : "加入生产清单"}${item.name}`}
                              onChange={() => toggleBatchSelection(item.id)}
                            />
                            <button type="button" onClick={() => setBatchReviewId(item.id)}>
                              <span><strong>{item.name}</strong><small>{KIND_META[item.kind].label} · {item.referenceImages.length} 个现有版本</small></span>
                              <em>
                                {!eligible
                                  ? item.status === "confirmed" && !promptUsesCurrentStandard(item, activeStandard)
                                    ? "提示词待重编"
                                    : "待确认"
                                  : selected ? (reviewed ? "已审查" : "待审查") : "未选择"}
                              </em>
                            </button>
                          </div>
                        );
                      })}
                    </div>
                  </section>

                  <section className="asset-batch-review" aria-label="提示词审查">
                    {batchReviewItem ? (
                      <>
                        <header>
                          <div>
                            <strong>{batchReviewItem.name}</strong>
                            <span>{KIND_META[batchReviewItem.kind].label}资产 · {assetAspectRatio(activeStandard.visualStandard, batchReviewItem.kind)} · 1K</span>
                          </div>
                          <span className={reviewedSet.has(batchReviewItem.id) ? "reviewed" : ""}>
                            {reviewedSet.has(batchReviewItem.id) ? "已完成审查" : "等待审查"}
                          </span>
                        </header>
                        <div className="asset-batch-prompt">
                          <span>将要保存的生图提示词快照</span>
                          <pre>{batchReviewItem.referencePrompt || "当前没有提示词"}</pre>
                        </div>
                        <footer>
                          <p>请确认人物身份、服饰、材质、空间关系与禁止项准确；保存清单后仍不会自动生图。</p>
                          <button
                            className="button secondary compact"
                            type="button"
                            disabled={!batchSelectedIds.includes(batchReviewItem.id)}
                            onClick={() => setBatchReviewedIds((current) => current.includes(batchReviewItem.id) ? current : [...current, batchReviewItem.id])}
                          >
                            <Check size={15} />
                            {reviewedSet.has(batchReviewItem.id) ? "已标记审查" : "标记为已审查"}
                          </button>
                        </footer>
                      </>
                    ) : (
                      <div className="asset-batch-empty"><ListChecks size={26} />请选择一项资产审查提示词</div>
                    )}
                  </section>
                </div>

                <footer className="asset-batch-footer">
                  <div>
                    <label>
                      <input
                        type="checkbox"
                        checked={batchAcknowledged}
                        disabled={!allSelectedReviewed}
                        onChange={(event) => setBatchAcknowledged(event.target.checked)}
                      />
                      {batchSelectionMatchesPlan
                        ? `我确认现在开始执行 ${selectedBatchItems.length} 项生图任务，预计消耗 ${selectedBatchItems.length} 次图像生成额度。`
                        : `我已逐项审查以上提示词，并确认后续排队将消耗 ${selectedBatchItems.length} 次图像生成额度。`}
                    </label>
                    <small>
                      {selectedBatchItems.length === 0
                        ? "请至少选择一项已确认资产。"
                        : allSelectedReviewed
                          ? batchSelectionMatchesPlan
                            ? "清单已保存；点击开始后任务会按顺序执行，并可在任务中心查看。"
                            : "审查已完成，可以保存生产清单。"
                          : `还有 ${selectedBatchItems.filter((item) => !reviewedSet.has(item.id)).length} 项提示词未标记审查。`}
                    </small>
                    {error ? <span className="asset-batch-error">{error}</span> : null}
                  </div>
                  <div>
                    <button className="button secondary compact" type="button" onClick={() => setBatchOpen(false)}>关闭</button>
                    {!imageModelConfigured ? (
                      <button className="button secondary compact" type="button" onClick={onOpenApiSettings}>配置图像模型</button>
                    ) : (
                      <button
                        className="button primary compact"
                        type="button"
                        disabled={!batchAcknowledged || !allSelectedReviewed || batchSaving || batchQueueing}
                        onClick={batchSelectionMatchesPlan ? handleQueueBatchPlan : handleConfirmBatchPlan}
                      >
                        {batchSaving || batchQueueing
                          ? <LoaderCircle className="spinning" size={15} />
                          : batchSelectionMatchesPlan ? <Sparkles size={15} /> : <ShieldCheck size={15} />}
                        {batchQueueing
                          ? "正在创建队列…"
                          : batchSaving
                            ? "正在保存…"
                            : batchSelectionMatchesPlan
                              ? `开始批量生成（消耗 ${selectedBatchItems.length} 次额度）`
                              : "确认清单（暂不生成）"}
                      </button>
                    )}
                  </div>
                </footer>
              </div>
            </div>
          ) : null}
        </>
      )}
    </main>
  );
}
