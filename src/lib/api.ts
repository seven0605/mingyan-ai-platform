import type {
  AssetTunnelStatus,
  AssetBatchPlan,
  AssetItem,
  AssetLibrary,
  AssetStandardSettings,
  ComfyUIVideoSettings,
  ImageModelSettings,
  Project,
  ProjectStage,
  ProjectTask,
  Screenplay,
  ScreenplayMode,
  Storyboard,
  StoryboardAspectRatio,
  StoryboardTargetModel,
  ScriptPlan,
  SourceDocument,
  StoryAnalysis,
  SyncStatus,
  TextModelConnection,
  TextModelSettings,
  VideoModelSettings,
  VideoBackendSettings,
  VideoProductionPlan,
} from "../types";

interface NewProjectInput {
  name: string;
  description: string;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...init?.headers,
    },
  });

  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as { detail?: string } | null;
    throw new Error(payload?.detail ?? `本地服务请求失败（${response.status}）`);
  }

  return response.json() as Promise<T>;
}

export function listProjects() {
  return request<Project[]>("/api/projects");
}

export function createProject(input: NewProjectInput) {
  return request<Project>("/api/projects", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function updateProjectStage(projectId: string, stage: ProjectStage) {
  return request<Project>(`/api/projects/${projectId}/stage`, {
    method: "PATCH",
    body: JSON.stringify({ stage }),
  });
}

export function getProjectSource(projectId: string) {
  return request<SourceDocument | null>(`/api/projects/${projectId}/source`);
}

export function saveProjectSource(projectId: string, title: string, content: string) {
  return request<SourceDocument>(`/api/projects/${projectId}/source`, {
    method: "PUT",
    body: JSON.stringify({ title, content }),
  });
}

export function getProjectAnalysis(projectId: string) {
  return request<StoryAnalysis | null>(`/api/projects/${projectId}/analysis`);
}

export function analyzeProject(projectId: string) {
  return request<StoryAnalysis>(`/api/projects/${projectId}/analysis`, {
    method: "POST",
  });
}

export function getTextModelSettings() {
  return request<TextModelSettings>("/api/settings/text-model");
}

export function saveTextModelSettings(input: {
  baseUrl: string;
  model: string;
  apiKey?: string;
}) {
  return request<TextModelSettings>("/api/settings/text-model", {
    method: "PUT",
    body: JSON.stringify(input),
  });
}

export function testTextModelConnection() {
  return request<TextModelConnection>("/api/settings/text-model/test", {
    method: "POST",
  });
}

export function getImageModelSettings() {
  return request<ImageModelSettings>("/api/settings/image-model");
}

export function saveImageModelSettings(input: {
  baseUrl: string;
  model: string;
  concurrency: number;
  apiKey?: string;
}) {
  return request<ImageModelSettings>("/api/settings/image-model", {
    method: "PUT",
    body: JSON.stringify(input),
  });
}

export function testImageModelConnection() {
  return request<TextModelConnection>("/api/settings/image-model/test", {
    method: "POST",
  });
}

export function getVideoModelSettings() {
  return request<VideoModelSettings>("/api/settings/video-model");
}

export function saveVideoModelSettings(input: {
  baseUrl: string;
  model: string;
  concurrency: number;
  apiKey?: string;
}) {
  return request<VideoModelSettings>("/api/settings/video-model", {
    method: "PUT",
    body: JSON.stringify(input),
  });
}

export function testVideoModelConnection() {
  return request<TextModelConnection>("/api/settings/video-model/test", {
    method: "POST",
  });
}

export function getComfyUIVideoSettings() {
  return request<ComfyUIVideoSettings>("/api/settings/comfyui-video");
}

export function saveComfyUIVideoSettings(input: {
  baseUrl: string;
  workflowName: string;
  workflowJson: string;
  allowInsecureTls: boolean;
}) {
  return request<ComfyUIVideoSettings>("/api/settings/comfyui-video", {
    method: "PUT",
    body: JSON.stringify(input),
  });
}

export function testComfyUIVideoConnection() {
  return request<TextModelConnection>("/api/settings/comfyui-video/test", {
    method: "POST",
  });
}

export function getVideoBackendSettings() {
  return request<VideoBackendSettings>("/api/settings/video-backend");
}

export function saveVideoBackend(activeBackend: "api" | "comfyui") {
  return request<VideoBackendSettings>("/api/settings/video-backend", {
    method: "PUT",
    body: JSON.stringify({ activeBackend }),
  });
}

export function getSyncStatus() {
  return request<SyncStatus>("/api/sync/status");
}

export function saveSyncSettings(input: {
  folderPath: string;
  deviceName: string;
  enabled: boolean;
}) {
  return request<SyncStatus>("/api/sync/settings", {
    method: "PUT",
    body: JSON.stringify(input),
  });
}

export function pushSyncSnapshot(force = false) {
  return request<SyncStatus>("/api/sync/push", {
    method: "POST",
    body: JSON.stringify({ force }),
  });
}

export function pullSyncSnapshot(force = false) {
  return request<SyncStatus>("/api/sync/pull", {
    method: "POST",
    body: JSON.stringify({ force }),
  });
}

export function getScriptPlan(projectId: string) {
  return request<ScriptPlan | null>(`/api/projects/${projectId}/script-plan`);
}

export function generateScriptPlan(projectId: string) {
  return request<ScriptPlan>(`/api/projects/${projectId}/script-plan`, {
    method: "POST",
  });
}

export function getScreenplay(projectId: string) {
  return request<Screenplay | null>(`/api/projects/${projectId}/screenplay`);
}

export function generateScreenplay(
  projectId: string,
  input: {
    adaptationMode: ScreenplayMode;
    targetSeconds: 60 | 90 | 120 | 180;
    episodeCount: number;
  },
) {
  return request<Screenplay>(`/api/projects/${projectId}/screenplay`, {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function saveScreenplay(projectId: string, screenplay: Screenplay) {
  const {
    adaptationMode,
    targetSeconds,
    episodeCount,
    episodes,
    continuityNotes,
  } = screenplay;
  return request<Screenplay>(`/api/projects/${projectId}/screenplay`, {
    method: "PUT",
    body: JSON.stringify({
      adaptationMode,
      targetSeconds,
      episodeCount,
      episodes,
      continuityNotes,
    }),
  });
}

export function approveScreenplay(projectId: string) {
  return request<Screenplay>(`/api/projects/${projectId}/screenplay/approve`, {
    method: "POST",
  });
}

export function refineScreenplayEpisode(projectId: string, episodeNumber: number) {
  return request<Screenplay>(
    `/api/projects/${projectId}/screenplay/episodes/${episodeNumber}/refine`,
    { method: "POST" },
  );
}

export function getStoryboards(projectId: string) {
  return request<Storyboard[]>(`/api/projects/${projectId}/storyboards`);
}

export function generateStoryboard(
  projectId: string,
  episodeNumber: number,
  input: { targetModel: StoryboardTargetModel; aspectRatio: StoryboardAspectRatio },
) {
  return request<Storyboard>(`/api/projects/${projectId}/storyboards/${episodeNumber}`, {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function saveStoryboard(projectId: string, episodeNumber: number, storyboard: Storyboard) {
  const { episodeTitle, styleBible, groups, continuityNotes } = storyboard;
  return request<Storyboard>(`/api/projects/${projectId}/storyboards/${episodeNumber}`, {
    method: "PUT",
    body: JSON.stringify({
      episodeNumber,
      episodeTitle,
      styleBible,
      groups,
      continuityNotes,
    }),
  });
}

export function getAssetLibrary(projectId: string) {
  return request<AssetLibrary | null>(`/api/projects/${projectId}/assets`);
}

export function getAssetBatchPlan(projectId: string) {
  return request<AssetBatchPlan | null>(`/api/projects/${projectId}/assets/batch-plan`);
}

export function confirmAssetBatchPlan(projectId: string, assetIds: string[]) {
  return request<AssetBatchPlan>(`/api/projects/${projectId}/assets/batch-plan`, {
    method: "POST",
    body: JSON.stringify({ assetIds }),
  });
}

export function queueAssetBatchPlan(projectId: string) {
  return request<ProjectTask[]>(`/api/projects/${projectId}/assets/batch-plan/queue`, {
    method: "POST",
  });
}

export function getProjectTasks(projectId: string) {
  return request<ProjectTask[]>(`/api/projects/${projectId}/tasks`);
}

export function retryProjectTask(projectId: string, taskId: string) {
  return request<ProjectTask>(`/api/projects/${projectId}/tasks/${taskId}/retry`, {
    method: "POST",
  });
}

export function resumeProjectTasks(projectId: string) {
  return request<ProjectTask[]>(`/api/projects/${projectId}/tasks/resume`, {
    method: "POST",
  });
}

export function extractAssetLibrary(projectId: string) {
  return request<AssetLibrary>(`/api/projects/${projectId}/assets/extract`, {
    method: "POST",
  });
}

export function enrichAssetLibrary(
  projectId: string,
  standard: AssetStandardSettings,
) {
  return request<{ items: AssetItem[] }>(`/api/projects/${projectId}/assets/enrich`, {
    method: "POST",
    body: JSON.stringify(standard),
  });
}

export function saveAssetLibrary(projectId: string, library: AssetLibrary) {
  return request<AssetLibrary>(`/api/projects/${projectId}/assets`, {
    method: "PUT",
    body: JSON.stringify({ items: library.items, standard: library.standard }),
  });
}

export function generateAssetReferenceImage(
  projectId: string,
  assetId: string,
  options?: {
    mode: "asset-card" | "state";
    stateLabel?: string;
    statePrompt?: string;
  },
) {
  return request<AssetLibrary>(`/api/projects/${projectId}/assets/${assetId}/images`, {
    method: "POST",
    body: options ? JSON.stringify(options) : undefined,
  });
}

export function createAssetIdentityMaster(
  projectId: string,
  assetId: string,
  sourceImageId: string,
  imageData: string,
) {
  return request<AssetLibrary>(
    `/api/projects/${projectId}/assets/${assetId}/identity-masters`,
    {
      method: "POST",
      body: JSON.stringify({ sourceImageId, imageData }),
    },
  );
}

export function setPrimaryAssetReferenceImage(
  projectId: string,
  assetId: string,
  imageId: string,
) {
  return request<AssetLibrary>(
    `/api/projects/${projectId}/assets/${assetId}/images/${imageId}/primary`,
    { method: "PUT" },
  );
}

export function getVideoProductionPlan(projectId: string) {
  return request<VideoProductionPlan>(`/api/projects/${projectId}/video-plan`);
}

export function confirmVideoProductionPlan(
  projectId: string,
  itemIds: string[],
  referenceImageIds: Record<string, Record<string, string>>,
) {
  return request<VideoProductionPlan>(`/api/projects/${projectId}/video-plan`, {
    method: "POST",
    body: JSON.stringify({ itemIds, referenceImageIds }),
  });
}

export function queueVideoProductionPlan(projectId: string) {
  return request<ProjectTask[]>(`/api/projects/${projectId}/video-plan/queue`, {
    method: "POST",
  });
}

export function getAssetTunnelStatus() {
  return request<AssetTunnelStatus>("/api/settings/asset-tunnel");
}

export function startAssetTunnel(projectId: string) {
  return request<AssetTunnelStatus>(`/api/projects/${projectId}/asset-tunnel`, {
    method: "POST",
  });
}

export function stopAssetTunnel(projectId: string) {
  return request<AssetTunnelStatus>(`/api/projects/${projectId}/asset-tunnel`, {
    method: "DELETE",
  });
}
