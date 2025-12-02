
from __future__ import annotations

"""Window binding cho Kendz (Phase 8 – bước chuẩn bị auto-click).

Thiết kế:
- Mỗi process sẽ gắn (bind) với 1 cửa sổ trình duyệt cụ thể.
- Việc tìm kiếm và ánh xạ toạ độ đều được thực hiện trong module này.
- Giai đoạn hiện tại: CHỈ dùng để tính toán và log toạ độ, chưa gửi click thật.

Lưu ý:
- Implementation hiện tại sử dụng Win32 API qua ctypes, nên chỉ hoạt động trên Windows.
- Nếu chạy trên hệ điều hành khác, module sẽ raise RuntimeError với thông báo rõ ràng.
"""  # noqa: D205, D400

from dataclasses import dataclass
from typing import Optional, Tuple

import ctypes
import ctypes.wintypes as wt
import os
from pathlib import Path

import yaml


USER32 = ctypes.windll.user32 if os.name == "nt" else None


@dataclass
class BoundWindow:
    """Thông tin 1 cửa sổ đã bind.

    Thuộc tính:
        hwnd: Handle của cửa sổ (Win32).
        title: Tiêu đề cửa sổ.
        rect: (left, top, right, bottom) theo toạ độ màn hình.
    """  # noqa: D205, D400

    hwnd: int
    title: str
    rect: Tuple[int, int, int, int]

    @property
    def left(self) -> int:
        return self.rect[0]

    @property
    def top(self) -> int:
        return self.rect[1]

    @property
    def right(self) -> int:
        return self.rect[2]

    @property
    def bottom(self) -> int:
        return self.rect[3]

    @property
    def width(self) -> int:
        return self.right - self.left

    @property
    def height(self) -> int:
        return self.bottom - self.top

    def to_screen_from_rel(self, x_rel: float, y_rel: float) -> Tuple[int, int]:
        """Chuyển toạ độ tương đối (0..1) sang toạ độ màn hình (pixel).

        Args:
            x_rel: Toạ độ X tương đối trong [0.0, 1.0].
            y_rel: Toạ độ Y tương đối trong [0.0, 1.0].

        Returns:
            (x, y) nguyên, toạ độ màn hình.
        """  # noqa: D401
        x_rel = max(0.0, min(1.0, x_rel))
        y_rel = max(0.0, min(1.0, y_rel))

        x = int(self.left + x_rel * self.width)
        y = int(self.top + y_rel * self.height)
        return x, y


def _ensure_windows() -> None:
    if os.name != "nt" or USER32 is None:
        raise RuntimeError(
            "WindowBinding chỉ hỗ trợ trên Windows (os.name == 'nt').",
        )


def _get_window_text(hwnd: int) -> str:
    length = USER32.GetWindowTextLengthW(hwnd)
    buffer = ctypes.create_unicode_buffer(length + 1)
    USER32.GetWindowTextW(hwnd, buffer, length + 1)
    return buffer.value


def _get_window_rect(hwnd: int) -> Tuple[int, int, int, int]:
    rect = wt.RECT()
    if not USER32.GetWindowRect(hwnd, ctypes.byref(rect)):
        raise RuntimeError(f"GetWindowRect thất bại cho hwnd={hwnd}")
    return rect.left, rect.top, rect.right, rect.bottom


def find_window_by_title_keyword(keyword: str) -> Optional[BoundWindow]:
    """Tìm cửa sổ có chứa keyword trong title (case-insensitive).

    Trả về:
        BoundWindow hoặc None nếu không tìm thấy.
    """  # noqa: D401
    _ensure_windows()

    matches = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)
    def enum_proc(hwnd, lparam):  # type: ignore[override]
        if not USER32.IsWindowVisible(hwnd):
            return True
        title = _get_window_text(hwnd)
        if not title:
            return True
        if keyword.lower() in title.lower():
            rect = _get_window_rect(hwnd)
            matches.append(BoundWindow(hwnd=int(hwnd), title=title, rect=rect))
        return True

    USER32.EnumWindows(enum_proc, 0)

    if not matches:
        return None

    # Nếu có nhiều cửa sổ match, ưu tiên cái đầu tiên (hoặc sau này có thể sort).
    return matches[0]


def load_automation_config(config_path: Path) -> dict:
    """Đọc file config automation YAML đơn giản.

    Cấu trúc kỳ vọng:

    ```yaml
    mau_binh_siteA:
      profiles:
        1:
          window_title_keyword: "GO88 - P1"
        2:
          window_title_keyword: "GO88 - P2"
        3:
          window_title_keyword: "GO88 - P3"
    ```
    """  # noqa: D401
    with config_path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def bind_window_for_profile(
    game_id: str,
    profile_id: int,
    project_root: Path,
    config_file: str = "config/automation.yaml",
) -> BoundWindow:
    """Bind cửa sổ trình duyệt cho 1 profile cụ thể.

    Args:
        game_id: ID game, ví dụ: "mau_binh_siteA".
        profile_id: ID profile (1, 2, 3, ...).
        project_root: Thư mục gốc project.
        config_file: Đường dẫn tương đối tới file YAML automation.

    Returns:
        BoundWindow nếu tìm thấy.

    Raises:
        RuntimeError: nếu không đọc được config, không có entry, hoặc không tìm thấy cửa sổ.
    """  # noqa: D401
    _ensure_windows()

    cfg_path = (project_root / config_file).resolve()
    if not cfg_path.exists():
        raise RuntimeError(f"Không tìm thấy file config automation: {cfg_path}")

    cfg = load_automation_config(cfg_path)

    game_cfg = cfg.get(game_id)
    if not game_cfg:
        raise RuntimeError(f"Không tìm thấy cấu hình cho game_id={game_id} trong {cfg_path}")

    profiles_cfg = game_cfg.get("profiles", {})
    p_cfg = profiles_cfg.get(profile_id) or profiles_cfg.get(str(profile_id))
    if not p_cfg:
        raise RuntimeError(
            f"Không tìm thấy cấu hình profile_id={profile_id} trong game_id={game_id}",
        )

    keyword = p_cfg.get("window_title_keyword")
    if not keyword:
        raise RuntimeError(
            f"profile_id={profile_id} không có 'window_title_keyword' trong {cfg_path}",
        )

    bw = find_window_by_title_keyword(keyword)
    if not bw:
        raise RuntimeError(
            f"Không tìm thấy cửa sổ nào có title chứa '{keyword}' (profile_id={profile_id}).",
        )

    return bw
