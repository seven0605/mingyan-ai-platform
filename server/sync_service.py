from __future__ import annotations

import json
import os
import platform
import shutil
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4


SYNC_FOLDER_NAME = "MingyanAI-Sync"


class SyncConflictError(RuntimeError):
    pass


class SyncNotReadyError(RuntimeError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_timestamp(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
        return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return datetime.min.replace(tzinfo=timezone.utc)


class CrossDeviceSync:
    def __init__(self, data_dir: Path, database_path: Path) -> None:
        self.data_dir = data_dir
        self.database_path = database_path
        self.config_path = data_dir / "sync-device.json"
        self.generated_dir = data_dir / "generated"
        self._lock = threading.RLock()
        self._timer: threading.Timer | None = None
        self._state = "disabled"
        self._error = ""
        self._config = self._load_config()
        if self._config["enabled"]:
            self._state = "ready"

    def _default_config(self) -> dict[str, object]:
        return {
            "schemaVersion": 1,
            "deviceId": str(uuid4()),
            "deviceName": platform.node() or "这台电脑",
            "folderPath": "",
            "enabled": False,
            "lastSyncedAt": "",
            "lastRemoteDeviceId": "",
            "dirty": False,
        }

    def _load_config(self) -> dict[str, object]:
        config = self._default_config()
        if not self.config_path.is_file():
            return config
        try:
            saved = json.loads(self.config_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return config
        if not isinstance(saved, dict):
            return config
        for key in config:
            if key in saved:
                config[key] = saved[key]
        try:
            UUID(str(config["deviceId"]))
        except ValueError:
            config["deviceId"] = str(uuid4())
        return config

    def _save_config(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        temporary = self.config_path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(self._config, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(temporary, self.config_path)

    def _sync_root(self) -> Path:
        folder_path = str(self._config["folderPath"]).strip()
        if not folder_path:
            raise SyncNotReadyError("请先选择两台电脑共同使用的云盘目录")
        return Path(folder_path).expanduser().resolve() / SYNC_FOLDER_NAME

    @staticmethod
    def _suggested_folders() -> list[dict[str, str]]:
        home = Path.home()
        candidates: list[tuple[str, Path]] = [
            ("iCloud 云盘", home / "Library/Mobile Documents/com~apple~CloudDocs"),
            ("OneDrive", home / "OneDrive"),
            ("Dropbox", home / "Dropbox"),
            ("Google Drive", home / "Google Drive"),
            ("iCloud Drive", home / "iCloudDrive"),
        ]
        if one_drive := os.environ.get("OneDrive"):
            candidates.insert(1, ("OneDrive", Path(one_drive)))
        cloud_storage = home / "Library/CloudStorage"
        if cloud_storage.is_dir():
            for path in cloud_storage.iterdir():
                if path.name.startswith("GoogleDrive-"):
                    drive_root = next(
                        (
                            path / name
                            for name in ("我的云端硬盘", "My Drive")
                            if (path / name).is_dir()
                        ),
                        path,
                    )
                    candidates.append(("Google Drive", drive_root))
                else:
                    candidates.append((path.name, path))

        suggestions: list[dict[str, str]] = []
        seen: set[Path] = set()
        for label, path in candidates:
            if not str(path) or not path.is_dir():
                continue
            resolved = path.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            suggestions.append({"label": label, "path": str(resolved)})
        return suggestions[:6]

    def _device_dir(self) -> Path:
        return self._sync_root() / "devices" / str(self._config["deviceId"])

    def _read_manifests(self) -> list[dict[str, object]]:
        devices_dir = self._sync_root() / "devices"
        if not devices_dir.is_dir():
            return []
        manifests: list[dict[str, object]] = []
        for path in devices_dir.glob("*/manifest.json"):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                device_id = str(payload["deviceId"])
                UUID(device_id)
                if path.parent.name != device_id or int(payload["schemaVersion"]) != 1:
                    continue
                payload["manifestPath"] = str(path)
                manifests.append(payload)
            except (KeyError, OSError, TypeError, ValueError):
                continue
        return manifests

    def _latest_manifest(self) -> dict[str, object] | None:
        manifests = self._read_manifests()
        return max(
            manifests,
            key=lambda item: parse_timestamp(str(item.get("updatedAt", ""))),
            default=None,
        )

    def _local_has_data(self) -> bool:
        if self.generated_dir.is_dir() and next(self.generated_dir.rglob("*"), None):
            return True
        if not self.database_path.is_file():
            return False
        try:
            with sqlite3.connect(self.database_path) as connection:
                row = connection.execute("SELECT COUNT(*) FROM projects").fetchone()
            return bool(row and row[0])
        except sqlite3.Error:
            return True

    @staticmethod
    def _validate_database(path: Path) -> None:
        try:
            with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as connection:
                result = connection.execute("PRAGMA quick_check").fetchone()
        except sqlite3.Error as error:
            raise SyncNotReadyError("云端数据库快照无法读取，请等待云盘同步完成") from error
        if not result or result[0] != "ok":
            raise SyncNotReadyError("云端数据库快照校验失败，已保留本机数据")

    @staticmethod
    def _copy_generated(source: Path, destination: Path) -> tuple[int, int]:
        if not source.is_dir():
            return 0, 0
        file_count = 0
        total_bytes = 0
        for source_file in source.rglob("*"):
            if not source_file.is_file() or source_file.is_symlink():
                continue
            relative = source_file.relative_to(source)
            destination_file = destination / relative
            source_size = source_file.stat().st_size
            file_count += 1
            total_bytes += source_size
            if destination_file.is_file() and destination_file.stat().st_size == source_size:
                continue
            destination_file.parent.mkdir(parents=True, exist_ok=True)
            temporary = destination_file.with_name(
                f".{destination_file.name}.{uuid4().hex}.tmp"
            )
            shutil.copy2(source_file, temporary)
            os.replace(temporary, destination_file)
        return file_count, total_bytes

    def configure(self, folder_path: str, device_name: str, enabled: bool) -> None:
        with self._lock:
            normalized_name = device_name.strip()
            if not normalized_name:
                raise ValueError("设备名称不能为空")
            normalized_folder = str(Path(folder_path).expanduser().resolve()) if folder_path else ""
            if enabled:
                if not normalized_folder:
                    raise ValueError("启用同步前必须填写云盘目录")
                folder = Path(normalized_folder)
                folder.mkdir(parents=True, exist_ok=True)
                if not folder.is_dir():
                    raise ValueError("同步路径必须是文件夹")
                generated = self.generated_dir.resolve()
                if folder == generated or generated in folder.parents:
                    raise ValueError("同步目录不能放在生成素材目录内部")
            folder_changed = normalized_folder != self._config["folderPath"]
            self._config.update(
                {
                    "folderPath": normalized_folder,
                    "deviceName": normalized_name,
                    "enabled": enabled,
                }
            )
            if folder_changed:
                self._config.update(
                    {
                        "lastSyncedAt": "",
                        "lastRemoteDeviceId": "",
                        "dirty": self._local_has_data(),
                    }
                )
            self._state = "ready" if enabled else "disabled"
            self._error = ""
            self._save_config()
            if not enabled:
                self._cancel_timer()
                return

            latest = self._latest_manifest()
            if latest is None:
                self.push(force=True)
            elif not self._local_has_data():
                self.pull(force=True)
            elif not self._config["lastSyncedAt"]:
                self._state = "conflict"
                self._error = "本机和云端都有项目数据，请选择保留本机或使用云端版本"

    def status(self) -> dict[str, object]:
        with self._lock:
            latest: dict[str, object] | None = None
            if self._config["enabled"]:
                try:
                    latest = self._latest_manifest()
                except (OSError, SyncNotReadyError) as error:
                    self._state = "error"
                    self._error = str(error)
            return {
                "enabled": bool(self._config["enabled"]),
                "folderPath": str(self._config["folderPath"]),
                "deviceId": str(self._config["deviceId"]),
                "deviceName": str(self._config["deviceName"]),
                "state": self._state,
                "dirty": bool(self._config["dirty"]),
                "lastSyncedAt": str(self._config["lastSyncedAt"]) or None,
                "latestDeviceName": str(latest.get("deviceName", "")) if latest else "",
                "latestUpdatedAt": str(latest.get("updatedAt", "")) if latest else None,
                "suggestedFolders": self._suggested_folders(),
                "error": self._error,
            }

    def mark_dirty(self, delay_seconds: float = 3) -> None:
        with self._lock:
            self._config["dirty"] = True
            self._save_config()
            if not self._config["enabled"]:
                return
            self._cancel_timer()
            self._timer = threading.Timer(delay_seconds, self._scheduled_push)
            self._timer.daemon = True
            self._timer.start()

    def _cancel_timer(self) -> None:
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None

    def _scheduled_push(self) -> None:
        try:
            self.push()
        except (OSError, RuntimeError, sqlite3.Error) as error:
            with self._lock:
                self._state = "conflict" if isinstance(error, SyncConflictError) else "error"
                self._error = str(error)

    def push(self, force: bool = False) -> None:
        with self._lock:
            self._cancel_timer()
            if not self._config["enabled"]:
                raise SyncNotReadyError("跨设备同步尚未启用")
            if not self.database_path.is_file():
                raise SyncNotReadyError("本机数据库尚未创建")
            latest = self._latest_manifest()
            last_synced = parse_timestamp(str(self._config["lastSyncedAt"]))
            if (
                not force
                and latest is not None
                and str(latest["deviceId"]) != self._config["deviceId"]
                and parse_timestamp(str(latest["updatedAt"])) > last_synced
            ):
                self._state = "conflict"
                self._error = "另一台电脑有更新版本，已停止覆盖；请先获取云端最新版"
                raise SyncConflictError(self._error)

            self._state = "syncing"
            self._error = ""
            device_dir = self._device_dir()
            device_dir.mkdir(parents=True, exist_ok=True)
            snapshot = device_dir / "mingyan.sqlite3"
            temporary_snapshot = device_dir / f".mingyan.{uuid4().hex}.tmp"
            with sqlite3.connect(self.database_path) as source:
                with sqlite3.connect(temporary_snapshot) as destination:
                    source.backup(destination)
            self._validate_database(temporary_snapshot)
            os.replace(temporary_snapshot, snapshot)

            file_count, total_bytes = self._copy_generated(
                self.generated_dir, self._sync_root() / "generated"
            )
            updated_at = utc_now()
            manifest = {
                "schemaVersion": 1,
                "deviceId": self._config["deviceId"],
                "deviceName": self._config["deviceName"],
                "updatedAt": updated_at,
                "databaseBytes": snapshot.stat().st_size,
                "assetFileCount": file_count,
                "assetBytes": total_bytes,
            }
            manifest_path = device_dir / "manifest.json"
            temporary_manifest = device_dir / ".manifest.tmp"
            temporary_manifest.write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            os.replace(temporary_manifest, manifest_path)
            self._config.update(
                {
                    "lastSyncedAt": updated_at,
                    "lastRemoteDeviceId": self._config["deviceId"],
                    "dirty": False,
                }
            )
            self._save_config()
            self._state = "ready"
            self._error = ""

    def pull(self, force: bool = False) -> None:
        with self._lock:
            self._cancel_timer()
            if not self._config["enabled"]:
                raise SyncNotReadyError("跨设备同步尚未启用")
            latest = self._latest_manifest()
            if latest is None:
                raise SyncNotReadyError("云盘中还没有明琰AI同步快照")
            if self._config["dirty"] and not force:
                self._state = "conflict"
                self._error = "本机存在未同步修改，获取云端版本会覆盖这些修改"
                raise SyncConflictError(self._error)

            source_database = (
                self._sync_root()
                / "devices"
                / str(latest["deviceId"])
                / "mingyan.sqlite3"
            )
            if not source_database.is_file():
                raise SyncNotReadyError("云端数据库文件尚未同步完成，请稍后重试")
            self._validate_database(source_database)
            self._state = "syncing"
            self._error = ""
            self._copy_generated(self._sync_root() / "generated", self.generated_dir)

            self.data_dir.mkdir(parents=True, exist_ok=True)
            temporary_database = self.data_dir / f".mingyan-import.{uuid4().hex}.tmp"
            shutil.copy2(source_database, temporary_database)
            self._validate_database(temporary_database)
            os.replace(temporary_database, self.database_path)
            self._config.update(
                {
                    "lastSyncedAt": str(latest["updatedAt"]),
                    "lastRemoteDeviceId": str(latest["deviceId"]),
                    "dirty": False,
                }
            )
            self._save_config()
            self._state = "ready"
            self._error = ""

    def sync_on_startup(self) -> None:
        with self._lock:
            if not self._config["enabled"]:
                return
            try:
                latest = self._latest_manifest()
                if latest is None:
                    if self.database_path.is_file():
                        self.push(force=True)
                    return
                latest_at = parse_timestamp(str(latest["updatedAt"]))
                last_synced = parse_timestamp(str(self._config["lastSyncedAt"]))
                if latest_at > last_synced:
                    if self._config["dirty"]:
                        raise SyncConflictError(
                            "本机和另一台电脑都有未合并修改，已暂停自动同步"
                        )
                    self.pull(force=True)
                elif self._config["dirty"]:
                    self.push()
            except (OSError, RuntimeError, sqlite3.Error) as error:
                self._state = "conflict" if isinstance(error, SyncConflictError) else "error"
                self._error = str(error)

    def flush(self) -> None:
        with self._lock:
            self._cancel_timer()
            if not self._config["enabled"] or not self._config["dirty"]:
                return
        try:
            self.push()
        except (OSError, RuntimeError, sqlite3.Error):
            return

