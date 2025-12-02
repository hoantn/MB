

## 3.7. Auto template layout (Phase 7)

- Module: `kendz.tools.auto_template_layout`
- Sử dụng template mặt lưng `data/templates/mau_binh_siteA/back.png` để dò tất cả lá bài úp.
- Các bước:
  1. Template matching đa scale để tìm toạ độ lá bài úp trên toàn khung hình.
  2. Non-maximum suppression để giữ một bounding box cho mỗi lá.
  3. Lọc cluster có toạ độ Y lớn nhất (người chơi phía dưới).
  4. Gom thành 3 hàng (3+5+5) theo Y, sort từng hàng theo X.
  5. Ghi layout 13 lá vào `config/layouts_mau_binh.yaml`.
  6. Lưu ảnh debug `data/vision_layout_debug.png` với khung và index 1..13.


## 3.7. Auto template layout (Phase 7.1 - multi template)

- Module: `kendz.tools.auto_template_layout`
- Dùng 2 template:
  + `data/templates/mau_binh_siteA/back_full.png`
  + `data/templates/mau_binh_siteA/back_cut.png`
- Quy trình:
  1. Template matching đa scale cho từng template, merge kết quả.
  2. NMS để loại trùng, giữ 1 bounding box / lá.
  3. Chọn cluster có Y lớn nhất làm cụm người chơi.
  4. Gom thành 3 hàng (3+5+5) theo Y, sort từng hàng theo X.
  5. Ghi layout 13 lá vào `config/layouts_mau_binh.yaml`.
  6. Lưu ảnh debug `data/vision_layout_debug.png`.


## 3.8. Manual layout calibrate (Phase 8)

- Module: `kendz.tools.layout_calibrate_manual`
- Mục đích: Xác định toạ độ 13 lá bài NGỬA của người chơi bằng tay, 1 lần cho mỗi cấu hình game.
- Cách hoạt động:
  1. Chụp full screen hiện tại bằng `capture_screen`.
  2. Mở cửa sổ OpenCV, cho phép user vẽ lần lượt các rect bao quanh 13 lá bài:
     - Chuột trái: click & drag để tạo rect.
     - Chuột phải: undo rect cuối.
     - ENTER/SPACE: lưu khi đủ rect.
     - ESC/q: thoát không lưu.
  3. Convert (x, y, w, h) sang toạ độ tương đối 0..1.
  4. Ghi vào `config/layouts_mau_binh.yaml` theo `game_id` và `profile_id`.
- Sau khi calibrate xong, Vision pipeline sẽ dùng layout này để crop 13 lá NGỬA ổn định, không phụ thuộc template mặt lưng.


## 4. Card Recognizer (Phase 9)

- Module core: `kendz.vision.card_recognizer.CardRecognizer`
- Template lưu tại: `data/card_templates/<game_id>/` theo mã 2C..AS (PNG).
- Tool label:
  - `python -m kendz.tools.card_template_labeler`
  - Lấy ảnh từ `data/vision_cards/<game_id>/profile_1/card_*.png`, hiển thị từng lá
    và yêu cầu user nhập mã (vd: 3S, TD, AH).
  - Lưu template vào `data/card_templates/<game_id>/<code>.png`.
- Tool test:
  - `python -m kendz.tools.test_recognizer_from_crops`
  - Đọc toàn bộ `card_*.png` trong folder crop, chạy recognizer và in kết quả.
  - Sinh ảnh debug `data/vision_recognizer_debug.png` với mã trên mỗi lá.
- Mục tiêu:
  - Có thể build dần bộ template 52 lá trực tiếp từ GO88.
  - Đảm bảo pipeline Vision (crop 13 lá) -> Recognizer -> Engine hoạt động ổn định.
