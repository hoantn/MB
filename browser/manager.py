import json
from pathlib import Path
import os
import subprocess
import shutil
from typing import Dict, Optional
from .local_proxy import AuthHttpForwardProxy, LOCAL_PROXY_PORTS

from core.config import load_config, save_config
from core.logger import log
from .profile import ProfileConfig
from .devtools import DevToolsClient
from .tab import BrowserTab


PROFILE_PORTS = {
    "P1": 9222,
    "P2": 9223,
    "P3": 9224,
}


def get_default_chrome_path() -> str:
    """Tìm chrome.exe mặc định trên Windows, nếu không thấy thì trả 'chrome'."""
    candidates = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    ]
    for p in candidates:
        if os.path.exists(p):
            return p
    return "chrome"


def get_default_user_data_dir(profile_id: str) -> str:
    base = os.getenv("LOCALAPPDATA") or os.getcwd()
    root = os.path.join(base, "MauBinhTool")
    os.makedirs(root, exist_ok=True)
    return os.path.join(root, f"Profile_{profile_id}")


class BrowserManager:
    """
    QUAN TRỌNG: mọi thao tác với config đều dựa trên file mới nhất trên ổ đĩa
    để không ghi đè mất phần capture.regions / capture.slots đã lưu.
    """

    def __init__(self):
        self.config = load_config()
        self.tabs: Dict[str, BrowserTab] = {}
        self.processes: Dict[str, subprocess.Popen] = {}
        self.local_proxies: dict[str, AuthHttpForwardProxy] = {}

    # luôn load lại config mới nhất trước khi xử lý
    def _load_config_fresh(self) -> dict:
        self.config = load_config()
        return self.config

    def reload_config(self):
        self._load_config_fresh()

    def get_profile_config(self, profile_id: str) -> ProfileConfig:
        """
        Đọc config mới nhất, bổ sung chrome_path + user_data_dir nếu trống,
        sau đó lưu lại nhưng KHÔNG đụng tới các key khác (capture, v.v.).
        """
        cfg = self._load_config_fresh()
        profiles = cfg.get("profiles", {})
        d = profiles.get(profile_id, {})

        if not d.get("chrome_path"):
            d["chrome_path"] = get_default_chrome_path()
        if not d.get("user_data_dir"):
            d["user_data_dir"] = get_default_user_data_dir(profile_id)

        profiles[profile_id] = d
        cfg["profiles"] = profiles
        save_config(cfg)
        self.config = cfg

        return ProfileConfig.from_dict(d)

    def update_profile_config(self, profile_id: str, profile_dict: Dict):
        """
        Cập nhật cấu hình 1 profile nhưng merge trên bản config mới nhất
        để không mất phần capture.regions / slots.
        """
        cfg = self._load_config_fresh()
        profiles = cfg.get("profiles", {})
        profiles[profile_id] = profile_dict
        cfg["profiles"] = profiles
        save_config(cfg)
        self.config = cfg
        log.info("Updated profile config for %s", profile_id)

    def _get_port(self, profile_id: str) -> int:
        return PROFILE_PORTS.get(profile_id, 9222)

    def ensure_tab(self, profile_id: str) -> Optional[BrowserTab]:
        """
        Bảo đảm có DevTools tab cho profile.
        - Nếu đã có tab -> trả về luôn.
        - Nếu chưa có -> tạo DevToolsClient mới và attach.
        """
        tab = self.tabs.get(profile_id)
        if tab:
            return tab

        port = self._get_port(profile_id)
        dt = DevToolsClient(profile_id, port)
        dt.connect()
        tab = BrowserTab(profile_id=profile_id, devtools=dt)
        self.tabs[profile_id] = tab
        return tab

    def _ensure_local_proxy(self, profile_id, proxy_cfg) -> int | None:
        """
        Nếu proxy có username/password -> start 1 local forward proxy cho profile.
        Trả về port local để Chrome trỏ tới.
        (HIỆN CHƯA DÙNG, GIỮ LẠI ĐỂ SAU NÀY NẾU CẦN.)
        """
        if not proxy_cfg or not proxy_cfg.host or not proxy_cfg.username:
            return None

        if profile_id in self.local_proxies:
            # Đã có proxy local
            lp = self.local_proxies[profile_id]
            return lp.listen_port  # type: ignore[attr-defined]

        raw_host = proxy_cfg.host.strip()
        port_val = int(proxy_cfg.port or 0)

        # Tách scheme
        if "://" in raw_host:
            scheme, host_part = raw_host.split("://", 1)
            scheme = scheme.lower()
        else:
            scheme = "http"
            host_part = raw_host

        # Nếu host_part đã chứa :port thì tách, ngược lại dùng port trong config
        if ":" in host_part:
            upstream_host, upstream_port_str = host_part.rsplit(":", 1)
            try:
                upstream_port = int(upstream_port_str)
            except ValueError:
                upstream_port = port_val
        else:
            upstream_host = host_part
            upstream_port = port_val

        if upstream_port <= 0:
            log.error("Proxy[%s]: port upstream không hợp lệ", profile_id)
            return None

        local_port = LOCAL_PROXY_PORTS.get(profile_id, 0)
        if local_port <= 0:
            local_port = 19080

        lp = AuthHttpForwardProxy(
            listen_host="127.0.0.1",
            listen_port=local_port,
            upstream_host=upstream_host,
            upstream_port=upstream_port,
            username=proxy_cfg.username or "",
            password=proxy_cfg.password or "",
        )
        # để BrowserManager có thể truy cập listen_port
        lp.listen_port = local_port  # type: ignore[attr-defined]
        lp.start()
        self.local_proxies[profile_id] = lp

        log.info(
            "Started local auth proxy for %s at 127.0.0.1:%s -> %s:%s",
            profile_id,
            local_port,
            upstream_host,
            upstream_port,
        )
        return local_port

    def _prepare_proxy_extension(self, profile_id: str, proxy) -> Optional[str]:
        """
        Tạo Chrome Extension (Manifest V3) tự động auth proxy cho profile_id
        nếu có username/password.
        """
        # Không có proxy hoặc thiếu user/pass -> không tạo extension
        if (
            not proxy
            or not getattr(proxy, "host", None)
            or not getattr(proxy, "username", None)
            or not getattr(proxy, "password", None)
        ):
            return None

        base_dir = Path(__file__).resolve().parent.parent
        ext_dir = base_dir / "chrome_ext" / f"proxy_auth_{profile_id}"
        ext_dir.mkdir(parents=True, exist_ok=True)

        # ================= Manifest V3 =================
        manifest = {
            "name": f"MB Proxy Auth {profile_id}",
            "version": "1.0.0",
            "manifest_version": 3,
            "permissions": [
                "webRequest",
                "webRequestAuthProvider",
                "proxy",          # thêm để sát pattern proxy extension chính thống
            ],
            "host_permissions": [
                "<all_urls>",
            ],
            "background": {
                "service_worker": "background.js",
            },
        }
        manifest_path = ext_dir / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        # =================================================

        # ============= background.js – onAuthRequired (MV3, asyncBlocking) ============
        user_literal = json.dumps(proxy.username)
        pass_literal = json.dumps(proxy.password)

        bg_code = f"""const PROXY_USER = {user_literal};
const PROXY_PASS = {pass_literal};

const MAX_PROXY_AUTH_RETRIES = 3;
const retryMap = new Map();

console.log("MB Proxy Auth {profile_id} loaded. User =", PROXY_USER);

chrome.webRequest.onAuthRequired.addListener(
  (details, callback) => {{
    try {{
      console.log("MB Proxy Auth {profile_id} onAuthRequired", {{
        url: details.url,
        isProxy: details.isProxy,
        statusCode: details.statusCode,
        method: details.method,
        requestId: details.requestId,
        challenger: details.challenger,
      }});

      // Chỉ xử lý auth cho proxy (407 từ proxy), tránh đụng 401 của website
      if (!details.isProxy) {{
        callback({{}});
        return;
      }}

      // Giới hạn số lần thử cho mỗi requestId / proxy để tránh loop ERR_TOO_MANY_RETRIES
      const key =
        details.requestId ||
        (details.challenger
          ? details.challenger.host + ":" + details.challenger.port
          : "unknown");

      const current = retryMap.get(key) || 0;
      if (current >= MAX_PROXY_AUTH_RETRIES) {{
        console.warn("MB Proxy Auth {profile_id}: max retries reached for", key);
        callback({{}});
        return;
      }}
      retryMap.set(key, current + 1);

      callback({{
        authCredentials: {{
          username: PROXY_USER,
          password: PROXY_PASS,
        }},
      }});
    }} catch (e) {{
      console.error("MB Proxy Auth {profile_id} error in onAuthRequired", e);
      // Có lỗi thì trả rỗng để Chrome tự xử lý (popup) chứ không loop
      callback({{}});
    }}
  }},
  {{ urls: ["<all_urls>"] }},
  ["asyncBlocking"]
);
"""
        (ext_dir / "background.js").write_text(bg_code, encoding="utf-8")
        # ===========================================================================

        return str(ext_dir)

    def open_browser(self, profile_id: str) -> None:
        """Mở Chrome cho profile_id với cấu hình window + proxy per-profile,
        sau đó bảo đảm (nếu có) DevTools được attach lại."""
        cfg = self.get_profile_config(profile_id)
        port = self._get_port(profile_id)

        chrome_path = cfg.chrome_path or get_default_chrome_path()
        user_data_dir = cfg.user_data_dir or get_default_user_data_dir(profile_id)
        os.makedirs(user_data_dir, exist_ok=True)

        # width/height/scale từ cấu hình window
        width = cfg.window.width
        height = cfg.window.height
        scale = max(10, cfg.window.scale_percent) / 100.0  # tránh 0
        win_w = int(width * scale)
        win_h = int(height * scale)

        proc = self.processes.get(profile_id)
        if proc and proc.poll() is None:
            log.info("Browser for %s already running (reuse).", profile_id)
        else:
            args = [
                chrome_path,
                f"--remote-debugging-port={port}",
                f"--user-data-dir={user_data_dir}",

                # Giữ Chrome/tab game hoạt động mạnh hơn khi chạy nền
                "--disable-background-timer-throttling",
                "--disable-backgrounding-occluded-windows",
                "--disable-renderer-backgrounding",

                "--disable-dev-shm-usage",
                "--no-first-run",
                "--no-default-browser-check",
                f"--window-size={win_w},{win_h}",
                "--remote-allow-origins=*",
            ]
            proxy = cfg.proxy
            scheme: Optional[str] = None
            host_part: Optional[str] = None

            if proxy and proxy.host and proxy.port:
                raw_host = proxy.host.strip()
                port_val = int(proxy.port)

                if "://" in raw_host:
                    scheme, host_part = raw_host.split("://", 1)
                    scheme = scheme.lower()
                else:
                    scheme = "http"
                    host_part = raw_host

                if ":" not in host_part:
                    host_part = f"{host_part}:{port_val}"
            else:
                proxy = None
                
            # 1) Proxy auth bây giờ do extension KenDZ_P* cài sẵn trong profile xử lý.
            # Không còn tự tạo proxy_auth_* nữa.
            # (Nếu cần, có thể bỏ toàn bộ hàm _prepare_proxy_extension phía dưới.)

            # 2) Tham số --proxy-server
            if proxy and scheme and host_part:
                if scheme == "socks5":
                    # SOCKS5: nếu có user/pass phải embed vào URI để Chrome dùng trong handshake
                    if proxy.username and proxy.password:
                        proxy_uri = f"socks5://{proxy.username}:{proxy.password}@{host_part}"
                    else:
                        proxy_uri = f"socks5://{host_part}"
                elif scheme in ("http", "https"):
                    proxy_uri = f"{scheme}://{host_part}"
                else:
                    proxy_uri = host_part

                args.append(f"--proxy-server={proxy_uri}")
                log.info("Browser[%s] dùng proxy server: %s", profile_id, proxy_uri)
            else:
                log.info("Browser[%s] không dùng proxy", profile_id)

            try:
                proc = subprocess.Popen(
                    args,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                self.processes[profile_id] = proc
                log.info(
                    "Launched Chrome for %s on port %s, window=%sx%s, scale=%.2f",
                    profile_id,
                    port,
                    win_w,
                    win_h,
                    scale,
                )
            except Exception as e:
                log.error("Không thể mở Chrome cho %s: %s", profile_id, e)
                raise

        # Attach DevTools nếu có
        if hasattr(self, "ensure_tab"):
            try:
                self.ensure_tab(profile_id)
            except Exception as e:
                log.error("Không thể attach DevTools cho %s: %s", profile_id, e)

    def close_browser(self, profile_id: str) -> None:
        tab = self.tabs.get(profile_id)
        if tab:
            tab.devtools.disconnect()
            del self.tabs[profile_id]
            log.info("DevTools for %s closed", profile_id)

        proc = self.processes.get(profile_id)
        if proc and proc.poll() is None:
            try:
                proc.terminate()
                proc.wait(timeout=5)
                log.info("Chrome process for %s terminated", profile_id)
            except Exception as e:
                log.warning("Không thể terminate Chrome cho %s: %s", profile_id, e)
        if profile_id in self.processes:
            del self.processes[profile_id]

    def get_active_tab(self, profile_id: str) -> Optional[BrowserTab]:
        return self.tabs.get(profile_id)
        
    def delete_profile_user_data(self, profile_id: str) -> bool:
        """
        Xóa thư mục user_data_dir hiện tại của profile (P1/P2/P3),
        SAU ĐÓ nếu có thư mục template <user_data_dir>-D (P1-D/P2-D/P3-D)
        thì tự động copy template đó sang làm profile mới.

        - Không sửa bất kỳ phần config nào khác (capture, proxy, window,...).
        - Đóng Chrome của profile trước khi xóa để tránh file lock.
        - Trả về True nếu coi như xóa + (copy template nếu có) xong.
        """
        # 1) Đảm bảo đóng trình duyệt + DevTools trước
        self.close_browser(profile_id)

        # 2) Lấy config mới nhất để biết user_data_dir hiện tại
        cfg = self.get_profile_config(profile_id)
        raw_path = cfg.user_data_dir or ""
        if not raw_path:
            log.error("Profile %s không có user_data_dir để xóa", profile_id)
            return False

        path = os.path.abspath(raw_path)

        # Safety: chặn xóa đường dẫn quá ngắn / nguy hiểm
        if len(path) < 10:
            log.error(
                "Đường dẫn user_data_dir quá ngắn, từ chối xóa cho an toàn: %s",
                path,
            )
            return False

        # 3) Xóa thư mục user-data hiện tại (nếu có)
        if os.path.exists(path):
            try:
                shutil.rmtree(path)
                log.info("Đã xóa user-data-dir của %s: %s", profile_id, path)
            except Exception as e:
                log.error(
                    "Không thể xóa user-data-dir của %s (%s): %s",
                    profile_id,
                    path,
                    e,
                )
                return False
        else:
            log.info(
                "Thư mục user-data của %s không tồn tại, coi như đã sạch: %s",
                profile_id,
                path,
            )

        # 4) Tự động copy thư mục template <user_data_dir>-D nếu có
        template_dir = path + "-D"
        if os.path.isdir(template_dir):
            try:
                shutil.copytree(template_dir, path)
                log.info(
                    "Đã reset profile %s từ template: %s -> %s",
                    profile_id,
                    template_dir,
                    path,
                )
            except Exception as e:
                log.error(
                    "Lỗi khi copy template cho %s (%s -> %s): %s",
                    profile_id,
                    template_dir,
                    path,
                    e,
                )
                # lỗi copy template vẫn trả False để UI báo lỗi
                return False
        else:
            # Không có template -> giữ hành vi cũ: để trống, lần mở trình duyệt
            # tiếp theo open_browser sẽ tự os.makedirs(user_data_dir, exist_ok=True)
            log.info(
                "Không tìm thấy template cho %s (expect: %s). "
                "Giữ profile trống, lần mở Chrome tiếp theo sẽ tạo mới.",
                profile_id,
                template_dir,
            )

        return True
