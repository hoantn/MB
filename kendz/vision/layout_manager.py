# kendz/vision/layout_manager.py
"""Quản lý layout (toạ độ) của các lá bài trên màn hình game.

Ý tưởng:
- Dùng file YAML để định nghĩa toạ độ tương đối (0.0 - 1.0) cho từng lá bài.
- Cho phép nhiều layout khác nhau theo game_id / profile_id.

File cấu hình mặc định:
- config/layouts_mau_binh.yaml

Cấu trúc (ví dụ):

    mau_binh_siteA:
      profiles:
        1:
          self_cards:
            - index: 1
              x: 0.20
              y: 0.80
              w: 0.04
              h: 0.10
            - index: 2
              ...

Module này chỉ lo việc:
- Đọc YAML.
- Trả về danh sách CardRegion (Vision) tương ứng.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List

import yaml

from kendz.vision.layout_types import CardRegion


@dataclass
class SelfLayout:
    """Layout 13 lá của bản thân tại 1 profile/game."""

    card_regions: List[CardRegion]


class LayoutManager:
    """Đọc và cung cấp layout cho Vision."""

    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir
        self._cache: Dict[str, Dict[int, SelfLayout]] = {}

    def _load_yaml(self) -> dict:
        path = self.base_dir / "config" / "layouts_mau_binh.yaml"
        if not path.exists():
            raise FileNotFoundError(f"Không tìm thấy file layout: {path}")
        with path.open("r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}

    def get_self_layout(self, game_id: str, profile_id: int = 1) -> SelfLayout:
        """Lấy layout 13 lá cho 1 game_id + profile_id."""
        key = game_id
        if key not in self._cache:
            raw = self._load_yaml()
            game_cfg = raw.get(game_id)
            if not game_cfg:
                raise KeyError(f"Không tìm thấy layout cho game_id={game_id} trong layouts_mau_binh.yaml")

            profiles_cfg = game_cfg.get("profiles", {})
            profile_map: Dict[int, SelfLayout] = {}

            for pid_str, pdata in profiles_cfg.items():
                pid = int(pid_str)
                card_regions_cfg = pdata.get("self_cards", [])
                regions: List[CardRegion] = []
                for item in card_regions_cfg:
                    regions.append(
                        CardRegion(
                            x=float(item["x"]),
                            y=float(item["y"]),
                            w=float(item["w"]),
                            h=float(item["h"]),
                            index=int(item["index"]),
                        )
                    )
                profile_map[pid] = SelfLayout(card_regions=regions)

            self._cache[key] = profile_map

        profile_map = self._cache[key]
        if profile_id not in profile_map:
            raise KeyError(f"Không tìm thấy layout cho game_id={game_id} profile_id={profile_id}")
        return profile_map[profile_id]

    def save_custom_self_cards(self, game_id: str, profile_id: int, regions: List[CardRegion]) -> None:
        """Lưu layout 13 lá (self_cards) cho 1 game_id + profile_id vào YAML.

        - `regions` là danh sách CardRegion với toạ độ tương đối (0.0 - 1.0).
        - Ghi đè toàn bộ self_cards của profile tương ứng.
        - Tự làm tròn nhẹ toạ độ để file YAML gọn hơn.
        """
        # Đường dẫn file cấu hình
        path = self.base_dir / "config" / "layouts_mau_binh.yaml"
        path.parent.mkdir(parents=True, exist_ok=True)

        # Đọc YAML hiện tại (nếu có)
        if path.exists():
            with path.open("r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
        else:
            data = {}

        # Lấy / tạo cấu trúc game_id -> profiles -> profile_id
        game_cfg = data.setdefault(game_id, {})
        profiles_cfg = game_cfg.setdefault("profiles", {})

        profile_key = str(int(profile_id))
        cards_yaml = []
        for r in regions:
            cards_yaml.append(
                {
                    "index": int(r.index),
                    "x": float(f"{r.x:.6f}"),
                    "y": float(f"{r.y:.6f}"),
                    "w": float(f"{r.w:.6f}"),
                    "h": float(f"{r.h:.6f}"),
                }
            )

        profiles_cfg[profile_key] = {"self_cards": cards_yaml}

        # Ghi lại file YAML
        with path.open("w", encoding="utf-8") as f:
            yaml.safe_dump(data, f, allow_unicode=True, sort_keys=True)

        # Làm mới cache để lần sau đọc lại layout mới
        if game_id in self._cache:
            self._cache.pop(game_id, None)

