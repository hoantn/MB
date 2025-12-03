from typing import List, Tuple
from collections import defaultdict

from core.logger import log
from core.config import load_config
from capture.region import get_game_region, get_slots
from browser.manager import BrowserManager
from engine.card import Card


def card_to_code(c: Card) -> str:
    """
    Chuyển Card → code (VD: 'AR', '9C').
    Cố gắng dùng c.code, fallback sang (rank+suit).
    """
    if hasattr(c, "code"):
        return getattr(c, "code")
    if hasattr(c, "rank") and hasattr(c, "suit"):
        return f"{c.rank}{c.suit}"
    # last resort: str(c)
    return str(c)


def compute_target_codes(chi1: List[Card], chi2: List[Card], chi3: List[Card]) -> List[str]:
    """
    Gộp 3 chi thành list 13 lá theo layout thực tế trên bàn Mậu Binh:

      Hàng 1 (trên cùng):   3 lá  -> vị trí 1,2,3
      Hàng 2 (giữa):        5 lá  -> vị trí 4,5,6,7,8
      Hàng 3 (dưới):        5 lá  -> vị trí 9,10,11,12,13

    => layout chuẩn: 3 + 5 + 5, đi từ TRÊN xuống DƯỚI, từ TRÁI sang PHẢI.

    Tuỳ engine arrange_13_cards trả về (chi1, chi2, chi3) dạng 3-5-5 hay 5-5-3,
    ta tự phát hiện chiều dài để map cho đúng bàn.
    """
    len1, len2, len3 = len(chi1), len(chi2), len(chi3)

    if (len1, len2, len3) == (3, 5, 5):
        # Engine đã trả đúng thứ tự: chi1 (3), chi2 (5), chi3 (5)
        ordered_cards = list(chi1) + list(chi2) + list(chi3)
    elif (len1, len2, len3) == (5, 5, 3):
        # Engine dùng dạng chi1 (5), chi2 (5), chi3 (3)
        # Bàn thực tế: TOP = chi3 (3), MIDDLE = chi2 (5), BOTTOM = chi1 (5)
        ordered_cards = list(chi3) + list(chi2) + list(chi1)
    else:
        # Fallback: cứ nối thẳng, để còn debug nếu có cấu trúc lạ
        ordered_cards = list(chi1) + list(chi2) + list(chi3)

    return [card_to_code(c) for c in ordered_cards]


def compute_moves(current_codes: List[str], target_codes: List[str]) -> List[Tuple[int, int]]:
    """
    Tính danh sách (src_idx, dst_idx) để biến current → target.
    Thuật toán đơn giản: quét từ trái sang phải, swap từng lá cho đúng vị trí.
    """
    moves: List[Tuple[int, int]] = []
    cur = list(current_codes)  # copy

    for j in range(len(target_codes)):
        desired = target_codes[j]
        if j < len(cur) and cur[j] == desired:
            continue
        # tìm phía sau 1 lá có code = desired
        k = None
        for idx in range(j + 1, len(cur)):
            if cur[idx] == desired:
                k = idx
                break
        if k is None:
            # không tìm được (VD: nhận dạng sai, thiếu lá) → bỏ qua
            log.warning("Không tìm thấy lá %s trong current_codes, bỏ qua vị trí %d", desired, j)
            continue

        moves.append((k, j))
        # update local order cho các bước sau
        cur[j], cur[k] = cur[k], cur[j]

    return moves


def apply_arrangement(
    profile_id: str,
    browser_manager: BrowserManager,
    current_codes: List[str],
    chi1: List[Card],
    chi2: List[Card],
    chi3: List[Card],
):
    """
    Tự động kéo bài trên trình duyệt theo 3 chi đã sắp.
    - current_codes: list code đang có trên Dashboard cho profile tương ứng (13 phần tử).
    - chi1, chi2, chi3: danh sách Card engine trả về.
    """

    # 1) Kiểm tra tab / devtools
    tab = browser_manager.get_active_tab(profile_id)
    if not tab or not hasattr(tab, "devtools"):
        log.warning("apply_arrangement: không tìm thấy tab active cho %s", profile_id)
        return
    devtools = tab.devtools

    # 2) Lấy game_region + slots từ config
    cfg = load_config()
    game_region = get_game_region(profile_id)
    slots = get_slots(profile_id)

    if not game_region:
        log.warning("apply_arrangement: chưa có game_region cho %s", profile_id)
        return
    if not slots or len(slots) < 13:
        log.warning("apply_arrangement: slots cho %s chưa đủ 13 slot", profile_id)
        return

    # 3) Tính target_codes và danh sách (src,dst)
    target_codes = compute_target_codes(chi1, chi2, chi3)
    if len(current_codes) != 13 or len(target_codes) != 13:
        log.warning("apply_arrangement: current/target không đủ 13 lá (current=%d, target=%d)",
                    len(current_codes), len(target_codes))
        return

    moves = compute_moves(current_codes, target_codes)
    if not moves:
        log.info("apply_arrangement: không có move nào (có thể đã đúng thứ tự).")
        return

    # 4) Tính toạ độ trung tâm slot (ABS trên page)
    slot_centers = {}
    for i in range(1, 14):
        key = str(i)
        rect = slots.get(key)
        if not rect:
            continue
        cx = game_region["x"] + rect["x"] + rect["width"] / 2.0
        cy = game_region["y"] + rect["y"] + rect["height"] / 2.0
        slot_centers[i] = (cx, cy)

    # 5) Thực hiện kéo cho từng move
    log.info("apply_arrangement[%s]: moves=%s", profile_id, moves)

    # bản code local để update thứ tự khi kéo (để tránh kéo chồng chéo sau này nếu cần)
    local_codes = list(current_codes)

    for src_idx, dst_idx in moves:
        # slot index tính từ 1..13
        s_slot = src_idx + 1
        d_slot = dst_idx + 1

        if s_slot not in slot_centers or d_slot not in slot_centers:
            log.warning("apply_arrangement: thiếu center cho slot %d hoặc %d", s_slot, d_slot)
            continue

        sx, sy = slot_centers[s_slot]
        dx, dy = slot_centers[d_slot]

        log.info("apply_arrangement[%s]: drag slot %d -> slot %d (%s -> %s)",
                 profile_id, s_slot, d_slot,
                 local_codes[src_idx] if src_idx < len(local_codes) else "?",
                 target_codes[dst_idx])

        try:
            devtools.mouse_drag(sx, sy, dx, dy)
            time.sleep(0.05)  # cho game update
        except Exception as e:
            log.error("apply_arrangement: lỗi drag %s", e)

        # update local order
        if 0 <= src_idx < len(local_codes) and 0 <= dst_idx < len(local_codes):
            local_codes[dst_idx], local_codes[src_idx] = local_codes[src_idx], local_codes[dst_idx]
