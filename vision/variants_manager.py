import os
from dataclasses import dataclass
from typing import List

from PIL import Image

from core.constants import TEMPLATES_DIR
from core.logger import log
from core.utils import compute_phash  # vẫn dùng để đếm, sau này muốn bật chống trùng thì còn


@dataclass
class VariantInfo:
    path: str
    phash: str


def _variant_folder(card_code: str) -> str:
    """
    Trả về thư mục chứa variants cho 1 lá bài.
    Vẫn giữ cấu trúc cũ: TEMPLATES_DIR/<card_code>/
    """
    folder = os.path.join(TEMPLATES_DIR, card_code)
    os.makedirs(folder, exist_ok=True)
    return folder


def _load_variants(card_code: str) -> List[VariantInfo]:
    """
    Load danh sách variant hiện có, chủ yếu để biết đang có bao nhiêu file
    (phục vụ đặt tên card_code_XXX.png).
    """
    folder = _variant_folder(card_code)
    variants: List[VariantInfo] = []
    if not os.path.isdir(folder):
        return variants

    for fname in os.listdir(folder):
        if not fname.lower().endswith((".png", ".jpg", ".jpeg")):
            continue
        path = os.path.join(folder, fname)
        try:
            img = Image.open(path)
            ph = compute_phash(img)
            variants.append(VariantInfo(path=path, phash=ph))
        except Exception as e:
            log.error("Failed to load variant %s: %s", path, e)
    return variants


def add_variant(card_code: str, img: Image.Image, min_diff_percent: float = 95.0) -> bool:
    """
    Thêm 1 variant cho lá bài `card_code`.

    - ĐÃ TẮT HOÀN TOÀN CHỐNG TRÙNG:
        Không còn so sánh pHash & không chặn ảnh "giống".
    - Sau khi lưu xong, tự động gọi recognizer.reload_templates()
        để bộ nhận diện dùng ngay templates mới.

    Trả về:
        True nếu lưu thành công, False nếu có lỗi IO.
    """
    folder = _variant_folder(card_code)

    # Chỉ dùng danh sách cũ để đánh số file (XXX)
    existing = _load_variants(card_code)
    idx = len(existing) + 1
    fname = f"{card_code}_{idx:03d}.png"
    path = os.path.join(folder, fname)

    try:
        img.save(path)
        log.info("Added variant for %s: %s (duplicate check disabled)", card_code, path)
    except Exception as e:
        log.error("Failed to save variant for %s: %s", card_code, e)
        return False

    # HOT RELOAD: xóa cache template của recognizer để lần scan tiếp theo dùng bộ mới
    try:
        from vision import recognizer  # import lazy để tránh vòng lặp import
        if hasattr(recognizer, "reload_templates"):
            recognizer.reload_templates()
            log.info("Recognizer templates reloaded after adding variant for %s", card_code)
        else:
            log.warning("recognizer.reload_templates() not found; templates will update only after restart.")
    except Exception as e:
        log.error("Could not reload recognizer templates after adding variant: %s", e)

    return True
