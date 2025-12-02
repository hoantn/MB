from __future__ import annotations

import logging
import socket
from typing import Dict, Tuple

from .profiles_model import ProfileConfig, DEFAULT_WIDTH, DEFAULT_HEIGHT, DEFAULT_START_URL


logger = logging.getLogger(__name__)


class BrowserManager:
    """Quản lý mở/đóng trình duyệt cho từng hồ sơ (profile).

    - Sử dụng undetected-chromedriver (uc) + Selenium.
    - Mỗi profile (P1/P2/P3) có tối đa 1 driver đang mở.
    - Trước khi mở, có thể test proxy (TCP connect tới host:port) nếu đang bật proxy.

    Kích thước & zoom:
    - DEFAULT_WIDTH/HEIGHT = 1280x720 là tỉ lệ gốc.
    - Người dùng chỉnh % trong UI sẽ làm thay đổi *kích thước cửa sổ* vật lý:
        width  = 1280 * (zoom_percent / 100)
        height = 720  * (zoom_percent / 100)
    - Không dùng CSS zoom trong trang, để tránh thay đổi vị trí tương đối của phần tử.
    """

    def __init__(self) -> None:
        self._drivers: Dict[str, "object"] = {}

    @property
    def drivers(self) -> Dict[str, "object"]:
        return self._drivers

    def test_proxy(self, cfg: ProfileConfig, timeout: float = 5.0) -> Tuple[bool, str]:
        """Test proxy bằng cách mở TCP tới host:port.

        Nếu proxy_type = "none" thì không test, trả về thông báo tương ứng.

        Trả về:
            (ok, message)
        """
        proxy_type = (cfg.proxy_type or "none").lower()
        if proxy_type == "none":
            return False, "Đang cấu hình 'Không dùng proxy', không cần test."

        host = (cfg.proxy_host or "").strip()
        port_str = (cfg.proxy_port or "").strip()

        if not host or not port_str:
            return False, "Chưa cấu hình đầy đủ proxy_host + proxy_port."

        try:
            port = int(port_str)
        except ValueError:
            return False, f"proxy_port không hợp lệ: {port_str!r}"

        try:
            with socket.create_connection((host, port), timeout=timeout):
                return True, f"Kết nối TCP tới {host}:{port} thành công."
        except OSError as exc:
            return False, f"Lỗi kết nối tới proxy {host}:{port}: {exc}"

    def open_browser(self, key: str, cfg: ProfileConfig) -> None:
        """Mở trình duyệt cho profile key (P1/P2/P3).

        - Nếu driver đã tồn tại, sẽ bỏ qua (hoặc có thể đóng rồi mở lại tuỳ nhu cầu).
        - Kích thước cửa sổ được tính theo tỉ lệ từ 1280x720 * (zoom_percent / 100).
        - Proxy chỉ gắn khi proxy_type != "none".
        - Sau khi mở, điều hướng tới start_url (hoặc DEFAULT_START_URL nếu trống).
        """
        if key in self._drivers and self._drivers[key] is not None:
            logger.info("Browser[%s] đã mở, bỏ qua yêu cầu mở lại.", key)
            return

        try:
            import undetected_chromedriver as uc  # type: ignore
        except Exception as exc:
            logger.error("Không import được undetected-chromedriver: %s", exc)
            raise RuntimeError(
                "Thiếu package undetected-chromedriver. "
                "Hãy cài bằng: pip install undetected-chromedriver"
            ) from exc

        options = uc.ChromeOptions()

        profile_path = (cfg.chrome_profile_path or "").strip()
        if profile_path:
            options.add_argument(f"--user-data-dir={profile_path}")

        proxy_type = (cfg.proxy_type or "none").lower()
        host = (cfg.proxy_host or "").strip()
        port = (cfg.proxy_port or "").strip()
        username = (cfg.proxy_username or "").strip()
        password = (cfg.proxy_password or "").strip()

        if proxy_type != "none" and host and port:
            # Chrome chấp nhận dạng chung scheme://[user:pass@]host:port
            if proxy_type == "http":
                scheme = "http"
            elif proxy_type == "socks5":
                scheme = "socks5"
            else:
                scheme = ""  # fallback, vẫn để Chrome tự hiểu

            auth_prefix = ""
            if username and password:
                auth_prefix = f"{username}:{password}@"
            if scheme:
                proxy_arg = f"{scheme}://{auth_prefix}{host}:{port}"
            else:
                proxy_arg = f"{auth_prefix}{host}:{port}"

            options.add_argument(f"--proxy-server={proxy_arg}")
            logger.info("Đã gắn proxy %s cho profile %s", proxy_arg, key)

        try:
            driver = uc.Chrome(options=options)
        except Exception as exc:
            logger.error("Lỗi khởi tạo Chrome driver cho %s: %s", key, exc)
            raise

        # Tính toán kích thước cửa sổ theo %
        try:
            zoom_percent = int(cfg.zoom_percent or 100)
        except Exception:
            zoom_percent = 100
        zoom_percent = max(50, min(200, zoom_percent))

        width = int(DEFAULT_WIDTH * zoom_percent / 100)
        height = int(DEFAULT_HEIGHT * zoom_percent / 100)

        try:
            driver.set_window_position(0, 0)
        except Exception as exc:
            logger.warning("Không set được vị trí cửa sổ: %s", exc)

        try:
            driver.set_window_size(width, height)
            logger.info(
                "Đã set kích thước cửa sổ cho %s: %sx%s (từ base %sx%s, zoom=%s%%)",
                key,
                width,
                height,
                DEFAULT_WIDTH,
                DEFAULT_HEIGHT,
                zoom_percent,
            )
        except Exception as exc:
            logger.warning("Không set được window size %sx%s: %s", width, height, exc)

        # Điều hướng tới start_url (hoặc mặc định)
        start_url = (cfg.start_url or "").strip() or DEFAULT_START_URL
        try:
            driver.get(start_url)
        except Exception as exc:
            logger.warning("Không mở được start_url %s cho profile %s: %s", start_url, key, exc)

        self._drivers[key] = driver

    def close_browser(self, key: str) -> None:
        drv = self._drivers.get(key)
        if drv is None:
            return
        try:
            drv.quit()
        except Exception as exc:
            logger.warning("Lỗi khi quit driver[%s]: %s", key, exc)
        finally:
            self._drivers[key] = None

    def close_all(self) -> None:
        for key in list(self._drivers.keys()):
            self.close_browser(key)
