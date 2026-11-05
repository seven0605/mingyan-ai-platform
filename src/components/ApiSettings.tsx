import {
  CheckCircle2,
  CloudCog,
  Eye,
  EyeOff,
  FileText,
  Image,
  KeyRound,
  LockKeyhole,
  Server,
  Upload,
  Video,
} from "lucide-react";
import { useEffect, useState } from "react";
import {
  saveComfyUIVideoSettings,
  saveImageModelSettings,
  saveTextModelSettings,
  saveVideoBackend,
  saveVideoModelSettings,
  testComfyUIVideoConnection,
  testImageModelConnection,
  testTextModelConnection,
  testVideoModelConnection,
} from "../lib/api";
import type {
  ComfyUIVideoSettings,
  ImageModelSettings,
  TextModelConnection,
  TextModelSettings,
  VideoModelSettings,
  VideoBackendSettings,
} from "../types";

interface ApiSettingsProps {
  textSettings: TextModelSettings | null;
  imageSettings: ImageModelSettings | null;
  videoSettings: VideoModelSettings | null;
  comfyUIVideoSettings: ComfyUIVideoSettings | null;
  videoBackendSettings: VideoBackendSettings | null;
  loadError: string | null;
  onTextSettingsChange: (settings: TextModelSettings) => void;
  onImageSettingsChange: (settings: ImageModelSettings) => void;
  onVideoSettingsChange: (settings: VideoModelSettings) => void;
  onComfyUIVideoSettingsChange: (settings: ComfyUIVideoSettings) => void;
  onVideoBackendSettingsChange: (settings: VideoBackendSettings) => void;
}

type SettingsTab = "text" | "image" | "video";

const IMAGE_DEFAULT_BASE_URL = "https://api.lk888.ai/v1";
const IMAGE_DEFAULT_MODEL = "tt-image-2.5";
const VIDEO_DEFAULT_BASE_URL = "https://shuikule.top/v1";
const VIDEO_DEFAULT_MODEL = "BD Seedance2.5";

