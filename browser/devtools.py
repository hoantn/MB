import base64
import json
import time
from typing import Dict, Optional, List

import requests
import websocket
from PIL import Image
from io import BytesIO

from core.logger import log


class DevToolsClient:
    """
    DevToolsClient dùng Chrome DevTools Protocol thật.

    - capture_screenshot(region)
    - mouse_move / mouse_click / mouse_drag

    Yêu cầu:
      - Chrome được mở với:
        --remote-debugging-port=<port>
        --user-data-dir=<profile_dir>
        --remote-allow-origins=*
    """

    def __init__(self, profile_id: str, port: int):
        self.profile_id = profile_id
        self.port = port
        self._ws_url: Optional[str] = None

    # ================== KẾT NỐI CƠ BẢN =====================

    def connect(self) -> None:
        """
        Lấy WebSocket URL của tab đầu tiên trên port tương ứng.
        """
        url = f"http://127.0.0.1:{self.port}/json"
        for _ in range(10):
            try:
                resp = requests.get(url, timeout=1.0)
                tabs = resp.json()
                page_tabs = [t for t in tabs if t.get("type") == "page"]
                if not page_tabs:
                    log.warning("DevTools[%s] không tìm thấy tab kiểu 'page' trên port %s",
                                self.profile_id, self.port)
                    time.sleep(0.5)
                    continue
                self._ws_url = page_tabs[0].get("webSocketDebuggerUrl")
                log.info("DevTools[%s] connected to ws: %s", self.profile_id, self._ws_url)
                return
            except Exception as e:
                log.warning("DevTools[%s] chưa kết nối được (%s), thử lại...", self.profile_id, e)
                time.sleep(0.5)
        raise RuntimeError(f"Không lấy được DevTools JSON từ port {self.port}")

    def disconnect(self) -> None:
        self._ws_url = None
        log.info("DevTools[%s] disconnected", self.profile_id)

    def _ensure_ws_url(self):
        if not self._ws_url:
            self.connect()

    def _open_ws(self) -> websocket.WebSocket:
        """
        Mỗi lần thao tác, mở một kết nối WebSocket mới cho đơn giản.
        """
        self._ensure_ws_url()
        if not self._ws_url:
            raise RuntimeError("Chưa có WebSocket URL cho DevTools")
        ws = websocket.create_connection(self._ws_url, timeout=5)
        return ws

    # ================== SCREENSHOT ==========================

    def capture_screenshot(self, region: Dict[str, int] | None = None) -> Image.Image:
        """
        Chụp screenshot qua Page.captureScreenshot.
        Nếu region != None thì dùng clip (x,y,width,height) theo coordinate của page.
        """
        ws = self._open_ws()
        try:
            msg_id = 1
            # Enable Page domain
            ws.send(json.dumps({"id": msg_id, "method": "Page.enable"}))
            msg_id += 1

            # Optional: bring to front
            ws.send(json.dumps({"id": msg_id, "method": "Page.bringToFront"}))
            msg_id += 1

            params: Dict = {"format": "png"}
            if region:
                clip = {
                    "x": float(region.get("x", 0)),
                    "y": float(region.get("y", 0)),
                    "width": float(region.get("width", 800)),
                    "height": float(region.get("height", 600)),
                    "scale": 1.0,
                }
                params["clip"] = clip

            ws.send(json.dumps({
                "id": msg_id,
                "method": "Page.captureScreenshot",
                "params": params,
            }))
            target_id = msg_id

            data_b64 = None
            while True:
                resp_raw = ws.recv()
                if not resp_raw:
                    break
                resp = json.loads(resp_raw)
                if resp.get("id") == target_id:
                    data_b64 = resp.get("result", {}).get("data")
                    break

            if not data_b64:
                raise RuntimeError("Không nhận được dữ liệu screenshot từ DevTools")

            img_bytes = base64.b64decode(data_b64)
            img = Image.open(BytesIO(img_bytes)).convert("RGB")
            return img
        finally:
            ws.close()

    # ================== INPUT CHUỘT =========================

    def _dispatch_mouse_events(self, events: List[Dict]):
        """
        Gửi nhiều Input.dispatchMouseEvent trong một connection.
        'events' là list các dict params (không chứa id/method).
        """
        ws = self._open_ws()
        try:
            msg_id = 1
            # enable Input & Page tối thiểu
            ws.send(json.dumps({"id": msg_id, "method": "Page.enable"}))
            msg_id += 1

            for ev in events:
                ws.send(json.dumps({
                    "id": msg_id,
                    "method": "Input.dispatchMouseEvent",
                    "params": ev,
                }))
                msg_id += 1
                # nhỏ giọt tránh spam
                time.sleep(0.01)
        finally:
            ws.close()

    def mouse_move(self, x: float, y: float):
        ev = {
            "type": "mouseMoved",
            "x": float(x),
            "y": float(y),
            "button": "none",
        }
        self._dispatch_mouse_events([ev])

    def mouse_click(self, x: float, y: float):
        """
        Click trái tại (x,y).
        """
        events = [
            {
                "type": "mouseMoved",
                "x": float(x),
                "y": float(y),
                "button": "none",
            },
            {
                "type": "mousePressed",
                "x": float(x),
                "y": float(y),
                "button": "left",
                "clickCount": 1,
            },
            {
                "type": "mouseReleased",
                "x": float(x),
                "y": float(y),
                "button": "left",
                "clickCount": 1,
            },
        ]
        self._dispatch_mouse_events(events)

    def mouse_drag(self, x1: float, y1: float, x2: float, y2: float):
        """
        Kéo chuột từ (x1,y1) → (x2,y2) bằng nút trái.
        """
        steps = 5
        events = []

        # move to start
        events.append({
            "type": "mouseMoved",
            "x": float(x1),
            "y": float(y1),
            "button": "none",
        })
        # press
        events.append({
            "type": "mousePressed",
            "x": float(x1),
            "y": float(y1),
            "button": "left",
            "clickCount": 1,
        })

        # intermediate moves với buttons=1
        for i in range(1, steps):
            t = i / steps
            xi = x1 + (x2 - x1) * t
            yi = y1 + (y2 - y1) * t
            events.append({
                "type": "mouseMoved",
                "x": float(xi),
                "y": float(yi),
                "button": "left",
                "buttons": 1,
            })

        # move cuối
        events.append({
            "type": "mouseMoved",
            "x": float(x2),
            "y": float(y2),
            "button": "left",
            "buttons": 1,
        })

        # release
        events.append({
            "type": "mouseReleased",
            "x": float(x2),
            "y": float(y2),
            "button": "left",
            "clickCount": 1,
        })

        self._dispatch_mouse_events(events)
