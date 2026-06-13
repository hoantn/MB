from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple
import datetime
import requests

from .config import load_config, save_config
from .logger import log


# Provider identifiers – dùng nội bộ module này
PROXY_PROVIDER_NONE = "none"
PROXY_PROVIDER_RAW = "raw"
PROXY_PROVIDER_TM_PROXY = "tmproxy"
PROXY_PROVIDER_PROXYNO1 = "proxyno1"


@dataclass
class Proxyno1Settings:
    """
    Cấu hình global cho ProxyNo1.

    Có thể override bằng block 'proxyno1' trong config.json:
    {
      "proxyno1": {
        "base_url": "...",
        "change_ip_path_template": "/change-key-ip/{api_key}",
        "key_status_path_template": "/key-status/{key}",
        "timeout_sec": 15
      }
    }
    """
    base_url: str = "https://app.proxyno1.com/api"
    change_ip_path_template: str = "/change-key-ip/{api_key}"
    key_status_path_template: str = "/key-status/{key}"
    timeout_sec: float = 15.0


class Proxyno1Client:
    """
    Client gọi API đổi IP ProxyNo1 theo API key.

    API change-key-ip chỉ đổi IP phía sau line,
    KHÔNG trả về host/port mới.
    """

    def __init__(self, api_key: str, settings: Optional[Proxyno1Settings] = None) -> None:
        if not api_key:
            raise ValueError("proxyno1_api_key is empty")

        self.api_key = api_key
        self.settings = settings or Proxyno1Settings()

    # ------------------------------------------------------------------
    # Helper
    # ------------------------------------------------------------------
    def _build_change_ip_url(self) -> str:
        base = self.settings.base_url.rstrip("/")
        path = self.settings.change_ip_path_template.format(api_key=self.api_key)
        if not path.startswith("/"):
            path = "/" + path
        return base + path

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def change_ip(self) -> Dict[str, Any]:
        """
        Gọi API đổi IP.

        Trả về:
            data (dict): JSON response của ProxyNo1.
        Ném RuntimeError nếu có lỗi HTTP / network / JSON.
        """
        url = self._build_change_ip_url()
        log.info("[ProxyNo1] Gọi change-ip: %s", url)

        try:
            resp = requests.get(url, timeout=self.settings.timeout_sec)
        except Exception as exc:  # network error
            log.error("[ProxyNo1] Lỗi kết nối: %s", exc)
            raise RuntimeError(f"Lỗi kết nối tới ProxyNo1: {exc}") from exc

        if resp.status_code != 200:
            msg = resp.text[:200]
            log.error("[ProxyNo1] HTTP %s: %s", resp.status_code, msg)
            raise RuntimeError(f"ProxyNo1 trả về HTTP {resp.status_code}: {msg}")

        try:
            data = resp.json()
        except Exception as exc:
            log.error("[ProxyNo1] JSON parse error: %s", exc)
            raise RuntimeError(f"Không parse được JSON từ ProxyNo1: {exc}") from exc

        # Thực tế response thường có field "message"
        msg = data.get("message") if isinstance(data, dict) else str(data)
        log.info("[ProxyNo1] change-ip OK: %s", msg)
        return data
        
    def get_key_status(self) -> Dict[str, Any]:
        """
        Gọi API key-status để lấy thông tin proxy của key hiện tại.

        Response mẫu:
        {
          "status": 0,
          "message": "Thành công",
          "data": {
             "key": "...",
             "http": "ip:port:user:pass" hoặc null,
             "sock5": "ip:port:user:pass" hoặc null,
             ...
          }
        }
        """
        url = self._build_key_status_url()
        log.info("[ProxyNo1] Gọi key-status: %s", url)

        try:
            resp = requests.get(url, timeout=self.settings.timeout_sec)
        except Exception as exc:
            log.error("[ProxyNo1] Lỗi kết nối key-status: %s", exc)
            raise RuntimeError(f"Lỗi kết nối tới ProxyNo1 key-status: {exc}") from exc

        if resp.status_code != 200:
            msg = resp.text[:200]
            log.error("[ProxyNo1] key-status HTTP %s: %s", resp.status_code, msg)
            raise RuntimeError(f"ProxyNo1 key-status HTTP {resp.status_code}: {msg}")

        try:
            data = resp.json()
        except Exception as exc:
            log.error("[ProxyNo1] key-status JSON parse error: %s", exc)
            raise RuntimeError(f"Không parse được JSON key-status: {exc}") from exc

        return data

    def _build_key_status_url(self) -> str:
        base = self.settings.base_url.rstrip("/")
        path = self.settings.key_status_path_template.format(key=self.api_key)
        if not path.startswith("/"):
            path = "/" + path
        return base + path

# ======================================================================
# Helper thao tác với config.json
# ======================================================================

