# Module Hồ sơ & Trình duyệt (P1/P2/P3) cho Mậu Binh

Module này tách riêng logic quản lý **profiles + proxy + trình duyệt** cho 3 hồ sơ: `P1`, `P2`, `P3`.

## Thư mục & file

- `main.py`  
  App demo dùng PyQt5 chỉ để test riêng tab **Hồ sơ**.
- `config/profiles.json`  
  File lưu cấu hình từng hồ sơ (profile path, proxy, kích thước cửa sổ).
- `mb_profiles/profiles_model.py`  
  - `ProfileConfig` – dataclass đại diện cấu hình 1 hồ sơ.  
  - `ProfilesStore` – load/save JSON.
- `mb_profiles/browser_manager.py`  
  - `BrowserManager` – quản lý mở/đóng Chrome cho từng hồ sơ, gắn proxy, resize.
- `mb_profiles/ui_profiles_tab.py`  
  - `ProfilesTab` – QWidget Tab "Hồ sơ" hiển thị trong UI chính.

## Chức năng chính

- Mỗi hồ sơ (P1/P2/P3) có:
  - Đường dẫn `Chrome profile path` riêng.
  - Proxy riêng (host/port, user/pass).
  - Danh sách kích thước cửa sổ mặc định: `1280x720`, `1366x768`, `1600x900`, `1920x1080`.
- Nút **Test proxy**:
  - Mở tạm 1 Chrome ẩn, kiểm tra truy cập `https://api.ipify.org?format=json`.
- Nút **Mở trình duyệt**:
  - Đóng instance cũ của hồ sơ đó (nếu có).
  - Mở Chrome với:
    - `--user-data-dir=<chrome_profile_path>`
    - `--proxy-server=http://host:port` (nếu có proxy).
  - Resize theo cấu hình width/height hiện tại.
- Nút **Áp dụng kích thước**:
  - Chỉ resize window của instance Chrome đã mở cho hồ sơ đó.
- Nút **Lưu cấu hình**:
  - Ghi lại `profiles.json`.

## Hướng dẫn tích hợp vào dự án Mậu Binh hiện tại

1. Copy thư mục:
   - `mb_profiles/`
   - `config/profiles.json` (hoặc merge vào config sẵn có)
2. Trong code UI chính (tab widget), tại tab "Hồ sơ":
   ```python
   from pathlib import Path
   from mb_profiles import ProfilesStore, BrowserManager, ProfilesTab

   base_dir = Path(__file__).resolve().parent
   store = ProfilesStore(base_dir / "config" / "profiles.json")
   browser_manager = BrowserManager()

   profiles_tab = ProfilesTab(store, browser_manager)
   tab_widget.addTab(profiles_tab, "Hồ sơ")
   ```
3. Đảm bảo cài package:
   ```bash
   pip install -r requirements.txt
   ```

## Ghi chú an toàn & kiểm thử

- Kiểm tra từng bước:
  1. Chạy `python main.py` để test standalone tab Hồ sơ.
  2. Chọn thư mục Chrome profile khác nhau cho P1/P2/P3.
  3. Set proxy test cho 1 hồ sơ, thử **Test proxy**.
  4. Mở trình duyệt từng hồ sơ -> kiểm tra đúng profile & proxy.
  5. Thay đổi kích thước từ combobox, bấm **Áp dụng kích thước** -> xem cửa sổ resize đúng.

- Khi tích hợp vào dự án chính:
  - Giữ nguyên cấu trúc module `mb_profiles.*`.
  - Không sửa tay `profiles.json` trong khi app đang chạy nếu không cần thiết; dùng nút **Lưu cấu hình** để đảm bảo nhất quán.
