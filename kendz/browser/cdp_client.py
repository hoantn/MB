from __future__ import annotations

import base64
from typing import Any, Dict, Optional, Tuple

from .cdp_connection import CDPConnection
from .cdp_tab_finder import get_websocket_debugger_url


class CDPSession:
    """Session DevTools cho 1 tab page."""

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 9222,
        timeout: float = 5.0,
    ) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout

        self._conn: Optional[CDPConnection] = None
        self._initialized: bool = False

    # ------------------------------------------------------------------ #
    # Life-cycle
    # ------------------------------------------------------------------ #
    def connect(self) -> None:
        """Kết nối tới websocketDevToolsUrl của tab 'page' đầu tiên."""
        ws_url = get_websocket_debugger_url(self.host, self.port)
        if not ws_url:
            raise RuntimeError(
                "CDPSession: Không tìm thấy tab 'page' nào trên DevTools "
                f"(host={self.host}, port={self.port}). "
                "Hãy đảm bảo Chrome đã mở và tab game đã được mở."
            )

        conn = CDPConnection(ws_url, timeout=self.timeout)
        conn.connect()
        self._conn = conn

        # Bật các domain cần thiết
        self._ensure_initialized()

    def close(self) -> None:
        if self._conn:
            self._conn.close()
        self._conn = None
        self._initialized = False

    # ------------------------------------------------------------------ #
    # Internal
    # ------------------------------------------------------------------ #
    def _ensure_initialized(self) -> None:
        if self._initialized:
            return
        if not self._conn:
            raise RuntimeError("CDPSession: chưa connect.")

        # Bật Page + Runtime để có thể chụp screenshot, đọc layout
        self._conn.send_cmd("Page.enable")
        self._conn.send_cmd("Runtime.enable")
        self._initialized = True

    def _cmd(self, method: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        if not self._conn:
            raise RuntimeError("CDPSession: chưa connect.")
        return self._conn.send_cmd(method, params)

    # ------------------------------------------------------------------ #
    # Public APIs
    # ------------------------------------------------------------------ #
    def capture_screenshot_png(self, format: str = "png", quality: Optional[int] = None) -> bytes:
        """Chụp screenshot tab hiện tại, trả về bytes PNG."""
        self._ensure_initialized()

        params: Dict[str, Any] = {"format": format}
        if quality is not None and format == "jpeg":
            params["quality"] = int(quality)

        resp = self._cmd("Page.captureScreenshot", params)
        result = resp.get("result") or {}
        data_b64 = result.get("data")
        if not data_b64:
            raise RuntimeError("CDPSession: không nhận được data screenshot.")

        return base64.b64decode(data_b64)

    def get_layout_metrics(self) -> Tuple[int, int]:
        """Lấy kích thước viewport để quy đổi normalized region.

        Trả về:
            (width, height)
        """
        self._ensure_initialized()
        resp = self._cmd("Page.getLayoutMetrics", {})
        result = resp.get("result") or {}

        # Theo DevTools protocol:
        # - CSS layout viewport: cssLayoutViewport / visualViewport
        # - Chúng ta ưu tiên cssLayoutViewport
        css_layout = result.get("cssLayoutViewport") or {}
        width = int(css_layout.get("clientWidth", 0))
        height = int(css_layout.get("clientHeight", 0))

        if width <= 0 or height <= 0:
            # Fallback sang visualViewport
            visual = result.get("visualViewport") or {}
            width = int(visual.get("clientWidth", 0))
            height = int(visual.get("clientHeight", 0))

        if width <= 0 or height <= 0:
            # Cuối cùng fallback sang device
            content = result.get("contentSize") or {}
            width = int(content.get("width", 0))
            height = int(content.get("height", 0))

        if width <= 0 or height <= 0:
            raise RuntimeError("CDPSession: không lấy được layout viewport hợp lệ.")

        return width, height