def _get_global_proxyno1_settings(cfg: Dict[str, Any]) -> Proxyno1Settings:
    """
    Đọc block 'proxyno1' ở mức global (nếu có) để override default.
    """
    cfg_p = cfg.get("proxyno1", {}) or {}
    base_url = cfg_p.get("base_url") or Proxyno1Settings.base_url
    change_tpl = cfg_p.get("change_ip_path_template") or Proxyno1Settings.change_ip_path_template
    status_tpl = cfg_p.get("key_status_path_template") or Proxyno1Settings.key_status_path_template
    timeout_raw = cfg_p.get("timeout_sec", Proxyno1Settings.timeout_sec)

    try:
        timeout = float(timeout_raw)
    except Exception:
        timeout = Proxyno1Settings.timeout_sec

    return Proxyno1Settings(
        base_url=base_url,
        change_ip_path_template=change_tpl,
        key_status_path_template=status_tpl,
        timeout_sec=timeout,
    )


def _get_profile_proxy_dict(cfg: Dict[str, Any], profile_id: str) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """
    Trả về (profile_dict, proxy_dict) cho profile_id.
    Auto tạo khung proxy nếu chưa có.
    """
    profiles = cfg.setdefault("profiles", {})
    if profile_id not in profiles:
        raise KeyError(f"Không tìm thấy profile '{profile_id}' trong config")

    p = profiles[profile_id]
    proxy = p.setdefault("proxy", {})
    if "host" not in proxy:
        proxy.setdefault("host", "")
    if "port" not in proxy:
        proxy.setdefault("port", 0)
    if "username" not in proxy:
        proxy.setdefault("username", "")
    if "password" not in proxy:
        proxy.setdefault("password", "")

    return p, proxy


def infer_provider(proxy_dict: Dict[str, Any]) -> str:
    """
    SUY LUẬN provider theo dữ liệu hiện có (giữ tương thích bản cũ).

    Ưu tiên:
    - Nếu đã có proxy['provider'] → dùng luôn.
    - Nếu có tmproxy_api_key → 'tmproxy'.
    - Nếu có host/port → 'raw'.
    - Ngược lại → 'none'.
    """
    provider = (proxy_dict.get("provider") or "").strip().lower()
    if provider:
        return provider

    if proxy_dict.get("tmproxy_api_key"):
        return PROXY_PROVIDER_TM_PROXY

    if proxy_dict.get("host") and (proxy_dict.get("port") or 0):
        return PROXY_PROVIDER_RAW

    return PROXY_PROVIDER_NONE


def ensure_proxyno1_provider(proxy_dict: Dict[str, Any]) -> None:
    """
    Nếu chưa set provider mà profile rõ ràng dùng proxyno1
    (có proxyno1_api_key) → set provider = 'proxyno1'.
    """
    if proxy_dict.get("provider"):
        return
    if proxy_dict.get("proxyno1_api_key"):
        proxy_dict["provider"] = PROXY_PROVIDER_PROXYNO1


