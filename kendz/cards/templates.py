# kendz/cards/templates.py
"""Quản lý template lá bài (52 lá + biến thể) cho Mậu Binh.

Thiết kế:
- Thư mục template cho 1 game_id:
    data/card_templates/<game_id>/
- Trong thư mục này chứa TẤT CẢ ảnh template cho 52 lá, tên file dạng:
    2H_1.png, 2H_2.png, 3D_1.png, ...
  trong đó:
    - prefix 2 ký tự đầu: mã lá bài (rank + suit)
    - phần sau "_" là chỉ số biến thể tăng dần (1, 2, 3, ...)

Module này KHÔNG phụ thuộc AppContext, mọi đường dẫn đều truyền qua base_dir.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List

import re

CARD_FILENAME_RE = re.compile(r"^([2-9TJQKA][CDHS])_(\d+)\.(png|jpg|jpeg)$", re.IGNORECASE)
BASE_CARD_RE = re.compile(r"^([2-9TJQKA][CDHS])\.(png|jpg|jpeg)$", re.IGNORECASE)

CARD_CODES: List[str] = [
    r + s
    for s in ["C", "D", "H", "S"]
    for r in ["2", "3", "4", "5", "6", "7", "8", "9", "T", "J", "Q", "K", "A"]
]


@dataclass
class VariantInfo:
    code: str
    variant_index: int
    filename: str
    path: Path


def get_templates_dir(base_dir: Path, game_id: str) -> Path:
    """Trả về thư mục chứa template: data/card_templates/<game_id>."""
    return base_dir / "data" / "card_templates" / game_id


def find_next_variant_index(base_dir: Path, game_id: str, code: str) -> int:
    """Tìm chỉ số biến thể tiếp theo cho lá `code` (2H, TD, ...).

    Đảm bảo:
    - Không ghi đè file đã tồn tại.
    - Nếu chưa có biến thể nào -> trả về 1.
    """
    code = code.upper()
    tdir = get_templates_dir(base_dir, game_id)
    tdir.mkdir(parents=True, exist_ok=True)

    max_idx = 0
    for name in tdir.glob(f"{code}_*.png"):
        m = CARD_FILENAME_RE.match(name.name)
        if not m:
            continue
        idx = int(m.group(2))
        if idx > max_idx:
            max_idx = idx

    # Ngoài *.png, cho phép cả jpg/jpeg nếu cần
    for ext in ("jpg", "jpeg"):
        for name in tdir.glob(f"{code}_*.{ext}"):
            m = CARD_FILENAME_RE.match(name.name)
            if not m:
                continue
            idx = int(m.group(2))
            if idx > max_idx:
                max_idx = idx

    return max_idx + 1



def list_variants(base_dir: Path, game_id: str) -> Dict[str, List[VariantInfo]]:
    """Liệt kê toàn bộ biến thể + ảnh gốc theo 52 lá.

    Quy ước:
    - Ảnh gốc:    CODE.png (ví dụ "2C.png")      -> variant_index = 0
    - Biến thể:   CODE_n.png (ví dụ "2C_1.png") -> variant_index = n (>=1)

    Trả về dict:
        {
            "2H": [VariantInfo(...), ...],
            "3H": [...],
            ...
        }
    """
    tdir = get_templates_dir(base_dir, game_id)
    result: Dict[str, List[VariantInfo]] = {code: [] for code in CARD_CODES}

    if not tdir.exists():
        return result

    for path in tdir.iterdir():
        if not path.is_file():
            continue

        # Ưu tiên match biến thể CODE_n.*
        m_var = CARD_FILENAME_RE.match(path.name)
        if m_var:
            code = m_var.group(1).upper()
            idx = int(m_var.group(2))
            info = VariantInfo(
                code=code,
                variant_index=idx,
                filename=path.name,
                path=path,
            )
            result.setdefault(code, []).append(info)
            continue

        # Nếu không phải biến thể thì thử match ảnh gốc CODE.*
        m_base = BASE_CARD_RE.match(path.name)
        if m_base:
            code = m_base.group(1).upper()
            info = VariantInfo(
                code=code,
                variant_index=0,
                filename=path.name,
                path=path,
            )
            result.setdefault(code, []).append(info)

    # sort từng list theo variant_index
    for code in result:
        result[code].sort(key=lambda v: v.variant_index)

    return result



def delete_variant(base_dir: Path, game_id: str, code: str, variant_index: int) -> bool:
    """Xoá 1 biến thể hoặc ảnh gốc (nếu tồn tại).

    - variant_index == 0  -> xoá ảnh gốc CODE.(png/jpg/jpeg)
    - variant_index >= 1  -> xoá biến thể CODE_index.(png/jpg/jpeg)
    """
    code = code.upper()
    tdir = get_templates_dir(base_dir, game_id)
    if not tdir.exists():
        return False

    if variant_index == 0:
        # Ảnh gốc: CODE.png / CODE.jpg / CODE.jpeg
        for ext in ("png", "jpg", "jpeg"):
            path = tdir / f"{code}.{ext}"
            if path.exists() and path.is_file():
                path.unlink()
                return True
        return False

    # Biến thể: CODE_index.png / jpg / jpeg
    pattern_prefix = f"{code}_{variant_index}."
    for path in tdir.iterdir():
        if not path.is_file():
            continue
        if path.name.startswith(pattern_prefix):
            path.unlink()
            return True
    return False

