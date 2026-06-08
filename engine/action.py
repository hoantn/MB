from typing import List, Tuple

from core.logger import log
from core.config import load_config
from core.apply_trace import apply_trace
from capture.region import get_game_region, get_slots
from browser.manager import BrowserManager
from engine.card import Card
import time
import os
from datetime import datetime

from PIL import ImageDraw

# Debug flags cho arrange:
# - DEBUG_ARRANGE_VISUAL: lưu ảnh debug slots + đường kéo
# - DEBUG_ARRANGE_DRY_RUN: chỉ vẽ/log, không gửi chuột thật
DEBUG_ARRANGE_VISUAL = False
DEBUG_ARRANGE_DRY_RUN = False


def compute_drag_settle_s(
    configured_sleep_s: float,
    current_move: Tuple[int, int],
    previous_move: Tuple[int, int] | None,
) -> Tuple[float, bool]:
    """Delay sleep theo cấu hình; touches_previous chỉ dùng để log/debug."""
    touches_previous = bool(
        previous_move is not None
        and set(current_move).intersection(previous_move)
    )
    # Delay giữa các lần kéo phải đi đúng theo cấu hình UI, không ép thêm
    # ngưỡng ẩn để người dùng kiểm soát tốc độ apply/repair nhất quán.
    return max(0.0, float(configured_sleep_s)), touches_previous


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


