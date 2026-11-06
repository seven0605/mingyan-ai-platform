export type PageId =
  | "workspace"
  | "source"
  | "storyboard"
  | "assets"
  | "video"
  | "prompts"
  | "tasks"
  | "plugins"
  | "api"
  | "library"
  | "export";

export type ProjectStage = "text" | "script" | "storyboard" | "assets" | "video";

export interface Project {
  id: string;
  name: string;
  description: string;
  stage: ProjectStage;
  createdAt: string;
  updatedAt: string;
}

export interface SourceDocument {
  projectId: string;
  title: string;
  content: string;
  charCount: number;
  chapterCount: number;
  updatedAt: string;
}

export interface AnalysisCandidate {
  name: string;
  mentions: number;
  chapters: number[];
}

export interface PlotNode {
  index: number;
  title: string;
  charCount: number;
  opening: string;
  closing: string;
}

export interface StoryAnalysis {
  projectId: string;
  engine: string;
  sourceUpdatedAt: string;
  updatedAt: string;
  characters: AnalysisCandidate[];
  scenes: AnalysisCandidate[];
  plotNodes: PlotNode[];
}

export interface TextModelSettings {
  provider: "openai-compatible";
  baseUrl: string;
  model: string;
  hasCredential: boolean;
  configured: boolean;
  updatedAt: string | null;
}

export interface TextModelConnection {
  connected: boolean;
  model: string;
  latencyMs: number;
  message: string;
}

export interface ImageModelSettings {
  provider: "buming-openai-compatible";
  baseUrl: string;
  model: string;
  hasCredential: boolean;
  configured: boolean;
  concurrency: number;
  updatedAt: string | null;
}

export interface VideoModelSettings {
  provider: "shuikule-openai-compatible";
  baseUrl: string;
  model: string;
  hasCredential: boolean;
  configured: boolean;
  concurrency: number;
  updatedAt: string | null;
}

export interface ComfyUIVideoSettings {
  provider: "comfyui-h3";
  baseUrl: string;
  model: "MiniMax H3";
  workflowName: string;
  workflowJson: string;
  allowInsecureTls: boolean;
  workflowConfigured: boolean;
  configured: boolean;
  updatedAt: string | null;
}

export interface VideoBackendSettings {
  activeBackend: "api" | "comfyui";
  configured: boolean;
  apiConfigured: boolean;
  comfyuiConfigured: boolean;
  updatedAt: string | null;
}

export interface ScriptCharacter {
  name: string;
  identity: string;
  goal: string;
  obstacle: string;
  arc: string;
}

export interface ScriptRelationship {
  fromCharacter: string;
  toCharacter: string;
  publicRelation: string;
  trueAttitude: string;
  tension: string;
}

export interface ScriptScene {
  index: number;
  chapter: string;
  heading: string;
  characters: string[];
  objective: string;
  conflict: string;
  turn: string;
  outcome: string;
}

export interface ScriptPlan {
  projectId: string;
  model: string;
  sourceUpdatedAt: string;
  updatedAt: string;
  title: string;
  format: string;
  logline: string;
  coreConflict: string;
  characters: ScriptCharacter[];
  relationships: ScriptRelationship[];
  scenes: ScriptScene[];
  adaptationNotes: string[];
}

export type ScreenplayMode = "faithful" | "commercial";
export type ScreenplayBeatKind = "action" | "dialogue" | "voiceover";
export type ScreenplayOrigin = "source" | "translation" | "suggestion";
export type ScreenplayStatus = "draft" | "approved";
export type ScreenplayFidelityStatus = "unchecked" | "passed" | "review";

export interface ScreenplayBeat {
  kind: ScreenplayBeatKind;
  speaker: string;
  text: string;
  sourceRef: string;
  origin: ScreenplayOrigin;
  estimatedSeconds: number;
}

export interface ScreenplayScene {
  index: number;
  heading: string;
  characters: string[];
  props: string[];
  objective: string;
  obstacle: string;
  estimatedSeconds: number;
  sourceRefs: string[];
  beats: ScreenplayBeat[];
  result: string;
}

export interface ScreenplayEpisode {
  episodeNumber: number;
  title: string;
  sourceRange: string;
  objective: string;
  centralConflict: string;
  stateChange: string;
  targetSeconds: number;
  estimatedSeconds: number;
  scenes: ScreenplayScene[];
  endingState: string;
  hook: string;
  qualityNotes: string[];
  fidelityStatus: ScreenplayFidelityStatus;
  fidelityNotes: string[];
}

export interface Screenplay {
  projectId: string;
  model: string;
  sourceUpdatedAt: string;
  planUpdatedAt: string;
  updatedAt: string;
  status: ScreenplayStatus;
  approvedAt: string | null;
  adaptationMode: ScreenplayMode;
  targetSeconds: number;
  episodeCount: number;
  episodes: ScreenplayEpisode[];
  continuityNotes: string[];
}

export type StoryboardTargetModel = "seedance-2.0" | "sora-2" | "kling-3.0" | "veo-3.1";
export type StoryboardAspectRatio = "16:9" | "9:16";

export interface StoryboardSegment {
  startSeconds: number;
  endSeconds: number;
  camera: string;
  action: string;
  motionVisual: string;
  expression: string;
  environment: string;
  effects: string;
  sound: string;
}

