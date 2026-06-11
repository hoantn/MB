from __future__ import annotations

from typing import Any, Dict, Optional, Tuple


def read_live_runtime_info(browser_manager: Any, profile_id: str) -> Optional[Dict[str, Any]]:
    """Read the current viewport/canvas for fixed runtime coordinates."""
    if browser_manager is None or not hasattr(browser_manager, "ensure_tab"):
        return None
    tab = browser_manager.ensure_tab(profile_id)
    if tab is None or getattr(tab, "devtools", None) is None:
        return None
    view = tab.devtools.get_cocos_view_info()
    if not isinstance(view, dict):
        return None
    frame = view.get("frame") or {}
    canvas = view.get("canvas") or {}
    design = view.get("design") or {}
    if not frame or not canvas:
        return None
    return {
        "mode": "runtime_fixed",
        "viewport": {
            "width": round(float(frame.get("width", 0))),
            "height": round(float(frame.get("height", 0))),
        },
        "canvas": {
            "left": round(float(canvas.get("left", 0))),
            "top": round(float(canvas.get("top", 0))),
            "width": round(float(canvas.get("width", 0))),
            "height": round(float(canvas.get("height", 0))),
        },
        "design": {
            "width": round(float(design.get("width", 0))) if design else 0,
            "height": round(float(design.get("height", 0))) if design else 0,
        },
    }


def stamp_runtime_info(
    cfg: Dict[str, Any],
    profile_id: str,
    info: Dict[str, Any],
    scope: str | None = None,
) -> None:
    cap = cfg.setdefault("capture", {})
    runtime = cap.setdefault("runtime", {})
    runtime[profile_id] = dict(info)
    if scope:
        scopes = cap.setdefault("runtime_scopes", {})
        profile_scopes = scopes.setdefault(profile_id, {})
        profile_scopes[str(scope)] = dict(info)


def get_saved_runtime_info(
    cfg: Dict[str, Any],
    profile_id: str,
    scope: str | None = None,
) -> Optional[Dict[str, Any]]:
    if scope:
        info = (((cfg.get("capture") or {}).get("runtime_scopes") or {}).get(profile_id) or {}).get(scope)
        return info if isinstance(info, dict) else None
    info = ((cfg.get("capture") or {}).get("runtime") or {}).get(profile_id)
    return info if isinstance(info, dict) else None


def _section_mismatch(
    saved: Dict[str, Any],
    live: Dict[str, Any],
    section: str,
    keys: Tuple[str, ...],
    tolerance: int,
) -> list[str]:
    out: list[str] = []
    s = saved.get(section) or {}
    l = live.get(section) or {}
    for key in keys:
        try:
            sv = int(round(float(s.get(key, 0))))
            lv = int(round(float(l.get(key, 0))))
        except Exception:
            out.append(f"{section}.{key}: saved={s.get(key)} live={l.get(key)}")
            continue
        if abs(sv - lv) > tolerance:
            out.append(f"{section}.{key}: saved={sv} live={lv}")
    return out


def compare_runtime_info(
    saved: Dict[str, Any],
    live: Dict[str, Any],
    tolerance: int = 2,
) -> Tuple[bool, str]:
    mismatches: list[str] = []
    mismatches.extend(_section_mismatch(saved, live, "viewport", ("width", "height"), tolerance))
    mismatches.extend(_section_mismatch(saved, live, "canvas", ("left", "top", "width", "height"), tolerance))
    if mismatches:
        return False, "; ".join(mismatches)
    return True, ""


def validate_runtime_coordinates(
    browser_manager: Any,
    profile_id: str,
    cfg: Dict[str, Any],
    tolerance: int = 2,
    scope: str | None = None,
) -> Tuple[bool, str]:
    """Validate the live viewport/canvas against the coordinates saved by Fix tọa độ."""
    saved = get_saved_runtime_info(cfg, profile_id, scope=scope)
    if not saved:
        if scope:
            return False, f"chua co runtime metadata cho {scope}, hay vao tab Fix toa do va luu lai nhom toa do nay"
        return False, "chua co runtime metadata, hay vao tab Fix toa do va luu lai toa do cho profile nay"
    live = read_live_runtime_info(browser_manager, profile_id)
    if not live:
        return False, "khong doc duoc viewport/canvas hien tai"
    ok, detail = compare_runtime_info(saved, live, tolerance=tolerance)
    if ok:
        return True, "runtime matched"
    return False, detail
