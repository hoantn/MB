from __future__ import annotations

import json
import queue
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, Optional
from core.config import load_config

try:
    import logging

    logger = logging.getLogger("MauBinhTool")
except Exception:  # pragma: no cover
    logger = None  # type: ignore


# Hàng đợi event: extension -> Python
WS_EVENT_QUEUE: "queue.Queue[Dict[str, Any]]" = queue.Queue()

# Hàng đợi command: Python -> extension
WS_COMMAND_QUEUE: "queue.Queue[Dict[str, Any]]" = queue.Queue()


def enqueue_command(command: Dict[str, Any]) -> None:
    """
    Được Python gọi (MainWindow / RoomEngine) để đẩy command
    xuống extension. Mỗi command chỉ chứa action + vài tham số.
    """
    try:
        WS_COMMAND_QUEUE.put_nowait(command)
        if logger:
            logger.info(
                "WS bridge enqueue command: action=%s profile=%s",
                command.get("action"),
                command.get("profile_id"),
            )
    except queue.Full:
        if logger:
            logger.warning("WS bridge command queue full, bỏ command: %s", command)


class _WSBridgeHandler(BaseHTTPRequestHandler):
    """
    HTTP handler:

    - POST /mb-ws-event
        Extension gửi event (room_list, room_snapshot, ...)

    - POST /mb-ws-command-pop
        Extension gọi định kỳ để lấy 1 command cho profile của nó.
    """

    server_version = "MBWSBridge/1.0"

    # ------------------------------------------------------------------
    # Extension -> Python: gửi event
    # ------------------------------------------------------------------
    def _handle_event_post(self) -> None:
        length_str = self.headers.get("Content-Length") or "0"
        try:
            length = int(length_str)
        except ValueError:
            length = 0

        raw = self.rfile.read(length)
        try:
            data = json.loads(raw.decode("utf-8") or "{}")
        except Exception:
            data = {
                "kind": "invalid",
                "raw": raw.decode("utf-8", errors="ignore"),
            }

        try:
            WS_EVENT_QUEUE.put_nowait(data)
            if logger:
                logger.info(
                    "WS bridge recv event: kind=%s profile=%s",
                    data.get("kind"),
                    data.get("profile_id"),
                )
        except queue.Full:
            if logger:
                logger.warning("WS bridge event queue full, bỏ event: %s", data)

        self.send_response(204)
        self.end_headers()

    # ------------------------------------------------------------------
    # Extension -> Python: pop command cho profile
    # ------------------------------------------------------------------
    def _handle_command_pop(self) -> None:
        length_str = self.headers.get("Content-Length") or "0"
        try:
            length = int(length_str)
        except ValueError:
            length = 0

        raw = self.rfile.read(length)
        profile_id: Optional[str] = None
        if raw:
            try:
                body = json.loads(raw.decode("utf-8") or "{}")
                profile_id = body.get("profile_id")
            except Exception:
                profile_id = None

        selected: Optional[Dict[str, Any]] = None
        kept: list[Dict[str, Any]] = []

        while True:
            try:
                cmd = WS_COMMAND_QUEUE.get_nowait()
            except queue.Empty:
                break

            if profile_id is None or cmd.get("profile_id") == profile_id:
                selected = cmd
                break
            kept.append(cmd)

        # trả lại các command khác vào queue
        for cmd in kept:
            try:
                WS_COMMAND_QUEUE.put_nowait(cmd)
            except queue.Full:
                break

        if not selected:
            # không có command cho profile này
            self.send_response(204)
            self.end_headers()
            return

        if logger:
            logger.info(
                "WS bridge pop command: action=%s profile=%s",
                selected.get("action"),
                selected.get("profile_id"),
            )

        body = json.dumps(selected).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    # ------------------------------------------------------------------
    # HTTP entrypoints
    # ------------------------------------------------------------------
    def do_POST(self) -> None:
        if self.path == "/mb-ws-event":
            self._handle_event_post()
        elif self.path == "/mb-ws-command-pop":
            self._handle_command_pop()
        elif self.path == "/mb-proxy-creds":
            self._handle_proxy_creds()
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, fmt: str, *args: Any) -> None:
        # Tắt log mặc định của http.server cho đỡ rác console
        return

    # ------------------------------------------------------------------
    # Extension -> Python: lấy proxy username/password cho 1 profile
    # ------------------------------------------------------------------
    def _handle_proxy_creds(self) -> None:
        length_str = self.headers.get("Content-Length") or "0"
        try:
            length = int(length_str)
        except ValueError:
            length = 0

        raw = self.rfile.read(length)
        profile_id: Optional[str] = None
        if raw:
            try:
                body = json.loads(raw.decode("utf-8") or "{}")
                profile_id = body.get("profile_id")
            except Exception:
                profile_id = None

        if not profile_id:
            # Thiếu profile_id -> bad request
            self.send_response(400)
            self.end_headers()
            return

        username = ""
        password = ""

        try:
            cfg = load_config()
            profiles = cfg.get("profiles", {}) or {}
            p_cfg = profiles.get(profile_id) or {}
            proxy_cfg = p_cfg.get("proxy") or {}
            username = proxy_cfg.get("username") or ""
            password = proxy_cfg.get("password") or ""
        except Exception:
            username = ""
            password = ""

        if not username:
            # Không có username -> không trả creds (extension sẽ bỏ qua)
            self.send_response(204)
            self.end_headers()
            return

        resp = {"username": username, "password": password}
        body_bytes = json.dumps(resp).encode("utf-8")

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body_bytes)))
        self.end_headers()
        self.wfile.write(body_bytes)

def start_ws_http_bridge(host: str = "127.0.0.1", port: int = 9527) -> ThreadingHTTPServer:
    """
    Extension sẽ:
        - POST /mb-ws-event        : gửi event
        - POST /mb-ws-command-pop  : lấy command
    """
    server = ThreadingHTTPServer((host, port), _WSBridgeHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server
