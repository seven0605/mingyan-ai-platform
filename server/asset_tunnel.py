from __future__ import annotations

from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
from queue import Empty, Queue
import re
import secrets
import shutil
import subprocess
import threading
import time
from typing import Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


TUNNEL_URL_PATTERN = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")
CONTENT_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
}


@dataclass(frozen=True)
class AssetTunnelStatus:
    installed: bool
    running: bool
    project_id: str | None
    public_url: str | None
    exposed_asset_count: int
    error: str


class TemporaryAssetTunnel:
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir
        self._lock = threading.RLock()
        self._server: ThreadingHTTPServer | None = None
        self._server_thread: threading.Thread | None = None
        self._process: subprocess.Popen[str] | None = None
        self._reader_thread: threading.Thread | None = None
        self._token = ""
        self._routes: dict[str, Path] = {}
        self._route_keys: dict[str, str] = {}
        self._project_id: str | None = None
        self._public_url: str | None = None
        self._error = ""
        self._served_request_count = 0

    def cloudflared_path(self) -> Path | None:
        configured = os.environ.get("MINGYAN_CLOUDFLARED_PATH", "").strip()
        candidates = [
            Path(configured) if configured else None,
            Path(found) if (found := shutil.which("cloudflared")) else None,
            self.data_dir / "bin" / ("cloudflared.exe" if os.name == "nt" else "cloudflared"),
        ]
        return next(
            (
                candidate
                for candidate in candidates
                if candidate
                and candidate.is_file()
                and (os.name == "nt" or os.access(candidate, os.X_OK))
            ),
            None,
        )

    def status(self) -> AssetTunnelStatus:
        with self._lock:
            running = bool(
                self._process
                and self._process.poll() is None
                and self._public_url
                and self._server
            )
            return AssetTunnelStatus(
                installed=self.cloudflared_path() is not None,
                running=running,
                project_id=self._project_id if running else None,
                public_url=self._public_url if running else None,
                exposed_asset_count=len(self._routes) if running else 0,
                error=self._error,
            )

    def start_local(self, project_id: str, files: Mapping[str, Path]) -> dict[str, str]:
        if not files:
            raise ValueError("没有可公开的参考素材")
        resolved_files: dict[str, Path] = {}
        for logical_id, file_path in files.items():
            resolved = file_path.resolve(strict=True)
            if not resolved.is_file() or resolved.suffix.lower() not in CONTENT_TYPES:
                raise ValueError("参考素材必须是本地 PNG、JPG 或 WEBP 图片")
            resolved_files[logical_id] = resolved

        with self._lock:
            self._stop_unlocked()
            self._token = secrets.token_urlsafe(32)
            self._routes = {}
            self._route_keys = {}
            for logical_id, file_path in resolved_files.items():
                route_key = f"{secrets.token_urlsafe(18)}{file_path.suffix.lower()}"
                self._routes[route_key] = file_path
                self._route_keys[logical_id] = route_key
            self._project_id = project_id
            self._error = ""
            self._served_request_count = 0

            tunnel = self

            class AssetRequestHandler(BaseHTTPRequestHandler):
                def do_GET(self) -> None:
                    tunnel._serve(self, include_body=True)

                def do_HEAD(self) -> None:
                    tunnel._serve(self, include_body=False)

                def log_message(self, _format: str, *_args: object) -> None:
                    return

            self._server = ThreadingHTTPServer(("127.0.0.1", 0), AssetRequestHandler)
            self._server.daemon_threads = True
            self._server_thread = threading.Thread(
                target=self._server.serve_forever,
                name="mingyan-asset-gateway",
                daemon=True,
            )
            self._server_thread.start()
            local_root = f"http://127.0.0.1:{self._server.server_port}"
            return self._urls_for_root(local_root)

    def start(self, project_id: str, files: Mapping[str, Path]) -> dict[str, str]:
        binary = self.cloudflared_path()
        if binary is None:
            raise FileNotFoundError("尚未安装 cloudflared")
        self.start_local(project_id, files)
        with self._lock:
            if self._server is None:
                raise RuntimeError("临时素材服务启动失败")
            local_url = f"http://127.0.0.1:{self._server.server_port}"
            output_queue: Queue[str] = Queue()
            try:
                self._process = subprocess.Popen(
                    [
                        str(binary),
                        "tunnel",
                        "--protocol",
                        "http2",
                        "--url",
                        local_url,
                    ],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                )
            except OSError as error:
                self._error = f"cloudflared 启动失败：{type(error).__name__}"
                self._stop_unlocked(preserve_error=True)
                raise RuntimeError(self._error) from error

            process = self._process

            def read_output() -> None:
                if process.stdout is None:
                    return
                for line in process.stdout:
                    output_queue.put(line)

            self._reader_thread = threading.Thread(
                target=read_output,
                name="mingyan-cloudflared-output",
                daemon=True,
            )
            self._reader_thread.start()

        public_url = self._wait_for_public_url(output_queue)
        with self._lock:
            self._public_url = public_url
            return self._urls_for_root(public_url)

    def stop(self) -> None:
        with self._lock:
            self._stop_unlocked()

    def served_request_count(self) -> int:
        with self._lock:
            return self._served_request_count

    def verify_urls(
        self, urls: Mapping[str, str], *, timeout_seconds: float = 120
    ) -> None:
        if not urls:
            raise ValueError("没有可验证的参考素材")
        deadline = time.monotonic() + timeout_seconds
        first_id, first_url = next(iter(urls.items()))
        last_error = ""
        while time.monotonic() < deadline:
            try:
                self._verify_url(first_url, min(5, max(1, deadline - time.monotonic())))
                break
            except (HTTPError, URLError, OSError, TimeoutError) as error:
                last_error = type(error).__name__
                time.sleep(1)
        else:
            raise RuntimeError(
                f"临时公网通道未就绪，参考素材 {first_id} 无法访问"
                + (f"（{last_error}）" if last_error else "")
            )

        for logical_id, url in list(urls.items())[1:]:
            try:
                self._verify_url(url, min(10, max(1, deadline - time.monotonic())))
            except (HTTPError, URLError, OSError, TimeoutError) as error:
                raise RuntimeError(
                    f"临时公网通道中的参考素材 {logical_id} 无法访问"
                    f"（{type(error).__name__}）"
                ) from error

    @staticmethod
    def _verify_url(url: str, timeout_seconds: float) -> None:
        request = Request(
            url,
            headers={"User-Agent": "MingyanAssetGateway/1.0"},
            method="HEAD",
        )
        with urlopen(request, timeout=timeout_seconds) as response:
            if response.status != 200:
                raise HTTPError(
                    url,
                    response.status,
                    "临时素材地址返回异常",
                    response.headers,
                    None,
                )
            if response.headers.get_content_type() not in CONTENT_TYPES.values():
                raise ValueError("临时素材地址未返回图片")

    def _wait_for_public_url(self, output_queue: Queue[str]) -> str:
        public_url = ""
        registered = False
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            try:
                line = output_queue.get(timeout=1)
            except Empty:
                with self._lock:
                    if self._process and self._process.poll() is not None:
                        break
                continue
            if match := TUNNEL_URL_PATTERN.search(line):
                public_url = match.group(0)
            if "Registered tunnel connection" in line:
                registered = True
            if public_url and registered:
                return public_url
        with self._lock:
            self._error = "未能在 45 秒内取得临时公网地址"
            self._stop_unlocked(preserve_error=True)
        raise RuntimeError(self._error)

    def _serve(
        self, handler: BaseHTTPRequestHandler, *, include_body: bool
    ) -> None:
        parts = urlsplit(handler.path).path.split("/")
        with self._lock:
            file_path = (
                self._routes.get(parts[3])
                if len(parts) == 4
                and parts[1] == "media"
                and secrets.compare_digest(parts[2], self._token)
                else None
            )
        if file_path is None:
            handler.send_error(404)
            return
        with self._lock:
            self._served_request_count += 1
        try:
            size = file_path.stat().st_size
            content_type = CONTENT_TYPES[file_path.suffix.lower()]
            handler.send_response(200)
            handler.send_header("Content-Type", content_type)
            handler.send_header("Content-Length", str(size))
            handler.send_header("Cache-Control", "private, no-store")
            handler.send_header("X-Content-Type-Options", "nosniff")
            handler.end_headers()
            if include_body:
                with file_path.open("rb") as source:
                    shutil.copyfileobj(source, handler.wfile)
        except (BrokenPipeError, ConnectionResetError):
            return

    def _urls_for_root(self, root: str) -> dict[str, str]:
        return {
            logical_id: f"{root}/media/{self._token}/{route_key}"
            for logical_id, route_key in self._route_keys.items()
        }

    def _stop_unlocked(self, *, preserve_error: bool = False) -> None:
        if self._process and self._process.poll() is None:
            self._process.terminate()
            try:
                self._process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._process.kill()
                self._process.wait(timeout=5)
        if self._server:
            self._server.shutdown()
            self._server.server_close()
        self._server = None
        self._server_thread = None
        self._process = None
        self._reader_thread = None
        self._token = ""
        self._routes = {}
        self._route_keys = {}
        self._project_id = None
        self._public_url = None
        if not preserve_error:
            self._error = ""
