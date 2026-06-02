from __future__ import annotations

import queue
import threading
from dataclasses import dataclass
from typing import Any, Dict, Optional

import requests

from core.logger import log
from core.tool_instance import get_tool_name


PROFILE_IDS = ("P1", "P2", "P3")


@dataclass(frozen=True)
class GoldThresholdConfig:
    bot_token: str = ""
    chat_id: str = ""
    min_enabled: bool = False
    min_threshold: int = 0
    max_enabled: bool = False
    max_threshold: int = 0
    intentional_foul_enabled: bool = False


class GoldThresholdNotifier:
    """
    Lightweight edge-triggered Telegram notifier.

    `check()` only compares three cached integers on the UI thread. HTTP work
    runs through one bounded worker queue, so bursts of cmd=205 never block UI
    or create an unbounded number of threads.
    """

    def __init__(self, config: Optional[GoldThresholdConfig] = None) -> None:
        self._config = config or GoldThresholdConfig()
        self._below_by_pid: Dict[str, bool] = {pid: False for pid in PROFILE_IDS}
        self._above_by_pid: Dict[str, bool] = {pid: False for pid in PROFILE_IDS}
        self._last_gold_by_pid: Dict[str, int] = {}
        self._sap_lang_alerted_keys: Dict[str, None] = {}
        self._queue: "queue.Queue[Optional[tuple[str, str, str]]]" = queue.Queue(maxsize=32)
        self._stop_event = threading.Event()
        self._worker = threading.Thread(
            target=self._worker_loop,
            name="GoldThresholdTelegram",
            daemon=True,
        )
        self._worker.start()

    @staticmethod
    def config_from_dict(data: Dict[str, Any]) -> GoldThresholdConfig:
        root = data.get("auto_settings") or {}
        telegram = root.get("telegram") or {}
        alerts = root.get("alerts") or {}
        # Read the old single threshold as Min until the user saves the new form.
        min_alert = alerts.get("gold_min_threshold")
        if not isinstance(min_alert, dict):
            min_alert = alerts.get("gold_threshold") or {}
        max_alert = alerts.get("gold_max_threshold") or {}
        intentional_foul = alerts.get("opp_sap_lang_intentional_foul") or {}

        def _threshold(alert: Dict[str, Any]) -> int:
            try:
                return max(0, int(alert.get("threshold") or 0))
            except Exception:
                return 0

        return GoldThresholdConfig(
            bot_token=str(telegram.get("bot_token") or "").strip(),
            chat_id=str(telegram.get("chat_id") or "").strip(),
            min_enabled=bool(min_alert.get("enabled", False)),
            min_threshold=_threshold(min_alert),
            max_enabled=bool(max_alert.get("enabled", False)),
            max_threshold=_threshold(max_alert),
            intentional_foul_enabled=bool(intentional_foul.get("enabled", False)),
        )

    def update_config(self, config: GoldThresholdConfig) -> None:
        """Cache config in RAM and re-arm state without emitting alerts."""
        self._config = config
        self._below_by_pid = {
            pid: bool(gold < config.min_threshold)
            for pid, gold in self._last_gold_by_pid.items()
            if pid in PROFILE_IDS
        }
        self._above_by_pid = {
            pid: bool(gold > config.max_threshold)
            for pid, gold in self._last_gold_by_pid.items()
            if pid in PROFILE_IDS
        }
        for pid in PROFILE_IDS:
            self._below_by_pid.setdefault(pid, False)
            self._above_by_pid.setdefault(pid, False)

    def check(self, profiles: Dict[str, Dict[str, Any]]) -> None:
        """Evaluate threshold crossings from a RoomEngine monitoring snapshot."""
        cfg = self._config

        for pid in PROFILE_IDS:
            state = profiles.get(pid) or {}
            gold_raw = state.get("gold")
            if gold_raw is None:
                continue
            try:
                gold = int(gold_raw)
            except Exception:
                continue

            self._last_gold_by_pid[pid] = gold
            if cfg.min_enabled and cfg.min_threshold > 0:
                was_below = bool(self._below_by_pid.get(pid, False))
                if gold < cfg.min_threshold and not was_below:
                    self._below_by_pid[pid] = True
                    self._enqueue_alert("MIN", pid)
                elif gold > cfg.min_threshold:
                    self._below_by_pid[pid] = False

            if cfg.max_enabled and cfg.max_threshold > 0:
                was_above = bool(self._above_by_pid.get(pid, False))
                if gold > cfg.max_threshold and not was_above:
                    self._above_by_pid[pid] = True
                    self._enqueue_alert("MAX", pid)
                elif gold < cfg.max_threshold:
                    self._above_by_pid[pid] = False

    def send_test(self) -> bool:
        """Queue a test message using the current cached config."""
        cfg = self._config
        if not cfg.bot_token or not cfg.chat_id:
            return False
        return self._enqueue(cfg.bot_token, cfg.chat_id, f"[Test Telegram] {get_tool_name()}")

    def is_intentional_foul_enabled(self) -> bool:
        """Return the cached feature toggle without reading config.json."""
        return bool(self._config.intentional_foul_enabled)

    def send_bi_sap_lang(self, hand_key: str) -> bool:
        """Queue one best-effort alert per hand when intentional foul is applied."""
        cfg = self._config
        key = str(hand_key or "").strip()
        if not cfg.intentional_foul_enabled or not key:
            return False
        if key in self._sap_lang_alerted_keys:
            return False
        self._sap_lang_alerted_keys[key] = None
        if len(self._sap_lang_alerted_keys) > 128:
            oldest = next(iter(self._sap_lang_alerted_keys))
            self._sap_lang_alerted_keys.pop(oldest, None)
        if not cfg.bot_token or not cfg.chat_id:
            log.warning("[GOLD-ALERT] skip bị sập làng: thiếu token hoặc chat_id")
            return False
        return self._enqueue(cfg.bot_token, cfg.chat_id, f"[BỊ SẬP LÀNG] {get_tool_name()}")

    def stop(self) -> None:
        if self._stop_event.is_set():
            return
        self._stop_event.set()
        try:
            self._queue.put_nowait(None)
        except queue.Full:
            pass

    def _enqueue_alert(self, label: str, pid: str) -> None:
        cfg = self._config
        if not cfg.bot_token or not cfg.chat_id:
            log.warning("[GOLD-ALERT] skip %s: thiếu token hoặc chat_id", pid)
            return
        self._enqueue(cfg.bot_token, cfg.chat_id, f"[{label}] {get_tool_name()} - {pid}")

    def _enqueue(self, token: str, chat_id: str, message: str) -> bool:
        try:
            self._queue.put_nowait((token, chat_id, message))
            return True
        except queue.Full:
            log.warning("[GOLD-ALERT] queue đầy, bỏ qua message=%s", message)
            return False

    def _worker_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                job = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue
            if job is None:
                return
            token, chat_id, message = job
            try:
                response = requests.post(
                    f"https://api.telegram.org/bot{token}/sendMessage",
                    data={"chat_id": chat_id, "text": message},
                    timeout=5,
                )
                response.raise_for_status()
            except Exception as exc:
                # requests exceptions may contain the URL, which embeds the bot token.
                log.warning("[GOLD-ALERT] gửi Telegram lỗi: %s", type(exc).__name__)
