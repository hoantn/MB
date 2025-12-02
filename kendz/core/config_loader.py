# kendz/core/config_loader.py
"""Module chịu trách nhiệm:
- Đọc file config YAML
- Validate bằng Pydantic
- Gom thành một đối tượng KendzConfig duy nhất

Lưu ý:
- Tuyệt đối không viết logic nghiệp vụ tại đây
- Chỉ xử lý "cấu hình" và "merge" cấu hình
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List

import yaml
from pydantic import BaseModel, Field, ValidationError


# ----- Định nghĩa schema config -----

class CoreConfig(BaseModel):
    """Cấu hình cơ bản cho Kendz (từ file config/core.yaml)."""
    log_level: str = Field(default="INFO", description="Mức log mặc định")
    language: str = Field(default="vi", description="Ngôn ngữ hiển thị")
    default_game_id: str = Field(default="mau_binh_siteA", description="Game mặc định")


class ProfileConfig(BaseModel):
    """Cấu hình cho từng profile Chrome (từ config/profiles.yaml)."""
    id: int
    name: str
    chrome_profile_path: str
    game_id: str


class StrategyConfig(BaseModel):
    """Cấu hình chiến lược global (từ config/strategy.yaml)."""
    global_mode: str = Field(default="balance", description="Chế độ chiến lược toàn hệ thống")


class VisionConfig(BaseModel):
    """Cấu hình cho module Vision (từ config/vision.yaml).

    Các trường chính:
    - fps: số khung hình xử lý mỗi giây
    - capture_mode: screen / window (giai đoạn đầu dùng screen)
    - card_confidence_threshold: ngưỡng tin cậy nhận diện lá bài
    - debug_save_frame: có lưu ảnh debug hay không
    """
    fps: int = Field(default=8, ge=1, le=60, description="FPS xử lý của Vision")
    capture_mode: str = Field(default="screen", description="Chế độ capture: screen/window")
    card_confidence_threshold: float = Field(
        default=0.78, ge=0.0, le=1.0, description="Ngưỡng tin cậy nhận diện lá bài"
    )
    debug_save_frame: bool = Field(default=True, description="Lưu ảnh debug khi cần")


@dataclass
class KendzConfig:
    """Gói toàn bộ cấu hình Kendz thành một object."""

    core: CoreConfig
    profiles: List[ProfileConfig]
    strategy: StrategyConfig
    vision: VisionConfig


# ----- Hàm load YAML hỗ trợ -----

def _load_yaml(path: Path) -> dict:
    """Đọc file YAML và trả về dict.

    Nếu file không tồn tại:
    - Ném exception rõ ràng để dev biết thiếu file cấu hình.
    """
    if not path.exists():
        raise FileNotFoundError(f"Không tìm thấy file config: {path}")

    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return data


# ----- Hàm public dùng để load toàn bộ config Kendz -----

def load_kendz_config(base_dir: Path | None = None) -> KendzConfig:
    """Hàm public để load toàn bộ config Kendz."""
    if base_dir is None:
        # base_dir là folder gốc của project Kendz
        base_dir = Path(__file__).resolve().parents[2]

    config_dir = base_dir / "config"

    core_raw = _load_yaml(config_dir / "core.yaml")
    profiles_raw = _load_yaml(config_dir / "profiles.yaml")
    strategy_raw = _load_yaml(config_dir / "strategy.yaml")
    vision_raw = _load_yaml(config_dir / "vision.yaml")

    try:
        core_cfg = CoreConfig(**core_raw.get("core", {}))
        profiles_cfg = [ProfileConfig(**p) for p in profiles_raw.get("profiles", [])]
        strategy_cfg = StrategyConfig(**strategy_raw.get("strategy", {}))
        vision_cfg = VisionConfig(**vision_raw.get("vision", {}))
    except ValidationError as e:
        raise RuntimeError(f"Lỗi validate cấu hình Kendz: {e}") from e

    if not profiles_cfg:
        raise RuntimeError("Chưa cấu hình bất kỳ profile nào trong config/profiles.yaml")

    return KendzConfig(core=core_cfg, profiles=profiles_cfg, strategy=strategy_cfg, vision=vision_cfg)
