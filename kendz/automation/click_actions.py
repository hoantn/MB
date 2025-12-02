# coding: utf-8
"""
Thuc thi cac hanh dong drag chuot cho game Mau Binh.

- Su dung Windows API (ctypes.windll.user32), KHONG can cai them thu vien.
- Mac dinh delay truoc va sau moi lan drag la 0.20 giay
  de tranh keo qua nhanh lam game khong kip xu ly.

API duoc cac module khac su dung:
- class DragAction
- ham perform_actions(actions, dry_run: bool, logger)
- alias Action = DragAction (de tuong thich import cu)
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Iterable

import ctypes


# Windows API
user32 = ctypes.windll.user32


@dataclass
class DragAction:
    x_from: int
    y_from: int
    x_to: int
    y_to: int
    # Tang cham: 0.20 giay truoc / sau moi lan drag
    delay_before: float = 1.20
    delay_after: float = 1.20
    description: str = ""


# De tuong thich voi import "Action" neu co
Action = DragAction


def _move_cursor(x: int, y: int) -> None:
    """Di chuyen chuot den toa do man hinh (x, y)."""
    user32.SetCursorPos(int(x), int(y))


def _mouse_down() -> None:
    """Nhan chuot trai."""
    MOUSEEVENTF_LEFTDOWN = 0x0002
    user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)


def _mouse_up() -> None:
    """Nha chuot trai."""
    MOUSEEVENTF_LEFTUP = 0x0004
    user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)


def perform_actions(actions: Iterable[DragAction], dry_run: bool, logger) -> None:
    """
    Thuc thi danh sach DragAction.

    - Neu dry_run=True: chi log, KHONG tac dong chuot.
    - Neu dry_run=False: dung Windows API de keo that.
    """
    for idx, act in enumerate(actions, start=1):
        logger.info(
            "ClickExec: Step %02d [DRAG] from=(%d, %d) to=(%d, %d) "
            "before=%.3f after=%.3f desc=%s",
            idx,
            act.x_from,
            act.y_from,
            act.x_to,
            act.y_to,
            act.delay_before,
            act.delay_after,
            act.description,
        )

        if dry_run:
            # Chi log, khong lam gi
            continue

        try:
            # Cho truoc khi bat dau drag
            time.sleep(float(act.delay_before))

            # Move -> down -> move -> up
            _move_cursor(act.x_from, act.y_from)
            _mouse_down()
            # Cho keo di 1 chut cho game bat kip
            # (duration keo co the tang neu can)
            _move_cursor(act.x_to, act.y_to)
            _mouse_up()

            # Cho sau khi drag xong
            time.sleep(float(act.delay_after))

        except Exception as exc:  # noqa: BLE001
            logger.error("ClickExec: loi khi thuc thi step %d: %s", idx, exc)
            # tiep tuc step tiep theo neu co loi
            continue
