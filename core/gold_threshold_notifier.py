from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional

import requests

from core.logger import log


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
    missing_3p_enabled: bool = False


class GoldThresholdNotifier:
    """
    Lightweight edge-triggered Telegram notifier.

    `check()` only compares three cached integers on the UI thread. HTTP work
    runs through one bounded worker queue, so bursts of cmd=205 never block UI
    or create an unbounded number of threads.
    """

    def __init__(self, config: Optional[GoldThresholdConfig] = None) -> None:
        self._config = config or GoldThresholdConfig()
        self._below_by_key: Dict[str, bool] = {}
        self._above_by_key: Dict[str, bool] = {}
        self._last_gold_by_key: Dict[str, int] = {}
        self._sap_lang_alerted_keys: Dict[str, None] = {}
        self._missing_3p_alerted_keys: Dict[str, None] = {}
        self._missing_3p_last_sent_at_by_tool: Dict[int, float] = {}
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
        missing_3p = alerts.get("missing_3p") or {}

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
            missing_3p_enabled=bool(missing_3p.get("enabled", False)),
        )

    def update_config(self, config: GoldThresholdConfig) -> None:
        """Cache config in RAM and re-arm state without emitting alerts."""
        self._config = config
        self._below_by_key = {
            key: bool(gold < config.min_threshold)
            for key, gold in self._last_gold_by_key.items()
        }
        self._above_by_key = {
            key: bool(gold > config.max_threshold)
            for key, gold in self._last_gold_by_key.items()
        }

    @staticmethod
    def _slot_int(tool_slot: int | str | None) -> int:
        try:
            slot = int(tool_slot or 1)
        except Exception:
            slot = 1
        return max(1, slot)

    @classmethod
    def _tool_label(cls, tool_slot: int | str | None) -> str:
        slot = cls._slot_int(tool_slot)
        return f"Tool {max(1, slot)}"

    @classmethod
    def _profile_key(cls, tool_slot: int | str | None, pid: str) -> str:
        slot = cls._slot_int(tool_slot)
        return f"tool{max(1, slot)}:{pid}"

    def check(self, profiles: Dict[str, Dict[str, Any]], tool_slot: int = 1) -> None:
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

            profile_key = self._profile_key(tool_slot, pid)
            self._last_gold_by_key[profile_key] = gold
            if cfg.min_enabled and cfg.min_threshold > 0:
                was_below = bool(self._below_by_key.get(profile_key, False))
                if gold < cfg.min_threshold and not was_below:
                    self._below_by_key[profile_key] = True
                    self._enqueue_alert("MIN", tool_slot, pid)
                elif gold > cfg.min_threshold:
                    self._below_by_key[profile_key] = False

            if cfg.max_enabled and cfg.max_threshold > 0:
                was_above = bool(self._above_by_key.get(profile_key, False))
                if gold > cfg.max_threshold and not was_above:
                    self._above_by_key[profile_key] = True
                    self._enqueue_alert("MAX", tool_slot, pid)
                elif gold < cfg.max_threshold:
                    self._above_by_key[profile_key] = False

    def send_test(self) -> bool:
        """Queue a test message using the current cached config."""
        cfg = self._config
        if not cfg.bot_token or not cfg.chat_id:
            return False
        return self._enqueue(cfg.bot_token, cfg.chat_id, "[Test Telegram] Tool 1")

    def is_intentional_foul_enabled(self) -> bool:
        """Return the cached feature toggle without reading config.json."""
        return bool(self._config.intentional_foul_enabled)

    def send_bi_sap_lang(self, hand_key: str, tool_slot: int = 1) -> bool:
        """Queue one best-effort alert per hand when intentional foul is applied."""
        cfg = self._config
        raw_key = str(hand_key or "").strip()
        if not cfg.intentional_foul_enabled or not raw_key:
            return False
        slot = self._slot_int(tool_slot)
        key = f"tool{slot}:{raw_key}"
        if key in self._sap_lang_alerted_keys:
            return False
        self._sap_lang_alerted_keys[key] = None
        if len(self._sap_lang_alerted_keys) > 128:
            oldest = next(iter(self._sap_lang_alerted_keys))
            self._sap_lang_alerted_keys.pop(oldest, None)
        if not cfg.bot_token or not cfg.chat_id:
            log.warning("[GOLD-ALERT] skip bị sập làng: thiếu token hoặc chat_id")
            return False
        return self._enqueue(cfg.bot_token, cfg.chat_id, f"[BỊ SẬP LÀNG] {self._tool_label(tool_slot)}")

    def is_missing_3p_enabled(self) -> bool:
        """Return the cached toggle for the new-hand room integrity alert."""
        return bool(self._config.missing_3p_enabled)

    def send_missing_3p(self, hand_key: str, tool_slot: int = 1) -> bool:
        """Queue at most one missing-3P alert for a WS hand burst."""
        cfg = self._config
        raw_key = str(hand_key or "").strip()
        if not cfg.missing_3p_enabled or not raw_key:
            return False
        slot = self._slot_int(tool_slot)
        key = f"tool{slot}:{raw_key}"
        if key in self._missing_3p_alerted_keys:
            return False

        # P1/P2/P3 WS snapshots may arrive in nearby polls. Coalesce that burst
        # without starting a timer thread or touching the database.
        now = time.monotonic()
        last_sent_at = float(self._missing_3p_last_sent_at_by_tool.get(slot, 0.0) or 0.0)
        if (now - last_sent_at) < 2.0:
            return False

        self._missing_3p_alerted_keys[key] = None
        if len(self._missing_3p_alerted_keys) > 128:
            oldest = next(iter(self._missing_3p_alerted_keys))
            self._missing_3p_alerted_keys.pop(oldest, None)
        if not cfg.bot_token or not cfg.chat_id:
            log.warning("[GOLD-ALERT] skip thiếu 3P: thiếu token hoặc chat_id")
            return False
        queued = self._enqueue(cfg.bot_token, cfg.chat_id, f"[THIẾU 3P] {self._tool_label(tool_slot)}")
        if queued:
            self._missing_3p_last_sent_at_by_tool[slot] = now
        return queued

    def stop(self) -> None:
        if self._stop_event.is_set():
            return
        self._stop_event.set()
        try:
            self._queue.put_nowait(None)
        except queue.Full:
            pass

    def _enqueue_alert(self, label: str, tool_slot: int, pid: str) -> None:
        cfg = self._config
        if not cfg.bot_token or not cfg.chat_id:
            log.warning("[GOLD-ALERT] skip %s: thiếu token hoặc chat_id", pid)
            return
        self._enqueue(cfg.bot_token, cfg.chat_id, f"[{label}] {self._tool_label(tool_slot)} - {pid}")

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


class ToolSlotGoldThresholdNotifier:
    """Per-tool adapter that preserves the old StrategyTab notifier interface."""

    def __init__(self, base: GoldThresholdNotifier, tool_slot: int) -> None:
        self.base = base
        self.tool_slot = GoldThresholdNotifier._slot_int(tool_slot)

    def check(self, profiles: Dict[str, Dict[str, Any]]) -> None:
        self.base.check(profiles, tool_slot=self.tool_slot)

    def send_test(self) -> bool:
        return self.base.send_test()

    def update_config(self, config: GoldThresholdConfig) -> None:
        self.base.update_config(config)

    def is_intentional_foul_enabled(self) -> bool:
        return self.base.is_intentional_foul_enabled()

    def send_bi_sap_lang(self, hand_key: str) -> bool:
        return self.base.send_bi_sap_lang(hand_key, tool_slot=self.tool_slot)

    def is_missing_3p_enabled(self) -> bool:
        return self.base.is_missing_3p_enabled()

    def send_missing_3p(self, hand_key: str) -> bool:
        return self.base.send_missing_3p(hand_key, tool_slot=self.tool_slot)
