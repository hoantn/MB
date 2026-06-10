from typing import Dict, List, Optional
from PIL import Image
from capture.region import get_slots
from core.logger import log

def crop_slots(profile_id: str, img: Image.Image, slot: int = 1) -> List[Optional[Image.Image]]:
    slots_cfg = get_slots(profile_id, slot=slot)
    result: List[Optional[Image.Image]] = []
    for i in range(1, 14):
        key = str(i)
        slot = slots_cfg.get(key)
        if not slot:
            result.append(None)
            continue
        x = slot.get("x", 0)
        y = slot.get("y", 0)
        w = slot.get("width", 50)
        h = slot.get("height", 70)
        try:
            crop = img.crop((x, y, x + w, y + h))
            result.append(crop)
        except Exception as e:
            log.error("Failed to crop slot %s: %s", key, e)
            result.append(None)
    return result
