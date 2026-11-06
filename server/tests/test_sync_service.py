from contextlib import closing
from pathlib import Path
import sqlite3

import pytest

from server.app import initialize_database
from server.sync_service import CrossDeviceSync, SyncConflictError


def add_project(database_path: Path, project_id: str, name: str) -> None:
    with closing(sqlite3.connect(database_path)) as connection:
        with connection:
            connection.execute(
                """
                INSERT INTO projects (
                    id, name, description, stage, created_at, updated_at
                ) VALUES (?, ?, '', 'text', ?, ?)
                """,
                (
                    project_id,
                    name,
                    "2026-11-06T00:00:00+00:00",
                    "2026-11-06T00:00:00+00:00",
                ),
            )


def project_names(database_path: Path) -> list[str]:
    with closing(sqlite3.connect(database_path)) as connection:
        return [
            row[0]
            for row in connection.execute("SELECT name FROM projects ORDER BY name")
        ]


def test_sync_round_trip_and_conflict_protection(tmp_path: Path) -> None:
    shared_folder = tmp_path / "shared"
    mac_data = tmp_path / "mac-data"
    windows_data = tmp_path / "windows-data"
    mac_database = mac_data / "mingyan.sqlite3"
    windows_database = windows_data / "mingyan.sqlite3"

    initialize_database(mac_database)
    add_project(mac_database, "project-mac", "凤掌九天")
    mac_asset = mac_data / "generated" / "project-mac" / "asset-1" / "image.png"
    mac_asset.parent.mkdir(parents=True)
    mac_asset.write_bytes(b"mock-image")

    mac_sync = CrossDeviceSync(mac_data, mac_database)
    mac_sync.configure(str(shared_folder), "MacBook", True)
    assert mac_sync.status()["state"] == "ready"

    windows_sync = CrossDeviceSync(windows_data, windows_database)
    windows_sync.configure(str(shared_folder), "Windows PC", True)
    assert project_names(windows_database) == ["凤掌九天"]
    assert (
        windows_data / "generated" / "project-mac" / "asset-1" / "image.png"
    ).read_bytes() == b"mock-image"

    add_project(windows_database, "project-windows", "第二台电脑新增")
    windows_sync.mark_dirty(delay_seconds=3600)
    windows_sync.push()

    add_project(mac_database, "project-stale", "旧电脑未合并修改")
    mac_sync.mark_dirty(delay_seconds=3600)
    with pytest.raises(SyncConflictError):
        mac_sync.push()
    assert mac_sync.status()["state"] == "conflict"

    mac_sync.pull(force=True)
    assert project_names(mac_database) == ["凤掌九天", "第二台电脑新增"]
    assert mac_sync.status()["state"] == "ready"
    mac_sync.flush()
    windows_sync.flush()

