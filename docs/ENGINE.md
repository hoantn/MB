# Kendz Engine – Phase 4 (Skeleton)

Mục tiêu:
- Có Mậu Binh Engine cơ bản để:
  + Xếp được 13 lá thành 3 chi.
  + Chạy test offline (không cần Vision/Automation).
  + Log ra dạng dễ đọc để phân tích.
- Chưa cố gắng đạt tối ưu tuyệt đối, tập trung vào kiến trúc sạch.

## 1. cards.py

- `Card`: rank + suit, có `rank_value`.
- `parse_card(code)`: "AS" -> Card('A','S').
- `parse_cards_list(text)`: "AS,KH,7D,..." -> list Card.
- `format_cards(cards)`: list Card -> chuỗi.
- `full_deck()`: sinh 52 lá.

## 2. hand_types.py

- `PokerHandType`: enum loại bài 5 lá (HIGH_CARD -> STRAIGHT_FLUSH).
- `Chi5`: chứa 5 lá, `hand_type`, `strength_key`.
- `Chi3`: chứa 3 lá, `strength_key`.
- `ArrangedHand`:
  - chi1 (Chi3), chi2 (Chi5), chi3 (Chi5).
  - is_lung: True/False.
  - notes: ghi chú (vd: "arrange_basic...").
  - `to_str()`: chuỗi mô tả.

## 3. evaluator.py

- `evaluate_poker5(cards)`:
  - Trả về `(hand_type, strength_key)`.
  - Dựa trên luật poker cơ bản.
- `compare_poker5(a, b)`:
  - So sánh 2 hand đã evaluate.
- `evaluate_chi3(cards)`:
  - Trả về strength_key đơn giản dựa trên rank.
- `compare_chi3(key_a, key_b)`:
  - So sánh 2 chi3.

## 4. arranger.py

- `arrange_basic(cards)`:
  - Giả định `cards` có 13 lá.
  - Sắp xếp rank giảm dần.
  - Chia:
    - chi3: 5 lá mạnh nhất (dưới).
    - chi2: 5 lá tiếp theo (giữa).
    - chi1: 3 lá yếu nhất (trên).
  - Đánh giá chi2, chi3 bằng `evaluate_poker5`.
  - Đánh dấu `is_lung` nếu chi3 < chi2 theo poker5.
  - Ghi chú trong `notes`.

Đây chỉ là chiến lược rất cơ bản, dùng để:
- Đảm bảo engine chạy được.
- Kiểm tra log và pipeline.
- Từ đây dễ dàng gắn thêm chiến lược nâng cao mà không phá kiến trúc.

## 5. service.py

- `test_engine_random(ctx)`:
  - Sinh `full_deck()`, xáo bài.
  - Lấy 13 lá đầu, xếp bằng `arrange_basic`.
  - Ghi log:
    - 13 lá ban đầu.
    - Kết quả xếp (`ArrangedHand.to_str()`).

Hàm này đang được gọi từ `main.py` để mọi lần chạy Kendz đều có một test engine đơn giản.


## 6. Chiến lược nâng cao: arrange_advanced

- File: `kendz/engine/arranger.py`
- Hàm: `arrange_advanced(cards, max_top_chi1=30)`

Ý tưởng chính:
- Duyệt tất cả tổ hợp chi1 (3 lá) từ 13 lá -> 286 tổ hợp.
- Chấm điểm chi1, giữ lại `max_top_chi1` tổ hợp mạnh nhất.
- Với mỗi chi1 ứng viên:
  + Duyệt tất cả tổ hợp chi2 (5 lá) trong 10 lá còn lại.
  + Chi3 = 5 lá còn lại.
  + Bỏ qua nếu chi3 < chi2 (lủng).
  + Chấm điểm tổng (chi1, chi2, chi3) với trọng số ưu tiên chi3 > chi2 > chi1.
- Chọn arrangement có tổng điểm cao nhất.

Hàm này là heuristic:
- Mạnh hơn `arrange_basic`.
- Vẫn đủ nhanh vì chỉ duyệt một phần không gian trạng thái (top chi1).
- Dễ mở rộng về sau (thay hàm scoring, thêm rule Mậu Binh chi tiết...).


## 7. Bài đặc biệt 13 lá (special_rules.py)

File: `kendz/engine/special_rules.py`

Hiện hỗ trợ nhận diện các loại bài đặc biệt sau:
- `SẢNH RỒNG`: 13 lá liên tiếp từ 2 -> A (mỗi rank đúng 1 lá).
- `6 ĐÔI`: 6 đôi + 1 lá lẻ.
- `5 ĐÔI 1 SÁM`: 5 đôi + 1 bộ 3.
- `CÙNG MÀU ĐỎ` / `CÙNG MÀU ĐEN`: 13 lá cùng màu (H/D hoặc S/C).

Hàm:
- `detect_special_13(cards) -> (special_name, meta)`:
  + `special_name`: tên bài đặc biệt hoặc `None` nếu không phải.
  + `meta`: thông tin phụ (hiện tại để trống, dùng cho mở rộng sau).

Khi `arrange_advanced()` gặp bài đặc biệt:
- Không chạy heuristic search nữa.
- Gọi `arrange_basic()` để chia chi tạm thời.
- Đánh dấu:
  + `ArrangedHand.special_type = special_name`
  + `ArrangedHand.is_lung = False`
  + `ArrangedHand.notes` mô tả rõ đây là bài đặc biệt.