def normalize_cards_for_view(cards: List[Card]) -> List[Card]:
    """Chuẩn hoá thứ tự lá trong 1 chi để dễ nhìn (thấp -> cao).

    - Không thay đổi logic hạng bài (đã được engine quyết định).
    - Chỉ sắp xếp lại thứ tự trong *cùng một chi* để UI/Apply đồng nhất.
    - Xử lý riêng sảnh A2345: hiển thị A-2-3-4-5 (A là thấp).
    """
    if not cards:
        return []

    # Sảnh wheel A2345: dùng A như thấp nhất
    ranks = [c.rank for c in cards]
    if len(cards) == 5 and set(ranks) == {"A", "2", "3", "4", "5"}:
        wheel_order = {"A": 0, "2": 1, "3": 2, "4": 3, "5": 4}
        return sorted(cards, key=lambda c: (wheel_order.get(c.rank, 99), c.suit))

    # Mặc định: sort theo rank tăng dần, ổn định theo suit
    return sorted(cards, key=lambda c: (c.rank_index, c.suit))


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
    chi1 = normalize_cards_for_view(list(chi1))
    chi2 = normalize_cards_for_view(list(chi2))
    chi3 = normalize_cards_for_view(list(chi3))

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
    Tính danh sách (src_idx, dst_idx) để biến current → target theo nguyên tắc:

    - Trong mỗi CHI chỉ cần chứa đúng BỘ LÁ đã được engine quyết định.
      Thứ tự trong chi KHÔNG quan trọng.
    - Chỉ kéo khi lá đang ở SAI CHI.
    - Không đổi chỗ các lá trong cùng một chi nếu chúng đều thuộc chi đó.

    Cách làm:
    - Xác định chi mong muốn (0/1/2) cho từng lá từ target_codes.
    - Xác định chi hiện tại cho từng lá từ current_codes.
    - Duyệt từ trái sang phải:
        + Lá nào đang ở đúng chi thì bỏ qua.
        + Lá nào sai chi thì tìm 1 vị trí trong chi đích để swap (với 1 lá cũng sai chi).
    - Nếu gặp case bất thường, fallback về thuật toán swap cũ (exact) để an toàn.
    """

    from collections import Counter
    from typing import Dict

    def _index_to_chi(idx: int) -> int:
        """
        Map index 0..12 -> chi:
        - 0..2   : chi trên (TOP)
        - 3..7   : chi giữa (MIDDLE)
        - 8..12  : chi dưới (BOTTOM)
        """
        if 0 <= idx <= 2:
            return 0
        if 3 <= idx <= 7:
            return 1
        if 8 <= idx <= 12:
            return 2
        return -1

    def _compute_moves_exact(cur_codes: List[str], tgt_codes: List[str]) -> List[Tuple[int, int]]:
        """
        Thuật toán swap CŨ:
        - Quét từ trái sang phải, swap từng lá cho đúng vị trí.
        - GIỮ NGUYÊN behavior cũ để tránh side-effect.
        """
        moves: List[Tuple[int, int]] = []
        cur = list(cur_codes)

        for j in range(len(tgt_codes)):
            desired = tgt_codes[j]
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

    n_cur = len(current_codes)
    n_tgt = len(target_codes)

    # Chỉ tối ưu khi đủ 13 lá, còn lại fallback về thuật toán cũ cho an toàn
    if n_cur != 13 or n_tgt != 13:
        log.warning(
            "compute_moves: kích thước current=%d, target=%d không phải 13 -> dùng thuật toán exact",
            n_cur,
            n_tgt,
        )
        return _compute_moves_exact(current_codes, target_codes)

    # Sanity check: tập lá phải giống nhau, nếu không thì cũng nên fallback
    if Counter(current_codes) != Counter(target_codes):
        log.warning(
            "compute_moves: tập lá current và target khác nhau (current=%s, target=%s) -> dùng thuật toán exact",
            current_codes,
            target_codes,
        )
        return _compute_moves_exact(current_codes, target_codes)

    # 1) Map mỗi lá -> CHI MONG MUỐN (theo target_codes)
    desired_chi: Dict[str, int] = {}
    for idx, code in enumerate(target_codes):
        desired_chi[code] = _index_to_chi(idx)

    # 2) Bắt đầu từ current_codes
    cur = list(current_codes)
    moves: List[Tuple[int, int]] = []

    # 3) Giải các chu kỳ sai chi. Mỗi swap luôn đặt ít nhất một lá vào đúng chi,
    # nên thuật toán kết thúc sau tối đa 13 swap và không cần kéo lại lần hai.
    for _ in range(13):
        wrong_indexes = [
            i for i, code in enumerate(cur)
            if desired_chi.get(code, -1) != _index_to_chi(i)
        ]
        if not wrong_indexes:
            return moves

        i = wrong_indexes[0]
        code_i = cur[i]
        chi_cur = _index_to_chi(i)
        chi_des = desired_chi.get(code_i, -1)

        # Ưu tiên swap đối ứng để sửa hai lá cùng lúc. Với chu kỳ ba chi,
        # lấy một lá sai trong chi đích rồi tiếp tục khép chu kỳ ở vòng sau.
        candidates = [j for j in wrong_indexes if _index_to_chi(j) == chi_des]
        reciprocal = [
            j for j in candidates
            if desired_chi.get(cur[j], -1) == chi_cur
        ]
        j_candidate = reciprocal[0] if reciprocal else (candidates[0] if candidates else None)
        if j_candidate is None:
            log.error(
                "compute_moves: trạng thái phân nhóm không hợp lệ cho lá %s tại slot %d",
                code_i,
                i,
            )
            return _compute_moves_exact(current_codes, target_codes)

        moves.append((i, j_candidate))
        cur[i], cur[j_candidate] = cur[j_candidate], cur[i]

    log.error("compute_moves: vượt giới hạn giải chu kỳ, fallback exact")
    return _compute_moves_exact(current_codes, target_codes)

def _save_arrange_debug_image(
    profile_id: str,
    devtools,
    game_region: dict,
    slots: dict,
    slot_centers: dict,
    moves: List[Tuple[int, int]],
) -> None:
    """Chụp screenshot vùng game và vẽ:
      - khung 13 slot
      - tâm click mỗi slot
      - mũi tên cho từng move src->dst

    Giúp kiểm tra xem:
      - config slot/game_region có khớp với lá bài thật hay không
      - đường kéo có đi đúng từ lá này tới slot mong muốn hay không
    """
    if not DEBUG_ARRANGE_VISUAL:
        return

    try:
        # Chụp screenshot chỉ vùng game_region
        img = devtools.capture_screenshot(game_region)
        draw = ImageDraw.Draw(img)

        # Vẽ khung slot + tâm slot
        for i in range(1, 14):
            key = str(i)
            rect = slots.get(key)
            if not rect:
                continue

            # toạ độ trong ảnh region (gốc ở game_region.x/y)
            x0 = rect["x"]
            y0 = rect["y"]
            x1 = x0 + rect["width"]
            y1 = y0 + rect["height"]

            # khung slot
            draw.rectangle((x0, y0, x1, y1), outline="red", width=2)

            # tâm slot
            if i in slot_centers:
                cx_abs, cy_abs = slot_centers[i]
                cx = cx_abs - game_region["x"]
                cy = cy_abs - game_region["y"]
                r = 4
                draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill="yellow")
                # đánh số slot
                draw.text((cx + 6, cy + 6), str(i), fill="yellow")

        # Vẽ mũi tên cho từng move
        for idx, (src_idx, dst_idx) in enumerate(moves):
            s_slot = src_idx + 1
            d_slot = dst_idx + 1
            if s_slot not in slot_centers or d_slot not in slot_centers:
                continue

            sx_abs, sy_abs = slot_centers[s_slot]
            dx_abs, dy_abs = slot_centers[d_slot]

            sx = sx_abs - game_region["x"]
            sy = sy_abs - game_region["y"]
            dx = dx_abs - game_region["x"]
            dy = dy_abs - game_region["y"]

            draw.line((sx, sy, dx, dy), fill="cyan", width=2)
            draw.text((dx + 6, dy + 6), f"m{idx + 1}", fill="cyan")

        # Lưu file
        out_dir = os.path.join("logs", "arrange_debug")
        os.makedirs(out_dir, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        out_path = os.path.join(out_dir, f"{profile_id}_arrange_{ts}.png")
        img.save(out_path)
        log.info("apply_arrangement[%s]: saved arrange debug image: %s", profile_id, out_path)
    except Exception as e:
        log.error("apply_arrangement[%s]: error saving arrange debug image: %s", profile_id, e)


def apply_arrangement(
    profile_id: str,
    browser_manager: BrowserManager,
    current_codes: List[str],
    chi1: List[Card],
    chi2: List[Card],
    chi3: List[Card],
    delay_s: float = 0.0,   # mặc định 0, chỉ dùng config
):
    """
    Tự động kéo bài trên trình duyệt theo 3 chi đã sắp.
    - current_codes: list code đang có trên Dashboard cho profile tương ứng (13 phần tử).
    - chi1, chi2, chi3: danh sách Card engine trả về.
    """

    # 1) Kiểm tra tab / devtools
    apply_trace("arrange_enter", profile_id, current_len=len(current_codes or []))
    tab = browser_manager.get_active_tab(profile_id)
    if not tab:
        apply_trace("arrange_no_tab", profile_id)
        log.warning("apply_arrangement: không tìm thấy tab active cho profile %s", profile_id)
        return

    devtools = tab.devtools
    if not devtools:
        apply_trace("arrange_no_devtools", profile_id)
        log.warning("apply_arrangement: tab %s chưa có DevTools client", profile_id)
        return

    # 2) Lấy game_region + slots từ config
    cfg = load_config()
    game_region = get_game_region(profile_id)
    slots = get_slots(profile_id)

    # ---- UI apply: thời gian chờ sau mỗi lần kéo (drag_duration_ms) ----
    ui_cfg = cfg.get("ui") or {}
    ui_apply = ui_cfg.get("apply") or {}
    try:
        # Mặc định 0 nếu không có trong config
        drag_ms = int(ui_apply.get("drag_duration_ms") or 0)
    except Exception:
        drag_ms = 0

    # Đổi sang giây, không ép min 0.1 nữa – hoàn toàn theo config
    drag_duration_s = max(0.0, float(drag_ms) / 1000.0)

    if not game_region:
        apply_trace("arrange_no_region", profile_id)
        log.warning("apply_arrangement: chưa có game_region cho %s", profile_id)
        return
    if not slots or len(slots) < 13:
        apply_trace("arrange_no_slots", profile_id, slots_len=len(slots or {}))
        log.warning("apply_arrangement: slots cho %s chưa đủ 13 slot", profile_id)
        return

    # 3) Tính target_codes và danh sách (src,dst)
    target_codes = compute_target_codes(chi1, chi2, chi3)
    if len(current_codes) != 13 or len(target_codes) != 13:
        apply_trace("arrange_bad_len", profile_id, current_len=len(current_codes), target_len=len(target_codes))
        log.warning(
            "apply_arrangement: current/target không đủ 13 lá (current=%d, target=%d)",
            len(current_codes),
            len(target_codes),
        )
        return

    moves = compute_moves(current_codes, target_codes)
    if not moves:
        apply_trace("arrange_no_moves", profile_id)
        log.info("apply_arrangement: không có move nào (có thể đã đúng thứ tự).")
        # NO-OP là một kết quả thành công: layout đầu vào đã đúng nhóm chi.
        # Trả về đủ 13 lá để tầng trên phân biệt với lỗi kéo thực sự.
        return list(current_codes)

    # 4) Tính toạ độ click kéo bài (ABS trên page)
    # Đọc vị trí click tương đối trong từng slot từ config để dễ tinh chỉnh.
    cfg = load_config()
    ui_cfg = cfg.get("ui") or {}
    click_cfg = ui_cfg.get("apply_click") or {}

    # PX: 0 = mép trái, 1 = mép phải
    # PY: 0 = mép trên, 1 = mép dưới
    CLICK_PX = float(click_cfg.get("slot_click_px", 0.5))
    CLICK_PY = float(click_cfg.get("slot_click_py", 0.6))

    slot_centers = {}
    for i in range(1, 14):
        key = str(i)
        rect = slots.get(key)
        if not rect:
            continue

        cx = game_region["x"] + rect["x"] + rect["width"] * CLICK_PX
        cy = game_region["y"] + rect["y"] + rect["height"] * CLICK_PY

        slot_centers[i] = (cx, cy)

    # 5) Ảnh debug slots + đường kéo (nếu bật)
    _save_arrange_debug_image(profile_id, devtools, game_region, slots, slot_centers, moves)

    # 6) Thực hiện kéo cho từng move
    log.info("apply_arrangement[%s]: moves=%s", profile_id, moves)
    apply_trace("arrange_moves_ready", profile_id, moves_len=len(moves))

    # bản code local để update thứ tự khi kéo
    local_codes = list(current_codes)

    had_error = False

    previous_move: Tuple[int, int] | None = None
    for src_idx, dst_idx in moves:
        # slot index tính từ 1..13
        s_slot = src_idx + 1
        d_slot = dst_idx + 1

        if s_slot not in slot_centers or d_slot not in slot_centers:
            log.warning("apply_arrangement: thiếu center cho slot %d hoặc %d", s_slot, d_slot)
            continue

        sx, sy = slot_centers[s_slot]
        dx, dy = slot_centers[d_slot]

        log.info(
            "apply_arrangement[%s]: drag slot %d -> slot %d (%s -> %s)",
            profile_id,
            s_slot,
            d_slot,
            local_codes[src_idx] if 0 <= src_idx < len(local_codes) else "?",
            target_codes[dst_idx] if 0 <= dst_idx < len(target_codes) else "?",
        )

        # Tổng thời gian chờ sau mỗi drag:
        #   - drag_duration_s: "thời gian game update / animation"
        #   - delay_s: "nghỉ thêm giữa các drag theo config"
        apply_trace("drag_before", profile_id, src=s_slot, dst=d_slot)
        configured_sleep = max(0.0, float(drag_duration_s) + float(delay_s))
        # Game cần thời gian chốt swap/animation trước khi một slot vừa kéo
        # được dùng lại. Chỉ tăng thời gian cho chuỗi phụ thuộc; không tăng CPU
        # và vẫn giữ các swap độc lập ở tốc độ nhanh.
        total_sleep, touches_previous = compute_drag_settle_s(
            configured_sleep,
            (src_idx, dst_idx),
            previous_move,
        )
        apply_trace(
            "drag_settle",
            profile_id,
            src=s_slot,
            dst=d_slot,
            settle_ms=int(total_sleep * 1000),
            dependent=touches_previous,
        )

        if DEBUG_ARRANGE_DRY_RUN:
            # Chỉ log + delay, không kéo chuột thật
            if total_sleep > 0:
                time.sleep(total_sleep)
        else:
            # Mỗi drag được retry tối đa 2 lần nếu DevTools ném exception
            drag_ok = False
            max_attempts = 2

            for attempt in range(1, max_attempts + 1):
                try:
                    devtools.mouse_drag(sx, sy, dx, dy)
                    if total_sleep > 0:
                        time.sleep(total_sleep)
                    drag_ok = True
                    apply_trace("drag_after", profile_id, src=s_slot, dst=d_slot, attempt=attempt)
                    break
                except Exception as e:
                    apply_trace("drag_error", profile_id, src=s_slot, dst=d_slot, attempt=attempt, error=str(e))
                    log.error(
                        "apply_arrangement[%s]: lỗi drag slot %d -> %d (attempt %d/%d): %s",
                        profile_id,
                        s_slot,
                        d_slot,
                        attempt,
                        max_attempts,
                        e,
                    )
                    # nghỉ nhẹ trước khi thử lại
                    time.sleep(0.05)

            if not drag_ok:
                had_error = True
                break  # DỪNG LUÔN – không kéo các move sau

        # update local order CHỈ khi không lỗi
        if not had_error and 0 <= src_idx < len(local_codes) and 0 <= dst_idx < len(local_codes):
            local_codes[dst_idx], local_codes[src_idx] = (
                local_codes[src_idx],
                local_codes[dst_idx],
            )
            previous_move = (src_idx, dst_idx)

    if had_error:
        apply_trace("arrange_failed", profile_id, partial_len=len(local_codes))
        # Các drag trước lỗi đã được DevTools xác nhận. Trả lại layout một phần
        # để retry tiếp tục từ trạng thái gần nhất, không kéo lại từ đầu.
        return local_codes

    apply_trace("arrange_done", profile_id, result_len=len(local_codes))
    return local_codes
