import { useEffect, useState } from "react";
import { ApiSettings } from "./components/ApiSettings";
import { AssetWorkspace } from "./components/AssetWorkspace";
import { CreateProjectDialog } from "./components/CreateProjectDialog";
import { PlaceholderPage } from "./components/PlaceholderPage";
import { Sidebar } from "./components/Sidebar";
import { SourceEditor } from "./components/SourceEditor";
import { StoryboardWorkspace } from "./components/StoryboardWorkspace";
import { SyncSettings } from "./components/SyncSettings";
import { TaskCenter } from "./components/TaskCenter";
import { TopBar } from "./components/TopBar";
import { VideoWorkspace } from "./components/VideoWorkspace";
import { Workspace } from "./components/Workspace";
import { useProjects } from "./hooks/useProjects";
import {
  getComfyUIVideoSettings,
  getImageModelSettings,
  getTextModelSettings,
  getVideoBackendSettings,
  getVideoModelSettings,
} from "./lib/api";
import type {
  ComfyUIVideoSettings,
  ImageModelSettings,
  PageId,
  TextModelSettings,
  VideoBackendSettings,
  VideoModelSettings,
} from "./types";

const PAGE_TITLES: Record<Exclude<PageId, "workspace" | "source">, string> = {
  storyboard: "分镜工作台",
  assets: "角色 · 场景 · 物品",
  video: "视频生成",
  prompts: "提示词模板",
  tasks: "任务中心",
  plugins: "插件管理",
  api: "API 设置",
  sync: "跨设备同步",
  library: "素材库",
  export: "成片导出",
};

export default function App() {
  const [activePage, setActivePage] = useState<PageId>("workspace");
  const [createDialogOpen, setCreateDialogOpen] = useState(false);
  const [textModelSettings, setTextModelSettings] = useState<TextModelSettings | null>(null);
  const [imageModelSettings, setImageModelSettings] = useState<ImageModelSettings | null>(null);
  const [videoModelSettings, setVideoModelSettings] = useState<VideoModelSettings | null>(null);
  const [comfyUIVideoSettings, setComfyUIVideoSettings] = useState<ComfyUIVideoSettings | null>(null);
  const [videoBackendSettings, setVideoBackendSettings] = useState<VideoBackendSettings | null>(null);
  const [settingsError, setSettingsError] = useState<string | null>(null);
  const {
    projects,
    currentProject,
    loading,
    error,
    createProject,
    selectProject,
    updateStage,
  } = useProjects();

  useEffect(() => {
    let active = true;
    Promise.all([
      getTextModelSettings(),
      getImageModelSettings(),
      getVideoModelSettings(),
      getComfyUIVideoSettings(),
      getVideoBackendSettings(),
    ])
      .then(([textSettings, imageSettings, videoSettings, comfySettings, backendSettings]) => {
        if (!active) return;
        setTextModelSettings(textSettings);
        setImageModelSettings(imageSettings);
        setVideoModelSettings(videoSettings);
        setComfyUIVideoSettings(comfySettings);
        setVideoBackendSettings(backendSettings);
      })
      .catch((settingsLoadError: unknown) => {
        if (!active) return;
        setSettingsError(
          settingsLoadError instanceof Error ? settingsLoadError.message : "模型配置读取失败",
        );
      });
    return () => {
      active = false;
    };
  }, []);

  return (
    <div className="app-shell">
      <Sidebar activePage={activePage} onNavigate={setActivePage} />
      <div className="app-main">
        <TopBar onSettings={() => setActivePage("api")} />
        {activePage === "workspace" ? (
          <Workspace
            projects={projects}
            currentProject={currentProject}
            loading={loading}
            backendError={error}
            onCreateProject={() => setCreateDialogOpen(true)}
            onSelectProject={selectProject}
            onUpdateStage={updateStage}
            onContinueProject={() => setActivePage("source")}
            onOpenApiSettings={() => setActivePage("api")}
            onOpenTasks={() => setActivePage("tasks")}
            textModelConfigured={textModelSettings?.configured ?? false}
            imageModelConfigured={imageModelSettings?.configured ?? false}
            videoModelConfigured={videoBackendSettings?.configured ?? false}
          />
        ) : activePage === "source" ? (
          <SourceEditor
            project={currentProject}
            onBack={() => setActivePage("workspace")}
            onCreateProject={() => setCreateDialogOpen(true)}
            onAdvanceToStoryboard={async () => {
              await updateStage("storyboard");
              setActivePage("storyboard");
            }}
          />
        ) : activePage === "api" ? (
          <ApiSettings
            textSettings={textModelSettings}
            imageSettings={imageModelSettings}
            videoSettings={videoModelSettings}
            comfyUIVideoSettings={comfyUIVideoSettings}
            videoBackendSettings={videoBackendSettings}
            loadError={settingsError}
            onTextSettingsChange={(settings) => {
              setTextModelSettings(settings);
              setSettingsError(null);
            }}
            onImageSettingsChange={(settings) => {
              setImageModelSettings(settings);
              setSettingsError(null);
            }}
            onVideoSettingsChange={(settings) => {
              setVideoModelSettings(settings);
              setVideoBackendSettings((current) => current ? {
                ...current,
                apiConfigured: settings.configured,
                configured: current.activeBackend === "api" ? settings.configured : current.configured,
              } : current);
              setSettingsError(null);
            }}
            onComfyUIVideoSettingsChange={(settings) => {
              setComfyUIVideoSettings(settings);
              setVideoBackendSettings((current) => current ? {
                ...current,
                comfyuiConfigured: settings.configured,
                configured: current.activeBackend === "comfyui" ? settings.configured : current.configured,
              } : current);
              setSettingsError(null);
            }}
            onVideoBackendSettingsChange={(settings) => {
              setVideoBackendSettings(settings);
              setSettingsError(null);
            }}
          />
        ) : activePage === "storyboard" ? (
          <StoryboardWorkspace
            project={currentProject}
            onBack={() => setActivePage("workspace")}
            onOpenScreenplay={() => setActivePage("source")}
          />
        ) : activePage === "assets" ? (
          <AssetWorkspace
            project={currentProject}
            onBack={() => setActivePage("workspace")}
            onOpenScreenplay={() => setActivePage("source")}
            onOpenApiSettings={() => setActivePage("api")}
            onAssetsReady={() => updateStage("assets")}
            imageModelConfigured={imageModelSettings?.configured ?? false}
          />
        ) : activePage === "video" ? (
          <VideoWorkspace
            project={currentProject}
            onBack={() => setActivePage("workspace")}
            onOpenAssets={() => setActivePage("assets")}
            onOpenApiSettings={() => setActivePage("api")}
            onOpenTasks={() => setActivePage("tasks")}
            onPlanReady={() => updateStage("video")}
            videoModelConfigured={videoBackendSettings?.configured ?? false}
            activeVideoBackend={videoBackendSettings?.activeBackend ?? "api"}
          />
        ) : activePage === "sync" ? (
          <SyncSettings />
        ) : activePage === "tasks" ? (
          <TaskCenter
            project={currentProject}
            onBack={() => setActivePage("workspace")}
            onOpenAssets={() => setActivePage("assets")}
          />
        ) : (
          <PlaceholderPage title={PAGE_TITLES[activePage]} onBack={() => setActivePage("workspace")} />
        )}
      </div>
      <CreateProjectDialog
        open={createDialogOpen}
        onClose={() => setCreateDialogOpen(false)}
        onCreate={createProject}
      />
    </div>
  );
}
