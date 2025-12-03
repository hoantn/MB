from typing import Optional, Dict
from core.config import load_config, save_config
from core.logger import log

def get_game_region(profile_id: str) -> Optional[Dict[str, int]]:
    cfg = load_config()
    region = cfg.get("capture", {}).get("regions", {}).get(profile_id)
    return region

def set_game_region(profile_id: str, region: Dict[str, int]) -> None:
    cfg = load_config()
    if "capture" not in cfg:
        cfg["capture"] = {"regions": {}, "slots": {}}
    if "regions" not in cfg["capture"]:
        cfg["capture"]["regions"] = {}
    cfg["capture"]["regions"][profile_id] = region
    save_config(cfg)
    log.info("Set game region for %s: %s", profile_id, region)

def get_slots(profile_id: str) -> Dict[str, Dict[str, int]]:
    cfg = load_config()
    return cfg.get("capture", {}).get("slots", {}).get(profile_id, {})

def set_slot(profile_id: str, slot_index: int, rect: Dict[str, int]) -> None:
    cfg = load_config()
    if "capture" not in cfg:
        cfg["capture"] = {"regions": {}, "slots": {}}
    if "slots" not in cfg["capture"]:
        cfg["capture"]["slots"] = {}
    if profile_id not in cfg["capture"]["slots"]:
        cfg["capture"]["slots"][profile_id] = {}
    cfg["capture"]["slots"][profile_id][str(slot_index)] = rect
    save_config(cfg)
    log.info("Set slot %s for %s: %s", slot_index, profile_id, rect)
