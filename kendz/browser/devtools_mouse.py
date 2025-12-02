# coding: utf-8
"""
DevTools mouse driver cho Mau Binh.

- Gui su kien drag chuot vao tab trinh duyet (Chrome / CocCoc) qua DevTools,
  KHONG dung chuot he thong -> nguoi dung van su dung chuot binh thuong.

Yeu cau:
- Trinh duyet duoc khoi dong voi --remote-debugging-port khac nhau cho tung profile.
- Python da cai websocket-client: pip install websocket-client
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Iterable, Tuple
from urllib.request import urlopen

try:
    import websocket  # type: ignore[import]
except ImportError:  # pragma: no cover
    websocket = None

from kendz.automation.click_actions import DragAction

# OFFSET de map tu toa do screen -> toa do viewport
CONTENT_OFFSET_X = 0
CONTENT_OFFSET_Y = 80  # co the chinh lai neu lech

# ====== TỐC ĐỘ KÉO CHUNG CHO DEVTOOLS (CHỈNH Ở ĐÂY) ======
DEVTOOLS_DELAY_BEFORE = 0.10  # giay - doi truoc moi drag
DEVTOOLS_DELAY_AFTER = 0.10   # giay - doi sau moi drag
# Nếu muốn rất chậm: 0.8 / 0.6
# =========================================================


@dataclass
class DevtoolsConfig:
    host: str = "127.0.0.1"
    base_port: int = 9220  # port = base_port + profile_id


class DevtoolsSession:
    """Mot session DevTools toi 1 tab trinh duyet."""

    def __init__(self, host: str, port: int, logger) -> None:
        if websocket is None:
            raise RuntimeError(
                "Chua cai websocket-client. Chay: pip install websocket-client",
            )

        self.logger = logger
        self.host = host
        self.port = port
        self._id = 0

        # Lay danh sach target qua HTTP /json
        url = f"http://{host}:{port}/json"
        self.logger.info("DevTools: ket noi %s", url)
        with urlopen(url) as resp:  # noqa: S310
            targets = json.load(resp)

        page = None
        for t in targets:
            if t.get("type") == "page":
                page = t
                break
        if not page:
            raise RuntimeError(
                "Khong tim thay tab 'page' nao tren DevTools port %d" % port,
            )

        ws_url = page["webSocketDebuggerUrl"]
        self.logger.info("DevTools: mo websocket %s", ws_url)
        self.ws = websocket.create_connection(ws_url, ping_timeout=30)

        self._send("Input.setIgnoreInputEvents", {"ignore": False})

    def _send(self, method: str, params: dict | None = None) -> None:
        self._id += 1
        msg = {"id": self._id, "method": method, "params": params or {}}
        self.ws.send(json.dumps(msg))

    def dispatch_mouse_event(
        self,
        type_: str,
        x: float,
        y: float,
        button: str = "left",
        click_count: int = 1,
        buttons: int | None = None,
    ) -> None:
        params = {
            "type": type_,
            "x": float(x),
            "y": float(y),
            "button": button,
            "clickCount": click_count,
        }
        if buttons is not None:
            params["buttons"] = int(buttons)
        self._send("Input.dispatchMouseEvent", params)

    def close(self) -> None:
        try:
            self.ws.close()
        except Exception:
            pass


def _screen_to_page(
    screen_xy: Tuple[int, int],
    rect: Tuple[int, int, int, int],
) -> Tuple[float, float]:
    """Chuyen toa do man hinh sang toa do viewport DevTools."""
    left, top, _right, _bottom = rect
    page_x = screen_xy[0] - left - CONTENT_OFFSET_X
    page_y = screen_xy[1] - top - CONTENT_OFFSET_Y
    return float(page_x), float(page_y)


def perform_drag_plan_via_devtools(
    profile_id: int,
    rect: Tuple[int, int, int, int],
    actions: Iterable[DragAction],
    live: bool,
    logger,
    config: DevtoolsConfig | None = None,
) -> None:
    """Thuc thi 1 plan drag thong qua DevTools."""
    actions = list(actions)
    if not actions:
        logger.info("DevTools: khong co action nao, bo qua.")
        return

    mode = "LIVE" if live else "DRY-RUN"
    logger.info(
        "DevTools: thuc thi plan %d buoc cho profile=%d (mode=%s).",
        len(actions),
        profile_id,
        mode,
    )

    # DRY-RUN: chi log, khong gui su kien
    if not live:
        for idx, act in enumerate(actions, start=1):
            logger.info(
                "DevTools DRY-RUN Step %02d: from=(%d,%d) to=(%d,%d) desc=%s",
                idx,
                act.x_from,
                act.y_from,
                act.x_to,
                act.y_to,
                act.description,
            )
        return

    cfg = config or DevtoolsConfig()
    port = cfg.base_port + profile_id
    sess = DevtoolsSession(cfg.host, port, logger)

    try:
        for idx, act in enumerate(actions, start=1):
            logger.info(
                "DevTools LIVE Step %02d: from=(%d,%d) to=(%d,%d) desc=%s",
                idx,
                act.x_from,
                act.y_from,
                act.x_to,
                act.y_to,
                act.description,
            )

            # DÙ act.delay_before/after là gì,
            # ta ép dùng DEVTOOLS_DELAY_* để ổn định animation game.
            time.sleep(DEVTOOLS_DELAY_BEFORE)

            sx1, sy1 = act.x_from, act.y_from
            sx2, sy2 = act.x_to, act.y_to
            px1, py1 = _screen_to_page((sx1, sy1), rect)
            px2, py2 = _screen_to_page((sx2, sy2), rect)

            # move -> press -> move (keo) -> release
            sess.dispatch_mouse_event("mouseMoved", px1, py1, button="left")
            sess.dispatch_mouse_event(
                "mousePressed",
                px1,
                py1,
                button="left",
                click_count=1,
            )
            sess.dispatch_mouse_event(
                "mouseMoved",
                px2,
                py2,
                button="left",
                buttons=1,
            )
            sess.dispatch_mouse_event(
                "mouseReleased",
                px2,
                py2,
                button="left",
                click_count=1,
            )

            time.sleep(DEVTOOLS_DELAY_AFTER)

    finally:
        sess.close()
