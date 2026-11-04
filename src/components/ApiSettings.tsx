import {
  CheckCircle2,
  Eye,
  EyeOff,
  FileText,
  Image,
  KeyRound,
  LockKeyhole,
  Server,
} from "lucide-react";
import { useEffect, useState } from "react";
import {
  saveImageModelSettings,
  saveTextModelSettings,
  testImageModelConnection,
  testTextModelConnection,
} from "../lib/api";
import type {
  ImageModelSettings,
  TextModelConnection,
  TextModelSettings,
} from "../types";

interface ApiSettingsProps {
  textSettings: TextModelSettings | null;
  imageSettings: ImageModelSettings | null;
  loadError: string | null;
  onTextSettingsChange: (settings: TextModelSettings) => void;
  onImageSettingsChange: (settings: ImageModelSettings) => void;
}

type SettingsTab = "text" | "image";

const IMAGE_DEFAULT_BASE_URL = "https://api.lk888.ai/v1";
const IMAGE_DEFAULT_MODEL = "tt-image-2.5";

export function ApiSettings({
  textSettings,
  imageSettings,
  loadError,
  onTextSettingsChange,
  onImageSettingsChange,
}: ApiSettingsProps) {
  const [activeTab, setActiveTab] = useState<SettingsTab>("image");
  const [baseUrl, setBaseUrl] = useState(IMAGE_DEFAULT_BASE_URL);
  const [model, setModel] = useState(IMAGE_DEFAULT_MODEL);
  const [apiKey, setApiKey] = useState("");
  const [showKey, setShowKey] = useState(false);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [testResult, setTestResult] = useState<TextModelConnection | null>(null);

  const settings = activeTab === "image" ? imageSettings : textSettings;
  const isImage = activeTab === "image";

  useEffect(() => {
    if (activeTab === "image") {
      setBaseUrl(imageSettings?.baseUrl || IMAGE_DEFAULT_BASE_URL);
      setModel(imageSettings?.model || IMAGE_DEFAULT_MODEL);
      return;
    }
    setBaseUrl(textSettings?.baseUrl || "");
    setModel(textSettings?.model || "");
  }, [activeTab, imageSettings, textSettings]);

  const hasUnsavedChanges = Boolean(
    baseUrl.trim() !== settings?.baseUrl || model.trim() !== settings?.model || apiKey.trim(),
  );
  const canSave = Boolean(
    baseUrl.trim()
      && model.trim()
      && (settings?.hasCredential || apiKey.trim())
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
        isImage ? await testImageModelConnection() : await testTextModelConnection(),
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
          <p>分别管理剧本创作与图像生成服务，所有密钥只保存在本机系统凭据库。</p>
        </div>
        <div className={settings?.configured ? "model-status configured" : "model-status"}>
          {settings?.configured ? <CheckCircle2 size={18} /> : <Server size={18} />}
          <span>{isImage ? "图像模型" : "文本模型"}{settings?.configured ? "已配置" : "未配置"}</span>
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
      </div>

      <div className="settings-layout">
        <form className="settings-form" onSubmit={save}>
          <div className="settings-section-heading">
            {isImage ? <Image size={20} /> : <Server size={20} />}
            <div>
              <h2>{isImage ? "不鸣AI · TT Image 2.5" : "OpenAI 兼容文本接口"}</h2>
              <p>{isImage ? "用于角色、场景与物品参考图；支持后续接入文生图和参考图编辑。" : "用于小说分析、剧本改编和分镜提示词生成。"}</p>
            </div>
          </div>

          <label className="settings-field">
            <span>接口地址</span>
            <input
              type="url"
              value={baseUrl}
              onChange={(event) => setBaseUrl(event.target.value)}
              placeholder={isImage ? IMAGE_DEFAULT_BASE_URL : "https://api.example.com/v1"}
              autoComplete="url"
              required
            />
            <small>{isImage ? "已按不鸣AI接入文档预填，通常无需修改。" : "填写服务商提供的兼容接口根地址。"}</small>
          </label>

          <label className="settings-field">
            <span>模型 ID</span>
            <input
              value={model}
              onChange={(event) => setModel(event.target.value)}
              placeholder={isImage ? IMAGE_DEFAULT_MODEL : "例如：deepseek-chat"}
              autoComplete="off"
              required
            />
            <small>{isImage ? "已预填 tt-image-2.5，必须与服务商后台显示的 ID 一致。" : "必须与服务商文档中的模型 ID 完全一致。"}</small>
          </label>

          <label className="settings-field">
            <span>API 密钥</span>
            <div className="secret-input">
              <input
                type={showKey ? "text" : "password"}
                value={apiKey}
                onChange={(event) => setApiKey(event.target.value)}
                placeholder={settings?.hasCredential ? "已安全保存；留空则不修改" : "粘贴服务商提供的 API Key"}
                autoComplete="new-password"
                required={!settings?.hasCredential}
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
          </label>

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
              {testing ? "正在测试…" : isImage ? "免生图测试连接" : "测试连接"}
            </button>
            <button className="button primary" type="submit" disabled={!canSave}>
              <KeyRound size={17} />
              {saving ? "正在保存…" : settings?.configured ? "更新配置" : "保存配置"}
            </button>
          </div>
        </form>

        <aside className="credential-note">
          <div className="credential-note-icon"><LockKeyhole size={23} /></div>
          <h2>密钥保存在系统凭据库</h2>
          <p>macOS 使用钥匙串，Windows 使用凭据管理器。SQLite 只记录接口地址和模型名称。</p>
          {isImage ? <p className="credential-test-note">连接测试只读取服务商模型列表，不会生成图片，也不会消耗生图额度。</p> : null}
          <dl>
            <div><dt>服务商</dt><dd>{isImage ? "不鸣AI" : "OpenAI 兼容"}</dd></div>
            <div><dt>模型</dt><dd>{model || "尚未填写"}</dd></div>
            <div><dt>凭据状态</dt><dd>{settings?.hasCredential ? "已安全保存" : "尚未保存"}</dd></div>
            <div><dt>数据位置</dt><dd>仅限这台电脑</dd></div>
          </dl>
        </aside>
      </div>
    </main>
  );
}