export interface StoryboardGroup {
  index: number;
  sceneIndex: number;
  startSeconds: number;
  endSeconds: number;
  durationSeconds: number;
  purpose: string;
  hookType: string;
  metadata: string;
  sceneDescription: string;
  firstFrameLock: string;
  segments: StoryboardSegment[];
  qualityBase: string;
  visualStyle: string;
  subjects: string[];
  spatialRelations: string;
  actionTimeline: string;
  cameraLanguage: string;
  emotionalTurn: string;
  keyDialogue: string;
  negativePrompt: string;
  generationParams: string;
  videoPrompt: string;
}

export interface Storyboard {
  projectId: string;
  model: string;
  targetModel: StoryboardTargetModel;
  aspectRatio: StoryboardAspectRatio;
  fps: number;
  totalSeconds: number;
  screenplayUpdatedAt: string;
  updatedAt: string;
  episodeNumber: number;
  episodeTitle: string;
  styleBible: string;
  groups: StoryboardGroup[];
  continuityNotes: string[];
}

export type AssetKind = "character" | "scene" | "prop";
export type AssetStatus = "draft" | "confirmed";
export type AssetVisualStandard =
  | "live-action"
  | "guofeng-3d"
  | "handpainted-3d2d"
  | "western-dark-medieval"
  | "victorian-gothic";
export type CostumeEra =
  | "auto"
  | "xia"
  | "shang"
  | "zhou"
  | "qin"
  | "han"
  | "three-kingdoms"
  | "jin"
  | "northern-southern"
  | "sui"
  | "tang"
  | "five-dynasties"
  | "song"
  | "yuan"
  | "ming"
  | "qing";

export interface AssetStandardSettings {
  visualStandard: AssetVisualStandard;
  costumeEra: CostumeEra;
}

export interface AssetImageVersion {
  id: string;
  url: string;
  prompt: string;
  model: string;
  taskId: string;
  aspectRatio: string;
  resolution: string;
  cost: number | null;
  identityReferenceImageId: string;
  role: "asset-card" | "state";
  stateLabel: string;
  createdAt: string;
}

export interface AssetIdentityMaster {
  id: string;
  url: string;
  sourceImageId: string;
  createdAt: string;
}

export interface AssetItem {
  id: string;
  kind: AssetKind;
  name: string;
  status: AssetStatus;
  appearances: string[];
  sourceRefs: string[];
  description: string;
  visualAnchor: string;
  continuityNotes: string;
  referencePrompt: string;
  promptStandardSignature: string;
  referenceImages: AssetImageVersion[];
  primaryReferenceImageId: string | null;
  identityMasters: AssetIdentityMaster[];
  identityMasterId: string | null;
}

export interface AssetLibrary {
  projectId: string;
  screenplayUpdatedAt: string;
  storyboardUpdatedAt: string | null;
  updatedAt: string;
  standard: AssetStandardSettings;
  items: AssetItem[];
}

export interface AssetBatchPlanItem {
  assetId: string;
  assetKind: AssetKind;
  name: string;
  prompt: string;
  aspectRatio: string;
  existingVersionCount: number;
}

export interface AssetBatchPlan {
  projectId: string;
  items: AssetBatchPlanItem[];
  estimatedUnitCost: number | null;
  estimatedTotalCost: number | null;
  costSampleCount: number;
  assetLibraryUpdatedAt: string;
  confirmedAt: string;
  current: boolean;
  updatedAt: string;
}

export interface VideoPlanAssetReference {
  assetId: string;
  kind: AssetKind;
  name: string;
  imageId: string;
  imageUrl: string;
  direct: boolean;
  availableImages: Array<{
    id: string;
    url: string;
    label: string;
    identityReferenceImageId: string;
    identityMasterId: string;
    identityMasterUrl: string;
  }>;
  identityMasterId: string;
  identityMasterUrl: string;
}

export interface VideoProductionPlanItem {
  id: string;
  episodeNumber: number;
  episodeTitle: string;
  groupIndex: number;
  sceneIndex: number;
  durationSeconds: number;
  aspectRatio: StoryboardAspectRatio;
  targetModel: StoryboardTargetModel;
  purpose: string;
  prompt: string;
  assetReferences: VideoPlanAssetReference[];
  blockingReasons: string[];
  ready: boolean;
}

export interface VideoProductionPlan {
  projectId: string;
  items: VideoProductionPlanItem[];
  selectedItemIds: string[];
  referenceImageIds: Record<string, Record<string, string>>;
  storyboardUpdatedAt: string;
  assetLibraryUpdatedAt: string;
  current: boolean;
  confirmedAt: string | null;
}

export interface AssetTunnelStatus {
  provider: "cloudflare-quick-tunnel";
  installed: boolean;
  running: boolean;
  projectId: string | null;
  publicUrl: string | null;
  exposedAssetCount: number;
  error: string;
  warning: string;
}

export type ProjectTaskStatus = "queued" | "running" | "completed" | "failed" | "interrupted";

export interface ProjectTask {
  id: string;
  projectId: string;
  type: "asset-image" | "video";
  status: ProjectTaskStatus;
  title: string;
  assetId: string;
  assetKind: AssetKind | "video";
  providerTaskId: string;
  model: string;
  resultUrl: string;
  cost: number | null;
  batchId: string;
  error: string;
  attemptCount: number;
  createdAt: string;
  updatedAt: string;
}
