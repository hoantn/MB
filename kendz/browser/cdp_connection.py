import json
import threading
import websocket
import time
from typing import Any, Dict, Optional


class CDPConnection:
    """Quản lý WebSocket kết nối DevTools Protocol."""

    def __init__(self, ws_url: str, timeout: float = 5.0) -> None:
        self.ws_url = ws_url
        self.timeout = timeout

        self._ws: Optional[websocket.WebSocket] = None
        self._recv_thread: Optional[threading.Thread] = None
        self._running = False
        self._id_counter = 0
        self._lock = threading.Lock()

        # Các response được lưu tạm theo request_id
        self._responses: Dict[int, Dict[str, Any]] = {}

    def connect(self) -> None:
        """Tạo kết nối tới ws://localhost:9222/..."""
        self._ws = websocket.WebSocket()
        self._ws.settimeout(self.timeout)
        self._ws.connect(self.ws_url)
        self._running = True

        # Thread nhận message từ DevTools
        self._recv_thread = threading.Thread(target=self._recv_loop, daemon=True)
        self._recv_thread.start()

    def close(self) -> None:
        self._running = False
        if self._ws:
            try:
                self._ws.close()
            except:
                pass

    def _recv_loop(self) -> None:
        """Nhận message từ DevTools và lưu theo request_id."""
        while self._running and self._ws:
            try:
                msg = self._ws.recv()
                if not msg:
                    continue

                data = json.loads(msg)

                # Response cho 1 request cụ thể
                if "id" in data:
                    req_id = int(data["id"])
                    with self._lock:
                        self._responses[req_id] = data

            except Exception:
                time.sleep(0.01)

    def _next_id(self) -> int:
        with self._lock:
            self._id_counter += 1
            return self._id_counter

    def send_cmd(self, method: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Gửi lệnh DevTools và chờ response."""
        if self._ws is None:
            raise RuntimeError("CDPConnection: WebSocket chưa connect.")

        req_id = self._next_id()

        msg = {
            "id": req_id,
            "method": method,
            "params": params or {}
        }

        self._ws.send(json.dumps(msg))

        # Chờ response từ thread _recv_loop
        start = time.time()
        while time.time() - start < self.timeout:
            with self._lock:
                if req_id in self._responses:
                    result = self._responses.pop(req_id)
                    return result
            time.sleep(0.01)

        raise TimeoutError(f"CDPConnection: Timeout khi chờ lệnh {method}")
