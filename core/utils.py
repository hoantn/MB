from typing import Tuple
from PIL import Image
import imagehash

def compute_phash(img: Image.Image) -> str:
    """Tính perceptual hash cho 1 ảnh."""
    return str(imagehash.phash(img.convert("RGB")))

def compare_phash(h1: str, h2: str) -> float:
    """So sánh 2 phash, trả về % giống nhau (0..100)."""
    if len(h1) != len(h2):
        return 0.0
    dist = sum(c1 != c2 for c1, c2 in zip(h1, h2))
    max_bits = len(h1) * 4  # 16 hex * 4 bits
    similarity = 1.0 - (dist / max_bits)
    return similarity * 100.0

def normalize_card_code(code: str) -> str:
    """Chuẩn hóa mã lá bài về dạng [RANK][SUIT]."""
    code = code.strip().upper()
    if len(code) == 2:
        return code
    return code

def split_card_code(code: str) -> Tuple[str, str]:
    code = normalize_card_code(code)
    if len(code) < 2:
        return code, ""
    rank = code[0]
    suit = code[1]
    return rank, suit
