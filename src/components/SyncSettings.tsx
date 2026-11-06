import {
  AlertTriangle,
  CheckCircle2,
  Cloud,
  DatabaseBackup,
  DownloadCloud,
  RefreshCw,
  ShieldCheck,
  UploadCloud,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";
import {
  getSyncStatus,
  pullSyncSnapshot,
  pushSyncSnapshot,
  saveSyncSettings,
} from "../lib/api";
import type { SyncState, SyncStatus } from "../types";

const STATE_LABELS: Record<SyncState, string> = {
  disabled: "尚未启用",
  ready: "同步正常",
  syncing: "正在同步",
  conflict: "需要选择版本",
  error: "同步异常",
};

function formatTime(value: string | null) {
  if (!value) return "尚未同步";
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).format(new Date(value));
}

export function SyncSettings() {
  const [status, setStatus] = useState<SyncStatus | null>(null);
  const [folderPath, setFolderPath] = useState("");
  const [deviceName, setDeviceName] = useState("");
  const [enabled, setEnabled] = useState(false);
  const [working, setWorking] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const formInitialized = useRef(false);

  const applyStatus = (nextStatus: SyncStatus, initializeForm = false) => {
    setStatus(nextStatus);
    if (initializeForm || !formInitialized.current) {
      setFolderPath(nextStatus.folderPath);
      setDeviceName(nextStatus.deviceName);
      setEnabled(nextStatus.enabled);
      formInitialized.current = true;
    }
  };

  useEffect(() => {
    let active = true;
    const load = async () => {
      try {
        const nextStatus = await getSyncStatus();
        if (active) applyStatus(nextStatus);
      } catch (loadError: unknown) {
        if (active) {
          setError(loadError instanceof Error ? loadError.message : "同步状态读取失败");
        }
      }
    };
    void load();
    const timer = window.setInterval(load, 5000);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, []);

  const hasChanges = Boolean(
    status
      && (
        folderPath.trim() !== status.folderPath
        || deviceName.trim() !== status.deviceName
        || enabled !== status.enabled
      ),
  );

  const save = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (working || !hasChanges) return;
    setWorking(true);
    setMessage(null);
    setError(null);
    try {
      const nextStatus = await saveSyncSettings({
        folderPath: folderPath.trim(),
        deviceName: deviceName.trim(),
        enabled,
      });
      applyStatus(nextStatus, true);
      setMessage(
        nextStatus.enabled
          ? "同步配置已保存；平台会在启动和数据变化时自动同步。"
          : "跨设备同步已关闭，本机数据保持不变。",
      );
    } catch (saveError: unknown) {
      setError(saveError instanceof Error ? saveError.message : "同步配置保存失败");
    } finally {
      setWorking(false);
    }
  };

  const push = async (force: boolean) => {
    if (working) return;
    if (force && !window.confirm("确定用本机版本覆盖云端最新版吗？另一台电脑未同步的修改将无法保留。")) {
      return;
    }
    setWorking(true);
    setMessage(null);
    setError(null);
    try {
      applyStatus(await pushSyncSnapshot(force));
      setMessage("本机数据库与新增素材已经同步到共享云盘。");
    } catch (pushError: unknown) {
      setError(pushError instanceof Error ? pushError.message : "上传同步失败");
    } finally {
      setWorking(false);
    }
  };

  const pull = async (force: boolean) => {
    if (working) return;
    if (force && !window.confirm("确定放弃本机未同步修改，改用云端最新版吗？")) {
      return;
    }
    setWorking(true);
    setMessage(null);
    setError(null);
    try {
      await pullSyncSnapshot(force);
      window.location.reload();
    } catch (pullError: unknown) {
      setError(pullError instanceof Error ? pullError.message : "获取云端版本失败");
      setWorking(false);
    }
  };

  const state = status?.state ?? "disabled";
  const isHealthy = state === "ready";

  return (
    <main className="api-settings-page sync-settings-page">
      <header className="settings-heading">
        <div>
          <h1>跨设备同步</h1>
          <p>两台电脑通过同一个云盘目录接续数据库、资产图片和生成视频。</p>
        </div>
        <div className={isHealthy ? "model-status configured" : "model-status"}>
          {isHealthy ? <CheckCircle2 size={18} /> : state === "conflict" ? <AlertTriangle size={18} /> : <Cloud size={18} />}
          <span>{STATE_LABELS[state]}</span>
        </div>
      </header>

      {status?.error ? <div className="service-alert sync-alert" role="alert">{status.error}</div> : null}

      <div className="sync-overview" aria-label="同步状态概览">
        <div>
          <RefreshCw size={18} />
          <span>最后同步</span>
          <strong>{formatTime(status?.lastSyncedAt ?? null)}</strong>
        </div>
        <div>
          <Cloud size={18} />
          <span>云端最新版</span>
          <strong>{formatTime(status?.latestUpdatedAt ?? null)}</strong>
        </div>
        <div>
          <DatabaseBackup size={18} />
          <span>最新设备</span>
          <strong>{status?.latestDeviceName || "尚无云端版本"}</strong>
        </div>
      </div>

      <div className="settings-layout">
        <form className="settings-form" onSubmit={save}>
          <div className="settings-section-heading">
            <Cloud size={20} />
            <div>
              <h2>共享云盘目录</h2>
              <p>两台电脑分别填写各自电脑上、指向同一个云盘文件夹的本地路径。</p>
            </div>
          </div>

          <label className="settings-field">
            <span>这台电脑的名称</span>
            <input
              value={deviceName}
              onChange={(event) => setDeviceName(event.target.value)}
              placeholder="例如：工作室 MacBook"
              required
            />
            <small>冲突提示会用这个名称标明最后由哪台电脑更新。</small>
          </label>

          <label className="settings-field">
            <span>云盘同步目录</span>
            <input
              value={folderPath}
              onChange={(event) => setFolderPath(event.target.value)}
              placeholder="例如：/Users/你/Library/CloudStorage/OneDrive"
              required={enabled}
            />
            <small>可使用 OneDrive、Dropbox、Google Drive 或其他会自动同步的本地文件夹。平台会在其中创建 MingyanAI-Sync。</small>
          </label>

          {status?.suggestedFolders.length ? (
            <div className="sync-folder-suggestions">
              <span>检测到的云盘</span>
              <div>
                {status.suggestedFolders.map((folder) => (
                  <button
                    key={folder.path}
                    className={folderPath === folder.path ? "selected" : ""}
                    type="button"
                    onClick={() => setFolderPath(folder.path)}
                  >
                    <Cloud size={15} />
                    {folder.label}
                  </button>
                ))}
              </div>
            </div>
          ) : null}

          <label className="settings-checkbox-field sync-enable-field">
            <input
              type="checkbox"
              checked={enabled}
              onChange={(event) => setEnabled(event.target.checked)}
            />
            <span>
              <strong>启用自动跨设备同步</strong>
              <small>启动时自动获取最新版；项目、资产或任务变化后自动推送快照。</small>
            </span>
          </label>

          {error ? <p className="form-error" role="alert">{error}</p> : null}
          {message ? <p className="settings-success" role="status">{message}</p> : null}

          <div className="settings-actions sync-actions">
            <button
              className="button secondary"
              type="button"
              disabled={!status?.enabled || working}
              onClick={() => pull(false)}
            >
              <DownloadCloud size={17} />
              获取云端最新版
            </button>
            <button
              className="button secondary"
              type="button"
              disabled={!status?.enabled || working}
              onClick={() => push(false)}
            >
              <UploadCloud size={17} />
              立即同步
            </button>
            <button className="button primary" type="submit" disabled={!hasChanges || working}>
              <ShieldCheck size={17} />
              {working ? "正在处理…" : "保存同步设置"}
            </button>
          </div>

          {state === "conflict" ? (
            <div className="sync-conflict-actions">
              <strong>请选择要保留的版本</strong>
              <p>系统不会自动覆盖任意一台电脑上的修改。</p>
              <div>
                <button className="button secondary" type="button" disabled={working} onClick={() => pull(true)}>
                  使用云端版本
                </button>
                <button className="button warning" type="button" disabled={working} onClick={() => push(true)}>
                  保留本机并覆盖云端
                </button>
              </div>
            </div>
          ) : null}
        </form>

        <aside className="credential-note sync-note">
          <div className="credential-note-icon"><ShieldCheck size={23} /></div>
          <h2>安全的快照同步</h2>
          <p>平台不会直接在云盘里打开 SQLite，而是先生成完整快照，再原子替换，避免同步到一半造成数据库损坏。</p>
          <p className="credential-test-note">API 密钥不会上传云盘。你只需在每台电脑首次使用时分别填写一次。</p>
          <dl>
            <div><dt>本机状态</dt><dd>{status?.dirty ? "有待同步修改" : "已与快照一致"}</dd></div>
            <div><dt>本机设备</dt><dd>{status?.deviceName || "正在读取"}</dd></div>
            <div><dt>同步内容</dt><dd>项目、图片、视频</dd></div>
            <div><dt>不上传</dt><dd>API 密钥</dd></div>
          </dl>
        </aside>
      </div>
    </main>
  );
}