export function ApiSettings({
  textSettings,
  imageSettings,
  videoSettings,
  comfyUIVideoSettings,
  videoBackendSettings,
  loadError,
  onTextSettingsChange,
  onImageSettingsChange,
  onVideoSettingsChange,
  onComfyUIVideoSettingsChange,
  onVideoBackendSettingsChange,
}: ApiSettingsProps) {
  const [activeTab, setActiveTab] = useState<SettingsTab>("image");
  const [baseUrl, setBaseUrl] = useState(IMAGE_DEFAULT_BASE_URL);
  const [model, setModel] = useState(IMAGE_DEFAULT_MODEL);
  const [apiKey, setApiKey] = useState("");
  const [workflowName, setWorkflowName] = useState("MiniMax H3 · 15秒 API 工作流");
  const [workflowJson, setWorkflowJson] = useState("");
  const [allowInsecureTls, setAllowInsecureTls] = useState(false);
  const [showKey, setShowKey] = useState(false);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [switchingBackend, setSwitchingBackend] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [testResult, setTestResult] = useState<TextModelConnection | null>(null);

  const activeVideoBackend = videoBackendSettings?.activeBackend ?? "api";
  const isComfyVideo = activeTab === "video" && activeVideoBackend === "comfyui";
  const settings = activeTab === "image"
    ? imageSettings
    : activeTab === "video"
      ? isComfyVideo ? comfyUIVideoSettings : videoSettings
      : textSettings;
  const isImage = activeTab === "image";
  const isVideo = activeTab === "video";

  useEffect(() => {
    if (activeTab === "image") {
      setBaseUrl(imageSettings?.baseUrl || IMAGE_DEFAULT_BASE_URL);
      setModel(imageSettings?.model || IMAGE_DEFAULT_MODEL);
      return;
    }
    if (activeTab === "video") {
      if (isComfyVideo) {
        setBaseUrl(comfyUIVideoSettings?.baseUrl || "");
        setModel("MiniMax H3");
        setWorkflowName(comfyUIVideoSettings?.workflowName || "MiniMax H3 · 15秒 API 工作流");
        setWorkflowJson(comfyUIVideoSettings?.workflowJson || "");
        setAllowInsecureTls(comfyUIVideoSettings?.allowInsecureTls ?? false);
      } else {
        setBaseUrl(videoSettings?.baseUrl || VIDEO_DEFAULT_BASE_URL);
        setModel(videoSettings?.model || VIDEO_DEFAULT_MODEL);
      }
      return;
    }
    setBaseUrl(textSettings?.baseUrl || "");
    setModel(textSettings?.model || "");
  }, [activeTab, comfyUIVideoSettings, imageSettings, isComfyVideo, textSettings, videoSettings]);

  const hasCredential = "hasCredential" in (settings ?? {})
    ? Boolean((settings as TextModelSettings | ImageModelSettings | VideoModelSettings).hasCredential)
    : false;
  const hasUnsavedChanges = isComfyVideo
    ? Boolean(
      baseUrl.trim() !== comfyUIVideoSettings?.baseUrl
      || workflowName.trim() !== comfyUIVideoSettings?.workflowName
      || workflowJson.trim() !== comfyUIVideoSettings?.workflowJson
      || allowInsecureTls !== comfyUIVideoSettings?.allowInsecureTls,
    )
    : Boolean(
      baseUrl.trim() !== settings?.baseUrl || model.trim() !== settings?.model || apiKey.trim(),
    );
  const canSave = isComfyVideo
    ? Boolean(baseUrl.trim() && workflowName.trim() && workflowJson.trim() && hasUnsavedChanges && !saving)
    : Boolean(
      baseUrl.trim()
        && model.trim()
        && (hasCredential || apiKey.trim())
        && hasUnsavedChanges
        && !saving,
    );
  const canTest = Boolean(settings?.configured && !hasUnsavedChanges && !saving && !testing);

  const switchTab = (tab: SettingsTab) => {
    if (tab === activeTab) return;
    setActiveTab(tab);
    setApiKey("");
    setShowKey(false);
    setMessage(null);
    setError(null);
    setTestResult(null);
  };

  const switchVideoBackend = async (backend: "api" | "comfyui") => {
    if (backend === activeVideoBackend || switchingBackend) return;
    setSwitchingBackend(true);
    setMessage(null);
    setError(null);
    setTestResult(null);
    try {
      onVideoBackendSettingsChange(await saveVideoBackend(backend));
      setApiKey("");
      setShowKey(false);
    } catch (switchError: unknown) {
      setError(switchError instanceof Error ? switchError.message : "视频通道切换失败");
    } finally {
      setSwitchingBackend(false);
    }
  };

  const save = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!canSave) return;
    setSaving(true);
    setMessage(null);
    setError(null);
    setTestResult(null);
    try {
      const input = {
        baseUrl: baseUrl.trim(),
        model: model.trim(),
        ...(apiKey.trim() ? { apiKey: apiKey.trim() } : {}),
      };
      if (isImage) {
        onImageSettingsChange(await saveImageModelSettings(input));
        setMessage("图像模型配置已安全保存，可以进行免生图连接测试。");
      } else if (isVideo) {
        if (isComfyVideo) {
          onComfyUIVideoSettingsChange(await saveComfyUIVideoSettings({
            baseUrl: baseUrl.trim(),
            workflowName: workflowName.trim(),
            workflowJson: workflowJson.trim(),
            allowInsecureTls,
          }));
          setMessage("云端 ComfyUI H3 配置已保存，可以进行免生成连接测试。");
        } else {
          onVideoSettingsChange(await saveVideoModelSettings(input));
          setMessage("视频 API 配置已安全保存，可以进行免生成连接测试。");
        }
      } else {
        onTextSettingsChange(await saveTextModelSettings(input));
        setMessage("文本模型配置已安全保存，后续文本与剧本任务将使用这个模型。");
      }
      setApiKey("");
      setShowKey(false);
    } catch (saveError: unknown) {
      setError(saveError instanceof Error ? saveError.message : "模型配置保存失败");
    } finally {
      setSaving(false);
    }
  };

  const testConnection = async () => {
    if (!canTest) return;
    setTesting(true);
    setError(null);
    setMessage(null);
    setTestResult(null);
    try {
      setTestResult(
        isImage
          ? await testImageModelConnection()
          : isVideo
            ? isComfyVideo
              ? await testComfyUIVideoConnection()
              : await testVideoModelConnection()
            : await testTextModelConnection(),
      );
    } catch (testError: unknown) {
      setError(testError instanceof Error ? testError.message : "模型连接测试失败");
    } finally {
      setTesting(false);
    }
  };

  return (
    <main className="api-settings-page">
      <header className="settings-heading">
        <div>
          <h1>API 设置</h1>
          <p>管理剧本、图像与视频服务；视频可在第三方 API 和自有云端 H3 之间切换。</p>
        </div>
        <div className={settings?.configured ? "model-status configured" : "model-status"}>
          {settings?.configured ? <CheckCircle2 size={18} /> : <Server size={18} />}
          <span>{isImage ? "图像模型" : isVideo ? "视频模型" : "文本模型"}{settings?.configured ? "已配置" : "未配置"}</span>
        </div>
      </header>

      {loadError ? <div className="service-alert settings-alert" role="alert">{loadError}</div> : null}

      <div className="settings-model-tabs" role="tablist" aria-label="模型配置类型">
        <button
          type="button"
          className={activeTab === "text" ? "settings-model-tab active" : "settings-model-tab"}
          role="tab"
          aria-selected={activeTab === "text"}
          onClick={() => switchTab("text")}
        >
          <FileText size={18} />
          <span><strong>文本与剧本模型</strong><small>{textSettings?.configured ? "已配置" : "未配置"}</small></span>
        </button>
        <button
          type="button"
          className={activeTab === "image" ? "settings-model-tab active" : "settings-model-tab"}
          role="tab"
          aria-selected={activeTab === "image"}
          onClick={() => switchTab("image")}
        >
          <Image size={18} />
          <span><strong>图像生成模型</strong><small>{imageSettings?.configured ? "已配置" : "未配置"}</small></span>
        </button>
        <button
          type="button"
          className={activeTab === "video" ? "settings-model-tab active" : "settings-model-tab"}
          role="tab"
          aria-selected={activeTab === "video"}
          onClick={() => switchTab("video")}
        >
          <Video size={18} />
          <span><strong>视频生成模型</strong><small>{videoBackendSettings?.configured ? "已配置" : "未配置"}</small></span>
        </button>
      </div>

      {isVideo ? (
        <div className="video-backend-switch" aria-label="视频生成通道">
          <button
            type="button"
            className={activeVideoBackend === "api" ? "active" : ""}
            onClick={() => switchVideoBackend("api")}
            disabled={switchingBackend}
          >
            <Video size={19} />
            <span><strong>视频 API</strong><small>BD Seedance2.5 · 单条 30 秒</small></span>
            <em>{videoBackendSettings?.apiConfigured ? "已配置" : "未配置"}</em>
          </button>
          <button
            type="button"
            className={activeVideoBackend === "comfyui" ? "active" : ""}
            onClick={() => switchVideoBackend("comfyui")}
            disabled={switchingBackend}
          >
            <CloudCog size={19} />
            <span><strong>云端 ComfyUI H3</strong><small>自租 GPU · 单条最长 15 秒</small></span>
            <em>{videoBackendSettings?.comfyuiConfigured ? "已配置" : "未配置"}</em>
          </button>
        </div>
      ) : null}

      <div className="settings-layout">
        <form className="settings-form" onSubmit={save}>
          <div className="settings-section-heading">
            {isImage ? <Image size={20} /> : isComfyVideo ? <CloudCog size={20} /> : isVideo ? <Video size={20} /> : <Server size={20} />}
            <div>
              <h2>{isImage ? "不鸣AI · TT Image 2.5" : isComfyVideo ? "自有云端 · ComfyUI MiniMax H3" : isVideo ? "睡哭了 · BD Seedance2.5" : "OpenAI 兼容文本接口"}</h2>
              <p>{isImage ? "用于角色、场景与物品参考图；支持后续接入文生图和参考图编辑。" : isComfyVideo ? "参考图直接上传到你的云端实例，不经过第三方视频 API；任务自动按 15 秒拆分。" : isVideo ? "用于 720p、4–30 秒的视频生成；正式生成前需准备公网可读的参考素材。" : "用于小说分析、剧本改编和分镜提示词生成。"}</p>
            </div>
          </div>

          <label className="settings-field">
            <span>接口地址</span>
            <input
              type="url"
              value={baseUrl}
              onChange={(event) => setBaseUrl(event.target.value)}
              placeholder={isImage ? IMAGE_DEFAULT_BASE_URL : isComfyVideo ? "https://你的6006映射地址" : isVideo ? VIDEO_DEFAULT_BASE_URL : "https://api.example.com/v1"}
              autoComplete="url"
              required
            />
            <small>{isImage ? "已按不鸣AI接入文档预填，通常无需修改。" : isComfyVideo ? "填写 AutoDL 自定义服务中的 6006 HTTP 映射地址；不要把这个地址分享给他人。" : isVideo ? "已按睡哭了接口文档预填，通常无需修改。" : "填写服务商提供的兼容接口根地址。"}</small>
          </label>

          {!isComfyVideo ? <label className="settings-field">
            <span>模型 ID</span>
            <input
              value={model}
              onChange={(event) => setModel(event.target.value)}
              placeholder={isImage ? IMAGE_DEFAULT_MODEL : isVideo ? VIDEO_DEFAULT_MODEL : "例如：deepseek-chat"}
              autoComplete="off"
              required
            />
            <small>{isImage ? "已预填 tt-image-2.5，必须与服务商后台显示的 ID 一致。" : isVideo ? "已预填 BD Seedance2.5；中间空格和大小写必须保持不变。" : "必须与服务商文档中的模型 ID 完全一致。"}</small>
          </label> : null}

          {!isComfyVideo ? <label className="settings-field">
            <span>API 密钥</span>
            <div className="secret-input">
              <input
                type={showKey ? "text" : "password"}
                value={apiKey}
                onChange={(event) => setApiKey(event.target.value)}
                placeholder={hasCredential ? "已安全保存；留空则不修改" : "粘贴服务商提供的 API Key"}
                autoComplete="new-password"
                required={!hasCredential}
              />
              <button
                type="button"
                onClick={() => setShowKey((visible) => !visible)}
                aria-label={showKey ? "隐藏密钥" : "显示密钥"}
              >
                {showKey ? <EyeOff size={18} /> : <Eye size={18} />}
              </button>
            </div>
            <small>已保存的密钥不会回传到浏览器，也不会写入项目数据库。</small>
          </label> : (
            <>
              <label className="settings-field">
                <span>工作流名称</span>
                <input
                  value={workflowName}
                  onChange={(event) => setWorkflowName(event.target.value)}
                  placeholder="MiniMax H3 · 15秒 API 工作流"
                  autoComplete="off"
                  required
                />
              </label>
              <label className="settings-field workflow-field">
                <span>ComfyUI API 工作流 JSON</span>
                <input
                  className="workflow-file-input"
                  type="file"
                  accept="application/json,.json"
                  onChange={async (event) => {
                    const file = event.target.files?.[0];
                    if (!file) return;
                    setWorkflowName(file.name.replace(/\.json$/i, ""));
                    setWorkflowJson(await file.text());
                  }}
                />
                <span className="workflow-upload-hint"><Upload size={15} />选择 ComfyUI “导出（API 格式）”的 JSON 文件</span>
                <textarea
                  value={workflowJson}
                  onChange={(event) => setWorkflowJson(event.target.value)}
                  placeholder={'在工作流中把提示词改为 {{prompt}}，第一张参考图改为 {{reference_1}}；还可使用 {{reference_2}}、{{seconds}}、{{width}}、{{height}}、{{seed}}。'}
                  spellCheck={false}
                  required
                />
                <small>必须使用 API 格式工作流，不是普通界面工作流。至少包含 {"{{prompt}}"} 和 {"{{reference_1}}"}；MP4 必须由 SaveVideo 节点输出。</small>
              </label>
              <label className="settings-checkbox-field">
                <input
                  type="checkbox"
                  checked={allowInsecureTls}
                  onChange={(event) => setAllowInsecureTls(event.target.checked)}
                />
                <span>
                  <strong>允许当前云机使用自签名 HTTPS 证书</strong>
                  <small>仅在 AutoDL 地址出现证书校验失败时开启；只影响这个 ComfyUI 连接。</small>
                </span>
              </label>
            </>
          )}

          {error ? <p className="form-error" role="alert">{error}</p> : null}
          {message ? <p className="settings-success" role="status">{message}</p> : null}
          {testResult ? (
            <p className="connection-success" role="status">
              <CheckCircle2 size={15} />
              {testResult.message} · {testResult.model} · {testResult.latencyMs} ms
            </p>
          ) : null}

          <div className="settings-actions">
            <button className="button secondary" type="button" disabled={!canTest} onClick={testConnection}>
              <Server size={17} />
              {testing ? "正在测试…" : isImage ? "免生图测试连接" : isComfyVideo ? "测试 ComfyUI 与工作流" : isVideo ? "免生成测试连接" : "测试连接"}
            </button>
            <button className="button primary" type="submit" disabled={!canSave}>
              <KeyRound size={17} />
              {saving ? "正在保存…" : settings?.configured ? "更新配置" : "保存配置"}
            </button>
          </div>
        </form>

        <aside className="credential-note">
          <div className="credential-note-icon"><LockKeyhole size={23} /></div>
          <h2>{isComfyVideo ? "云端实例由你掌控" : "密钥保存在系统凭据库"}</h2>
          <p>{isComfyVideo ? "平台只保存 6006 映射地址和工作流；参考图会直接上传到你的 ComfyUI input 目录。" : "macOS 使用钥匙串，Windows 使用凭据管理器。SQLite 只记录接口地址和模型名称。"}</p>
          {isImage || isVideo ? <p className="credential-test-note">{isComfyVideo ? "连接测试只读取 ComfyUI 系统状态，不会运行 H3 工作流或产生云端算力任务。" : `连接测试只读取服务商模型列表，不会生成${isImage ? "图片" : "视频"}，也不会消耗生成额度。`}</p> : null}
          {isVideo && !isComfyVideo ? <p className="credential-test-note">正式生成时会自动建立白名单临时 HTTPS 通道；任务完成或失败后立即关闭。</p> : null}
          {isComfyVideo ? <p className="credential-test-note">H3 官方开源版单条最长 15 秒；平台会自动拆分，不会把 Seedance 的 30 秒规则套到 H3。</p> : null}
          <dl>
            <div><dt>服务商</dt><dd>{isImage ? "不鸣AI" : isComfyVideo ? "自有云端 ComfyUI" : isVideo ? "睡哭了" : "OpenAI 兼容"}</dd></div>
            <div><dt>模型</dt><dd>{model || "尚未填写"}</dd></div>
            <div><dt>{isComfyVideo ? "工作流" : "凭据状态"}</dt><dd>{isComfyVideo ? comfyUIVideoSettings?.workflowConfigured ? "已导入" : "尚未导入" : hasCredential ? "已安全保存" : "尚未保存"}</dd></div>
            <div><dt>数据位置</dt><dd>{isComfyVideo ? "本机 + 你的云端" : "仅限这台电脑"}</dd></div>
          </dl>
        </aside>
      </div>
    </main>
  );
}