# ======================================================================
# API chính: gọi đổi IP cho 1 profile
# ======================================================================
def proxyno1_get_proxy_info_for_profile(profile_id: str, slot: int = 1) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """
    Lấy thông tin proxy (HTTP/SOCKS5) cho 1 profile thông qua key-status.

    Trả về: (ok, message, info_dict | None)

    info_dict có dạng:
    {
      "host": str,
      "port": int,              # port mặc định (ưu tiên socks5, fallback http – để tương thích cũ)
      "username": str,
      "password": str,
      "protocol": "http" | "socks5",
      "http_port": int,         # 0 nếu không có
      "socks5_port": int,       # 0 nếu không có
    }
    """
    cfg = load_config(slot)
    try:
        profile_dict, proxy = _get_profile_proxy_dict(cfg, profile_id)
    except KeyError as e:
        return False, str(e), None

    # Lấy API key: ưu tiên profile, sau đó global
    api_key = (proxy.get("proxyno1_api_key") or "").strip()
    if not api_key:
        global_cfg = cfg.get("proxyno1", {}) or {}
        api_key = (global_cfg.get("api_key") or "").strip()

    if not api_key:
        return False, (
            f"Chưa cấu hình proxyno1_api_key cho profile {profile_id} hoặc global 'proxyno1.api_key'."
        ), None

    settings = _get_global_proxyno1_settings(cfg)
    client = Proxyno1Client(api_key=api_key, settings=settings)

    try:
        data = client.get_key_status()
    except Exception as exc:
        return False, str(exc), None

    if not isinstance(data, dict):
        return False, "ProxyNo1 trả về JSON không hợp lệ.", None

    status = data.get("status")
    if status != 0:
        msg = data.get("message", "ProxyNo1 báo lỗi")
        return False, msg, None

    payload = data.get("data") or {}

    # Authentication (user:pass)
    auth = str(payload.get("authentication") or "").strip()
    username = ""
    password = ""
    if ":" in auth:
        username, password = auth.split(":", 1)

    host = ""
    http_port = 0
    socks_port = 0

    # --------- Format cũ: field 'http' / 'sock5' dạng ip:port:user:pass ----------
    http_str = str(payload.get("http") or "").strip()
    socks_str = str(payload.get("sock5") or payload.get("socks5") or "").strip()

    if http_str:
        parts = http_str.split(":")
        if len(parts) >= 2 and parts[1].isdigit():
            if not host:
                host = parts[0].strip()
            http_port = int(parts[1])
            if len(parts) >= 3 and not username:
                username = parts[2].strip()
            if len(parts) >= 4 and not password:
                password = parts[3].strip()

    if socks_str:
        parts = socks_str.split(":")
        if len(parts) >= 2 and parts[1].isdigit():
            if not host:
                host = parts[0].strip()
            socks_port = int(parts[1])
            if len(parts) >= 3 and not username:
                username = parts[2].strip()
            if len(parts) >= 4 and not password:
                password = parts[3].strip()

    # --------- Format mới: block 'proxy' + HTTP_IPv4 / SocksV5_IPv4 ----------
    if not http_str and not socks_str:
        proxy_block = payload.get("proxy") or {}
        host = str(proxy_block.get("ip") or "").strip()

        http_port_raw = proxy_block.get("HTTP_IPv4") or 0
        socks_port_raw = (
            proxy_block.get("SocksV5_IPv4")
            or proxy_block.get("Socks5_IPv4")
            or proxy_block.get("SOCKS5_IPv4")
            or 0
        )

        try:
            http_port = int(http_port_raw)
        except Exception:
            http_port = 0
        try:
            socks_port = int(socks_port_raw)
        except Exception:
            socks_port = 0

    # Chọn protocol mặc định (để hiển thị / tương thích cũ)
    if socks_port > 0:
        protocol = "socks5"
        default_port = socks_port
    elif http_port > 0:
        protocol = "http"
        default_port = http_port
    else:
        return False, "Key không có HTTP hoặc SOCKS5 proxy.", None

    if not host:
        return False, "Không tìm thấy host proxy trong key-status.", None

    # Ghi lại log basic cho UI / debug
    proxy["proxyno1_last_status_at"] = datetime.datetime.now().isoformat(timespec="seconds")
    proxy["proxyno1_last_status_msg"] = str(data.get("message", "OK"))
    try:
        save_config(cfg, slot)
    except Exception as e:
        log.error("[ProxyNo1] Lỗi khi save_config sau get_proxy_info: %s", e)

    info = {
        "host": host,
        "port": default_port,
        "username": username,
        "password": password,
        "protocol": protocol,
        "http_port": http_port,
        "socks5_port": socks_port,
    }
    msg = data.get("message") or "Lấy proxy ProxyNo1 thành công."
    return True, msg, info

def proxyno1_change_ip_for_profile(profile_id: str, slot: int = 1) -> Tuple[bool, str]:
    """
    Đổi IP ProxyNo1 cho 1 profile dựa trên config của slot tương ứng.

    - Đọc config theo slot (1→config.json, 2→config-tool2.json, ...).
    - Lấy proxyno1_api_key (ưu tiên theo profile, fallback global).
    - Gọi API change-key-ip.
    - Ghi lại thời gian + message cuối cùng vào config (để UI hiển thị).
    - Không sửa host/port (ProxyNo1 giữ nguyên line).

    Trả về: (ok: bool, message: str)
    """
    cfg = load_config(slot)
    try:
        profile_dict, proxy = _get_profile_proxy_dict(cfg, profile_id)
    except KeyError as e:
        return False, str(e)

    # Lấy API key: ưu tiên profile, sau đó mới tới global
    api_key = (proxy.get("proxyno1_api_key") or "").strip()
    if not api_key:
        global_cfg = cfg.get("proxyno1", {}) or {}
        api_key = (global_cfg.get("api_key") or "").strip()

    if not api_key:
        return False, (
            f"Chưa cấu hình proxyno1_api_key cho profile {profile_id} hoặc global 'proxyno1.api_key'."
        )

    # Đảm bảo provider nếu dùng proxyno1
    ensure_proxyno1_provider(proxy)

    settings = _get_global_proxyno1_settings(cfg)
    client = Proxyno1Client(api_key=api_key, settings=settings)

    try:
        data = client.change_ip()
        msg = data.get("message") if isinstance(data, dict) else str(data)
        ok = True
        error = ""
    except Exception as exc:
        msg = ""
        ok = False
        error = str(exc)

    # Ghi lại lịch sử cơ bản cho UI / debug
    now = datetime.datetime.now().isoformat(timespec="seconds")
    proxy["proxyno1_last_change_at"] = now
    if ok:
        proxy["proxyno1_last_message"] = msg
        # Xoá lỗi cũ nếu có
        proxy.pop("proxyno1_last_error", None)
    else:
        proxy["proxyno1_last_error"] = error

    # Lưu config đúng slot
    try:
        save_config(cfg, slot)
    except Exception as e:
        log.error("[ProxyNo1] Lỗi khi save_config sau change_ip slot=%d: %s", slot, e)

    if ok:
        return True, f"Đổi IP ProxyNo1 cho {profile_id} thành công: {msg}"
    return False, f"Đổi IP ProxyNo1 cho {profile_id} thất bại: {error}"
