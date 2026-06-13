from __future__ import annotations

import threading
from typing import Any, Optional

from PySide6.QtCore import QObject, Signal

from core.logger import log


class XaoVangToolAdapter(QObject):
    """Route an embedded XaoVangTab to the GameController of one tool slot."""

    _done = Signal(str, str)
    _error = Signal(str, str)
    _started = Signal(str, str)

    def __init__(
        self,
        *,
        slot: int,
        xao_vang_tab,
        game_controller,
        action_gate=None,
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self.slot = int(slot or 1)
        self.xao_vang_tab = xao_vang_tab
        self.game_controller = game_controller
        self.action_gate = action_gate
        self._browser_manager = getattr(game_controller, "_browser_manager", None)
        self._started.connect(self._on_started)
        self._done.connect(self._on_done)
        self._error.connect(self._on_error)
        self.xao_vang_tab.request_play_tai_xiu.connect(self.play)

    def play(self, profile_id: str, params: dict) -> None:
        payload = dict(params or {})
        pid = str(profile_id or "P1")
        log.info("[XaoVangToolAdapter] slot=%s request pid=%s params=%s", self.slot, pid, payload)

        lease = None
        if self.action_gate is not None:
            lease, busy = self.action_gate.try_acquire(pid, "xao_vang", owner="XaoVangToolAdapter")
            if busy is not None:
                msg = (
                    f"Tool {self.slot}: {pid} dang ban ({busy.action}); "
                    "bo qua Xao Vang de tranh xung dot"
                )
                log.warning(
                    "[XaoVangToolAdapter] slot=%s pid=%s blocked by action=%s",
                    self.slot,
                    pid,
                    busy.action,
                )
                self._error.emit(pid, msg)
                return

        self._started.emit(pid, f"Tool {self.slot}: Dang xao vang {pid}...")

        def _worker() -> None:
            try:
                if self._browser_manager is not None and hasattr(self._browser_manager, "reload_config"):
                    self._browser_manager.reload_config()

                side = str(payload.get("side") or "").strip().lower()
                bet = int(payload.get("bet") or 0)
                delay_ms = int(payload.get("delay_ms") or 0)
                chips = payload.get("chips")

                if chips:
                    self.game_controller.play_tai_xiu_chip_plan(
                        profile_id=pid,
                        chips=list(chips),
                        side=side,
                        delay_ms=delay_ms,
                    )
                else:
                    self.game_controller.play_tai_xiu_once(
                        profile_id=pid,
                        bet=bet,
                        side=side,
                        delay_ms=delay_ms,
                    )

                msg = f"Tool {self.slot}: Da choi {'TAI' if side == 'tai' else 'XIU'} | {pid} | Bet {bet}"
                log.info("[XaoVangToolAdapter] slot=%s success pid=%s side=%s bet=%s chips=%s", self.slot, pid, side, bet, chips)
                self._done.emit(pid, msg)
            except Exception as exc:
                log.exception("[XaoVangToolAdapter] slot=%s pid=%s failed", self.slot, pid)
                self._error.emit(pid, f"Tool {self.slot}: Loi: {exc}")
            finally:
                if self.action_gate is not None:
                    self.action_gate.release(lease)

        threading.Thread(
            target=_worker,
            name=f"xao-vang-tool{self.slot}-{pid}",
            daemon=True,
        ).start()

    def _on_started(self, profile_id: str, message: str) -> None:
        try:
            self.xao_vang_tab.lbl_status.setText(f"{profile_id}: {message}")
        except Exception:
            pass

    def _on_done(self, profile_id: str, message: str) -> None:
        try:
            self.xao_vang_tab.dat_trang_thai_profile(profile_id, message)
        except Exception:
            pass

    def _on_error(self, profile_id: str, message: str) -> None:
        try:
            self.xao_vang_tab.dat_trang_thai_profile(profile_id, message)
        except Exception:
            pass
