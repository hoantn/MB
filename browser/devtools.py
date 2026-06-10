import base64
import json
import threading
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
        # Các thao tác chuột của cùng một P phải tuần tự. P1/P2/P3 vẫn dùng
        # client/lock riêng nên tiếp tục hoạt động độc lập.
        self._input_lock = threading.RLock()

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

        Nếu ws_url đã hết hiệu lực (No such target id / 500) thì tự động
        lấy lại JSON / ws_url mới rồi thử lại 1 lần.
        """
        # Lần thử thứ nhất
        self._ensure_ws_url()
        if not self._ws_url:
            raise RuntimeError("Chưa có WebSocket URL cho DevTools")

        try:
            return websocket.create_connection(self._ws_url, timeout=5)

        except websocket.WebSocketBadStatusException as e:
            # Trường hợp server trả HTTP 500 (thường kèm No such target id)
            msg = str(e)
            if e.status_code == 500 or "No such target id" in msg:
                log.warning(
                    "DevTools[%s] ws_url cũ không còn hợp lệ (%s) -> lấy lại JSON / ws_url mới",
                    self.profile_id,
                    msg,
                )
                # Refresh ws_url rồi thử lại 1 lần
                self._ws_url = None
                self._ensure_ws_url()
                if not self._ws_url:
                    raise
                return websocket.create_connection(self._ws_url, timeout=5)
            # Lỗi khác: ném lại
            raise

        except Exception as e:
            # Một số version library ném Exception thường với message 'No such target id'
            msg = str(e)
            if "No such target id" in msg:
                log.warning(
                    "DevTools[%s] ws_url stale (%s) -> reconnect lấy ws_url mới",
                    self.profile_id,
                    msg,
                )
                self._ws_url = None
                self._ensure_ws_url()
                if not self._ws_url:
                    raise
                return websocket.create_connection(self._ws_url, timeout=5)
            raise


    # ================== SCREENSHOT ==========================

    def bring_to_front(self) -> None:
        """Ask Chrome DevTools to activate the attached page tab."""
        ws = self._open_ws()
        try:
            ws.send(json.dumps({"id": 1, "method": "Page.enable"}))
            ws.send(json.dumps({"id": 2, "method": "Page.bringToFront"}))
        finally:
            ws.close()

    def navigate(self, url: str) -> None:
        """Send one target navigation without waiting for the website to load."""
        target_url = str(url or "").strip()
        if not target_url:
            return

        ws = self._open_ws()
        try:
            ws.send(json.dumps({
                "id": 1,
                "method": "Page.navigate",
                "params": {"url": target_url},
            }))
        finally:
            ws.close()

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

    def _dispatch_mouse_events(self, events: List[Dict], sleep_per_event: float = 0.01, wait_ack: bool = True):
        with self._input_lock:
            self._dispatch_mouse_events_locked(events, sleep_per_event=sleep_per_event, wait_ack=wait_ack)

    def _dispatch_mouse_events_locked(self, events: List[Dict], sleep_per_event: float = 0.01, wait_ack: bool = True):
        ws = self._open_ws()
        try:
            msg_id = 1
            if wait_ack:
                def _send_and_wait(method: str, params: Optional[Dict] = None) -> None:
                    nonlocal msg_id
                    command_id = msg_id
                    payload = {"id": command_id, "method": method}
                    if params is not None:
                        payload["params"] = params
                    ws.send(json.dumps(payload))
                    msg_id += 1
                    while True:
                        raw = ws.recv()
                        if not raw:
                            raise RuntimeError(
                                "DevTools đóng kết nối trước khi xác nhận thao tác chuột"
                            )
                        response = json.loads(raw)
                        if response.get("id") != command_id:
                            continue
                        if response.get("error"):
                            raise RuntimeError(
                                f"DevTools từ chối thao tác chuột id={command_id}: "
                                f"{response.get('error')}"
                            )
                        return
                _send_and_wait("Page.enable")
                for ev in events:
                    _send_and_wait("Input.dispatchMouseEvent", ev)
                    time.sleep(sleep_per_event)
            else:
                # fire-and-forget: bắn event không chờ Chrome ACK (bản gốc)
                ws.send(json.dumps({"id": msg_id, "method": "Page.enable"}))
                msg_id += 1
                for ev in events:
                    ws.send(json.dumps({"id": msg_id, "method": "Input.dispatchMouseEvent", "params": ev}))
                    msg_id += 1
                    time.sleep(sleep_per_event)
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

    def mouse_drag(self, x1: float, y1: float, x2: float, y2: float, *, steps: int = 18, duration_s: float = 0.0, wait_ack: bool = False):
        steps = max(2, int(steps))

        events = []

        # 1) Di chuyển chuột tới điểm bắt đầu (không nhấn)
        events.append({
            "type": "mouseMoved",
            "x": float(x1),
            "y": float(y1),
            "button": "none",
        })

        # 2) Nhấn giữ nút trái tại điểm bắt đầu
        events.append({
            "type": "mousePressed",
            "x": float(x1),
            "y": float(y1),
            "button": "left",
            "clickCount": 1,
        })

        # 3) Di chuyển trung gian từ (x1, y1) -> (x2, y2)
        for i in range(1, steps):
            t = i / float(steps)
            xi = x1 + (x2 - x1) * t
            yi = y1 + (y2 - y1) * t
            events.append({
                "type": "mouseMoved",
                "x": float(xi),
                "y": float(yi),
                "button": "left",
                "buttons": 1,
            })

        # Bước move cuối cùng chính xác tại điểm đích
        events.append({
            "type": "mouseMoved",
            "x": float(x2),
            "y": float(y2),
            "button": "left",
            "buttons": 1,
        })

        # 4) Nhả chuột tại điểm đích
        events.append({
            "type": "mouseReleased",
            "x": float(x2),
            "y": float(y2),
            "button": "left",
            "clickCount": 1,
        })

        n_events = len(events)
        sleep_per_event = (max(0.002, float(duration_s) / n_events) if duration_s > 0 else 0.01)
        self._dispatch_mouse_events(events, sleep_per_event=sleep_per_event, wait_ack=wait_ack)

    def insert_text(self, text: str) -> None:
        """
        Gõ text vào phần tử đang focus sau khi đã click.
        Dùng CDP Input.insertText để text đi thẳng vào ô nhập hiện tại.
        """
        value = str(text or "")
        if not value:
            return

        ws = self._open_ws()
        try:
            msg_id = 1

            # Enable tối thiểu
            ws.send(json.dumps({"id": msg_id, "method": "Page.enable"}))
            msg_id += 1

            ws.send(json.dumps({"id": msg_id, "method": "Runtime.enable"}))
            msg_id += 1

            ws.send(json.dumps({"id": msg_id, "method": "Page.bringToFront"}))
            msg_id += 1

            # Bảo đảm phần tử đang active/focus
            focus_expr = """
            (function () {
                try {
                    const el = document.activeElement;
                    if (el && typeof el.focus === 'function') {
                        el.focus();
                    }
                    return true;
                } catch (e) {
                    return false;
                }
            })()
            """
            ws.send(json.dumps({
                "id": msg_id,
                "method": "Runtime.evaluate",
                "params": {
                    "expression": focus_expr,
                    "returnByValue": True,
                },
            }))
            msg_id += 1

            # Nghỉ rất nhẹ để game/DOM nhận focus
            time.sleep(0.05)

            insert_id = msg_id
            ws.send(json.dumps({
                "id": insert_id,
                "method": "Input.insertText",
                "params": {
                    "text": value
                },
            }))

            # Chờ response đúng id để biết command đã chạy
            while True:
                raw = ws.recv()
                if not raw:
                    break
                resp = json.loads(raw)
                if resp.get("id") == insert_id:
                    if "error" in resp:
                        raise RuntimeError(f"Input.insertText lỗi: {resp['error']}")
                    break

        finally:
            try:
                ws.close()
            except Exception:
                pass

    def type_text(self, text: str) -> None:
        self.insert_text(text)

    def send_text(self, text: str) -> None:
        self.insert_text(text)

    def paste_text(self, text: str) -> None:
        self.insert_text(text)
        
    def get_cocos_canvas_info(self) -> dict:
        """
        Lấy thông tin canvas Cocos:
        { left, top, width, height } từ cc.game.canvas.getBoundingClientRect().
        """
        ws = self._open_ws()
        try:
            msg_id = 1

            # Enable Runtime
            ws.send(json.dumps({
                "id": msg_id,
                "method": "Runtime.enable",
            }))
            msg_id += 1

            expr = """
            (function () {
                try {
                    if (typeof cc !== 'undefined' && cc.game && cc.game.canvas) {
                        var c = cc.game.canvas.getBoundingClientRect();
                        return {
                            left: c.left,
                            top: c.top,
                            width: c.width,
                            height: c.height
                        };
                    }
                } catch (e) {}
                return null;
            })()
            """

            ws.send(json.dumps({
                "id": msg_id,
                "method": "Runtime.evaluate",
                "params": {
                    "expression": expr,
                    "returnByValue": True,
                },
            }))
            target_id = msg_id

            canvas = None
            while True:
                resp_raw = ws.recv()
                if not resp_raw:
                    break
                resp = json.loads(resp_raw)
                if resp.get("id") == target_id:
                    val = resp.get("result", {}).get("result", {}).get("value")
                    if isinstance(val, dict):
                        canvas = val
                    break

            if not canvas:
                raise RuntimeError("Không lấy được thông tin canvas Cocos (cc.game.canvas).")

            return canvas

        finally:
            try:
                ws.close()
            except Exception:
                pass
        
    def get_cocos_view_info(self) -> dict:
        """
        Lấy thông tin view của Cocos Creator qua Runtime.evaluate.

        Trả về dict dạng:
        {
            "design": {"width": number, "height": number} | null,
            "canvas": {"left": number, "top": number, "width": number, "height": number} | null,
            "frame":  {"width": number, "height": number} | null,
        }

        - design: kích thước gốc cc.view.getDesignResolutionSize() (ví dụ 1560x720).
        - canvas: vị trí + kích thước thật của cc.game.canvas trên màn hình (CSS pixel).
        - frame:  window.innerWidth / innerHeight (viewport hiện tại).
        """
        ws = self._open_ws()
        try:
            msg_id = 1

            # Enable Runtime
            ws.send(json.dumps({
                "id": msg_id,
                "method": "Runtime.enable",
            }))
            msg_id += 1

            expr = """
            (function () {
                var info = {
                    design: null,
                    canvas: null,
                    frame: null,
                };
                try {
                    if (typeof cc !== 'undefined' && cc.view && cc.game && cc.game.canvas) {
                        try {
                            var d = cc.view.getDesignResolutionSize();
                            info.design = { width: d.width, height: d.height };
                        } catch (e) {}

                        try {
                            var c = cc.game.canvas.getBoundingClientRect();
                            info.canvas = {
                                left: c.left,
                                top: c.top,
                                width: c.width,
                                height: c.height,
                            };
                        } catch (e) {}

                        try {
                            info.frame = {
                                width: window.innerWidth,
                                height: window.innerHeight,
                            };
                        } catch (e) {}
                    }
                } catch (e) {}
                return info;
            })()
            """

            ws.send(json.dumps({
                "id": msg_id,
                "method": "Runtime.evaluate",
                "params": {
                    "expression": expr,
                    "returnByValue": True,
                },
            }))
            eval_id = msg_id

            result = None
            while True:
                raw = ws.recv()
                resp = json.loads(raw)
                if resp.get("id") == eval_id:
                    result = resp
                    break

            if not result or "result" not in result:
                raise RuntimeError("DevTools: không nhận được kết quả Cocos view info")

            value = result["result"]["result"]["value"]
            if not isinstance(value, dict):
                return {}
            return value

        finally:
            try:
                ws.close()
            except Exception:
                pass
def read_layout_codes(self):
    """
    Trả về mảng 13 code lá bài từ DOM / Cocos trong trình duyệt.
    """
    expr = """
    (() => {
        // TODO: thay bằng script thật của game anh đang đọc card
        // tạm thời assume global window.MB_CURRENT_LAYOUT đã tồn tại
        return window.MB_CURRENT_LAYOUT || [];
    })()
    """

    result = self.send(
        "Runtime.evaluate",
        {"expression": expr, "returnByValue": True}
    )

    try:
        return result["result"]["value"]
    except Exception:
        return None
