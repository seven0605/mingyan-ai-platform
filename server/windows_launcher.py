from __future__ import annotations

import multiprocessing
import os
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

import uvicorn

from server.app import create_app


def bundle_root() -> Path:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent.parent


def data_dir() -> Path:
    configured = os.environ.get("MINGYAN_DATA_DIR", "").strip()
    return Path(configured) if configured else Path.home() / ".mingyan-ai"


def server_port() -> int:
    return int(os.environ.get("MINGYAN_PORT", "8000"))


def health_ready(url: str, timeout: float = 0.5) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return response.status == 200
    except OSError:
        return False


def open_browser_when_ready(health_url: str, app_url: str) -> None:
    if os.environ.get("MINGYAN_NO_BROWSER") == "1":
        return
    for _ in range(120):
        if health_ready(health_url):
            webbrowser.open(app_url)
            return
        time.sleep(0.25)


def main() -> int:
    port = server_port()
    app_url = f"http://127.0.0.1:{port}/"
    health_url = f"http://127.0.0.1:{port}/api/health"
    if health_ready(health_url):
        if os.environ.get("MINGYAN_NO_BROWSER") != "1":
            webbrowser.open(app_url)
        return 0

    resolved_data_dir = data_dir()
    resolved_data_dir.mkdir(parents=True, exist_ok=True)
    static_dir = bundle_root() / "dist"
    if not (static_dir / "index.html").is_file():
        raise RuntimeError("缺少网页资源，请重新安装明琰AI平台")

    application = create_app(data_dir=resolved_data_dir, static_dir=static_dir)
    browser_thread = threading.Thread(
        target=open_browser_when_ready,
        args=(health_url, app_url),
        daemon=True,
    )
    browser_thread.start()
    print(f"明琰AI平台运行中：{app_url}")
    print("关闭此窗口即可停止本地服务。")
    uvicorn.run(
        application,
        host="127.0.0.1",
        port=port,
        loop="asyncio",
        http="h11",
        access_log=False,
    )
    return 0


if __name__ == "__main__":
    multiprocessing.freeze_support()
    raise SystemExit(main())
