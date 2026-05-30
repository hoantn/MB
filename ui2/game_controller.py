from __future__ import annotations

import time
from typing import Dict, Optional, Any

from PySide6.QtWidgets import QApplication

from browser.devtools import DevToolsClient
from core.config import load_config

class GameController:
    """
    Điều khiển game Mậu Binh thông qua DevTools (CLICK THẬT).

    Linh hoạt khởi tạo:

        GameController(browser_manager=browser_manager, config=browser_manager.config)
        # hoặc:
        GameController(devtools_clients={"P1": client1, ...}, config=config)

    Vào/ra phòng đều bằng click:
    - Vào phòng: click nút Bet theo toạ độ.
    - Thoát phòng: click nút Exit 2 lần, nghỉ 200ms giữa 2 click.
    """

    def __init__(
        self,
        browser_manager: Optional[Any] = None,
        config: Optional[dict] = None,
        devtools_clients: Optional[Dict[str, DevToolsClient]] = None,
    ) -> None:
        self._browser_manager = browser_manager
        self._devtools = devtools_clients or {}

        # Ưu tiên config truyền vào; nếu thiếu và có browser_manager thì lấy từ đó
        if config is None and browser_manager is not None and hasattr(browser_manager, "config"):
            config = browser_manager.config

        if config is None:
            raise RuntimeError("GameController cần config (thiếu 'config.json' hoặc browser_manager.config)")

        self._cfg: dict = config
        if "game_ui" not in self._cfg:
            raise RuntimeError("config.json thiếu key 'game_ui'")

    # ------------------------------------------------------------------ utils

    def _client(self, profile_id: str) -> DevToolsClient:
        """
        Lấy DevToolsClient cho profile_id.

        Ưu tiên đi qua BrowserManager.ensure_tab(profile_id) nếu có.
        """
        if self._browser_manager is not None and hasattr(self._browser_manager, "ensure_tab"):
            tab = self._browser_manager.ensure_tab(profile_id)
            if tab is None or getattr(tab, "devtools", None) is None:
                raise RuntimeError(f"Không tìm thấy DevTools cho profile {profile_id}")
            return tab.devtools  # type: ignore[return-value]

        if profile_id not in self._devtools:
            raise RuntimeError(f"Không tìm thấy DevToolsClient cho profile {profile_id}")
        return self._devtools[profile_id]

    # ------------------------------------------------------------------ actions

    def click_bet(self, profile_id: str, bet: int) -> None:
        """
        Click nút mức cược trong lobby (100 / 500 / 1000 / ...).

        Ưu tiên toạ độ theo từng profile nếu có:

            config['game_ui']['bet_buttons_profile'][profile_id][str(bet)] = {'x': ..., 'y': ...}

        Nếu chưa có cho profile đó thì fallback về config chung:

            config['game_ui']['bet_buttons'][str(bet)]
        """
        cfg = load_config()
        game_ui = cfg.get("game_ui", {}) or {}
        bet_key = str(int(bet))

        pos = None

        # 1) Ưu tiên per-profile
        profile_bets = (game_ui.get("bet_buttons_profile") or {}).get(profile_id)
        if isinstance(profile_bets, dict):
            pos = profile_bets.get(bet_key)

        # 2) Fallback global nếu chưa có per-profile
        if not pos:
            bet_buttons = game_ui.get("bet_buttons") or {}
            pos = bet_buttons.get(bet_key)

        if not pos:
            raise RuntimeError(
                f"Chưa cấu hình toạ độ bet {bet_key} cho profile {profile_id} (hoặc global) trong config.json"
            )

        x = int(pos.get("x", 0))
        y = int(pos.get("y", 0))
        self._client(profile_id).mouse_click(x, y)

    def click_exit_room_1(self, profile_id: str) -> None:
        """
        Click NÚT THOÁT phòng #1 (Back / X) trong phòng chơi.

        LƯU Ý:
        - HÀM NÀY CHỈ THỰC HIỆN 1 CLICK.
        - Việc thoát phòng 2 click (có delay) sẽ do RoomEngine
          điều phối bằng QTimer, để không block UI.

        Toạ độ ưu tiên theo từng profile nếu có:

            config['game_ui']['exit_button_profile'][profile_id] = {'x': ..., 'y': ...}

        Nếu chưa có sẽ fallback về:

            config['game_ui']['exit_button']
        """
        cfg = load_config()
        game_ui = cfg.get("game_ui", {}) or {}

        pos = None

        # 1) Ưu tiên per-profile
        exit_profiles = game_ui.get("exit_button_profile") or {}
        profile_exit = exit_profiles.get(profile_id)
        if isinstance(profile_exit, dict):
            pos = profile_exit

        # 2) Fallback global
        if not pos:
            pos = game_ui.get("exit_button")

        if not pos:
            raise RuntimeError(
                f"Chưa cấu hình exit_button cho profile {profile_id} (hoặc global) trong config.json"
            )

        x = int(pos.get("x", 0))
        y = int(pos.get("y", 0))
        self._client(profile_id).mouse_click(x, y)
        
    def click_exit_room_2(self, profile_id: str) -> None:
        """
        Click NÚT THOÁT phòng #2 (Confirm) trong phòng chơi.

        KHÔNG fallback về exit #1 để tránh click sai.
        Bắt buộc phải có:
          - config['game_ui']['exit_button2_profile'][profile_id]
            hoặc
          - config['game_ui']['exit_button2'] (global)
        """
        cfg = load_config()
        game_ui = cfg.get("game_ui", {}) or {}

        pos = None

        # 1) Ưu tiên per-profile (#2)
        exit_profiles2 = game_ui.get("exit_button2_profile") or {}
        profile_exit2 = exit_profiles2.get(profile_id)
        if isinstance(profile_exit2, dict):
            pos = profile_exit2

        # 2) Fallback global #2 (cho phép)
        if not pos:
            pos = game_ui.get("exit_button2")

        # 3) KHÔNG fallback về exit #1 nữa
        if not pos:
            raise RuntimeError(
                f"Chưa cấu hình exit_button2 cho profile {profile_id} (hoặc global) trong config.json"
            )

        x = int(pos.get("x", 0))
        y = int(pos.get("y", 0))
        self._client(profile_id).mouse_click(x, y)
    
    def click_exit_room(self, profile_id: str) -> None:
        """Backward-compatible alias: dùng THOÁT PHÒNG #1."""
        self.click_exit_room_1(profile_id)

    def click_binh(self, profile_id: str) -> None:
        """Click nút Báo binh sau khi game đã nhận hình bài đặc biệt."""
        cfg = load_config()
        game_ui = cfg.get("game_ui", {}) or {}
        profile_map = game_ui.get("binh_button_profile") or {}
        pos = profile_map.get(profile_id)
        if not isinstance(pos, dict):
            raise RuntimeError(
                f"Chưa cấu hình nút Báo binh cho profile {profile_id} trong config.json"
            )
        self._client(profile_id).mouse_click(
            int(pos.get("x", 0)),
            int(pos.get("y", 0)),
        )

    def click_done(self, profile_id: str) -> None:
        """Click nút Xong sau khi game đã nhận hình bài xếp thường."""
        cfg = load_config()
        game_ui = cfg.get("game_ui", {}) or {}
        profile_map = game_ui.get("done_button_profile") or {}
        pos = profile_map.get(profile_id)
        if not isinstance(pos, dict):
            raise RuntimeError(
                f"Chưa cấu hình nút Xong cho profile {profile_id} trong config.json"
            )
        self._client(profile_id).mouse_click(
            int(pos.get("x", 0)),
            int(pos.get("y", 0)),
        )

    def click_taixiu_bet(self, profile_id: str, bet: int) -> None:
        """
        Click chip cược dùng riêng cho Tài/Xỉu.

        Chỉ đọc:
            config['game_ui']['taixiu']['tx_bet_points_profile'][profile_id][str(bet)]
        """
        cfg = load_config()
        game_ui = cfg.get("game_ui", {}) or {}
        taixiu = game_ui.get("taixiu", {}) or {}
        bet_key = str(int(bet))

        pos = None
        profile_bets = (taixiu.get("tx_bet_points_profile") or {}).get(profile_id)
        if isinstance(profile_bets, dict):
            pos = profile_bets.get(bet_key)

        if not pos:
            raise RuntimeError(
                f"Chưa cấu hình chip Tài/Xỉu bet {bet_key} cho profile {profile_id} trong config.json"
            )

        x = int(pos.get("x", 0))
        y = int(pos.get("y", 0))
        self._client(profile_id).mouse_click(x, y)

    def click_tai(self, profile_id: str) -> None:
        """
        Click nút TÀI theo profile.
        """
        cfg = load_config()
        game_ui = cfg.get("game_ui", {}) or {}
        taixiu = game_ui.get("taixiu", {}) or {}

        pos = None
        tai_profiles = taixiu.get("tai_button_profile") or {}
        profile_pos = tai_profiles.get(profile_id)
        if isinstance(profile_pos, dict):
            pos = profile_pos

        if not pos:
            raise RuntimeError(
                f"Chưa cấu hình nút TÀI cho profile {profile_id} trong config.json"
            )

        x = int(pos.get("x", 0))
        y = int(pos.get("y", 0))
        self._client(profile_id).mouse_click(x, y)

    def click_xiu(self, profile_id: str) -> None:
        """
        Click nút XỈU theo profile.
        """
        cfg = load_config()
        game_ui = cfg.get("game_ui", {}) or {}
        taixiu = game_ui.get("taixiu", {}) or {}

        pos = None
        xiu_profiles = taixiu.get("xiu_button_profile") or {}
        profile_pos = xiu_profiles.get(profile_id)
        if isinstance(profile_pos, dict):
            pos = profile_pos

        if not pos:
            raise RuntimeError(
                f"Chưa cấu hình nút XỈU cho profile {profile_id} trong config.json"
            )

        x = int(pos.get("x", 0))
        y = int(pos.get("y", 0))
        self._client(profile_id).mouse_click(x, y)
        
    def click_taixiu_confirm(self, profile_id: str) -> None:
        """
        Click nút ĐẶT CƯỢC theo profile.
        """
        cfg = load_config()
        game_ui = cfg.get("game_ui", {}) or {}
        taixiu = game_ui.get("taixiu", {}) or {}

        pos = None
        confirm_profiles = taixiu.get("confirm_button_profile") or {}
        profile_pos = confirm_profiles.get(profile_id)
        if isinstance(profile_pos, dict):
            pos = profile_pos

        if not pos:
            raise RuntimeError(
                f"Chưa cấu hình nút ĐẶT CƯỢC cho profile {profile_id} trong config.json"
            )

        x = int(pos.get("x", 0))
        y = int(pos.get("y", 0))
        self._client(profile_id).mouse_click(x, y)
        
    def play_tai_xiu_once(self, profile_id: str, bet: int, side: str, delay_ms: int) -> None:
        """
        1 chuỗi đúng:
        - click nút TÀI hoặc XỈU
        - nghỉ delay_ms
        - click mức cược
        - nghỉ delay_ms
        - click nút ĐẶT CƯỢC
        """
        side_norm = (side or "").strip().lower()
        if side_norm not in ("tai", "xiu"):
            raise RuntimeError(f"Side không hợp lệ: {side}")

        if side_norm == "tai":
            self.click_tai(profile_id)
        else:
            self.click_xiu(profile_id)

        if delay_ms > 0:
            time.sleep(delay_ms / 1000.0)

        self.click_taixiu_bet(profile_id, int(bet))

        if delay_ms > 0:
            time.sleep(delay_ms / 1000.0)

        self.click_taixiu_confirm(profile_id)

    def play_tai_xiu_chip_plan(self, profile_id: str, chips: list, side: str, delay_ms: int) -> None:
        """
        Luong rieng cho Xao Vang: chon cua, bam tung chip that tren game,
        roi bam DAT CUOC. Khong nhap tien tu do.
        """
        side_norm = (side or "").strip().lower()
        if side_norm not in ("tai", "xiu"):
            raise RuntimeError(f"Side khong hop le: {side}")

        chip_values = []
        for chip in chips or []:
            value = int(chip)
            if value > 0:
                chip_values.append(value)

        if not chip_values:
            raise RuntimeError("Chua co chip de dat cuoc")

        if side_norm == "tai":
            self.click_tai(profile_id)
        else:
            self.click_xiu(profile_id)

        if delay_ms > 0:
            time.sleep(delay_ms / 1000.0)

        for chip in chip_values:
            self.click_taixiu_bet(profile_id, chip)
            if delay_ms > 0:
                time.sleep(delay_ms / 1000.0)

        self.click_taixiu_confirm(profile_id)
        
    # ==========================================================
    # AUTO SPAM / CHAT
    # ==========================================================

    def _get_auto_spam_pos(self, profile_id: str, key: str) -> Dict[str, int]:
        """
        key:
        - 'message_input_profile'
        - 'send_button_profile'
        """
        cfg = load_config()
        game_ui = cfg.get("game_ui", {}) or {}
        auto_spam = game_ui.get("auto_spam", {}) or {}

        profile_map = auto_spam.get(key) or {}
        pos = profile_map.get(profile_id)

        if not isinstance(pos, dict):
            raise RuntimeError(
                f"Chưa cấu hình {key} cho profile {profile_id} trong config.json"
            )

        return {
            "x": int(pos.get("x", 0)),
            "y": int(pos.get("y", 0)),
        }

    def click_auto_spam_input(self, profile_id: str) -> None:
        pos = self._get_auto_spam_pos(profile_id, "message_input_profile")
        self._client(profile_id).mouse_click(pos["x"], pos["y"])

    def click_auto_spam_send(self, profile_id: str) -> None:
        pos = self._get_auto_spam_pos(profile_id, "send_button_profile")
        self._client(profile_id).mouse_click(pos["x"], pos["y"])

    def _insert_text_best_effort(self, profile_id: str, text: str) -> None:
        """
        Ưu tiên API nhập text nếu DevToolsClient có sẵn.
        Nếu codebase của bạn đang dùng tên hàm khác, chỉ cần sửa helper này.
        """
        client = self._client(profile_id)

        if hasattr(client, "insert_text"):
            client.insert_text(text)
            return

        if hasattr(client, "type_text"):
            client.type_text(text)
            return

        if hasattr(client, "send_text"):
            client.send_text(text)
            return

        if hasattr(client, "paste_text"):
            client.paste_text(text)
            return

        raise RuntimeError(
            "DevToolsClient chưa có API nhập text. "
            "Hãy map helper _insert_text_best_effort() vào đúng hàm gõ chữ hiện có của bạn."
        )

    def send_auto_spam_message(
        self,
        profile_id: str,
        message: str,
        click_delay_ms: int = 300,
        send_delay_ms: int = 180,
    ) -> None:
        """
        Luồng:
        1) click ô nhập chat
        2) nhập text
        3) nghỉ nhẹ
        4) click nút gửi
        """
        msg = str(message or "").strip()
        if not msg:
            raise RuntimeError("Tin nhắn rỗng, không thể gửi auto spam")

        self.click_auto_spam_input(profile_id)

        if click_delay_ms > 0:
            time.sleep(click_delay_ms / 1000.0)

        self._insert_text_best_effort(profile_id, msg)

        if send_delay_ms > 0:
            time.sleep(send_delay_ms / 1000.0)

        self.click_auto_spam_send(profile_id)
