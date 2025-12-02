
# PHASE 9 – Kendz Mậu Binh Assist (Realtime, Multi-Profile)

## Mục tiêu

- Đọc 13 lá bài của chính mình từ màn hình game Mậu Binh.
- Nhận diện 13 lá thành mã 52 lá.
- Gọi Engine để xếp bài tối ưu thành 3 chi.
- Gợi ý realtime, hỗ trợ nhiều profile song song.

## Luồng dữ liệu
- Vision → crop 13 lá theo layout.
- Recognizer → mã hóa 13 lá.
- Engine → sắp bài.
- AssistLoop → realtime cho từng profile.

## Cách chạy
python -m kendz.tools.assist_profile1_loop --profile-id 1
python -m kendz.tools.assist_profile1_loop --profile-id 2
python -m kendz.tools.assist_profile1_loop --profile-id 3
