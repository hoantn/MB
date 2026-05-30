import json
from pathlib import Path
import os
import subprocess
import shutil
import time
import ctypes
from typing import Dict, Optional
import requests
from .local_proxy import AuthHttpForwardProxy

from core.config import load_config, save_config
from core.constants import BASE_DIR
from core.logger import log
from core.tool_instance import (
    get_profile_port,
    get_local_proxy_port,
    get_tool_extension_dir,
    get_tool_index,
    get_tool_name,
)
from .profile import ProfileConfig
from .devtools import DevToolsClient
from .tab import BrowserTab


PROFILE_PORTS = {}
RUNTIME_BROWSER_DIR = os.path.join(BASE_DIR, "runtime")
PREFERRED_BROWSER_EXES = (
    "GoogleChromePortable.exe",
    "chrome.exe",
    "msedge.exe",
)


class _WindowsRect(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


def get_primary_work_area() -> tuple[int, int, int, int]:
    """Return the usable primary desktop area, excluding the Windows taskbar."""
    try:
        rect = _WindowsRect()
        ok = ctypes.windll.user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(rect), 0)
        if ok and rect.right > rect.left and rect.bottom > rect.top:
            return int(rect.left), int(rect.top), int(rect.right), int(rect.bottom)
    except Exception:
        pass

    try:
        width = int(ctypes.windll.user32.GetSystemMetrics(0))
        height = int(ctypes.windll.user32.GetSystemMetrics(1))
        if width > 0 and height > 0:
            return 0, 0, width, height
    except Exception:
        pass

    return 0, 0, 1920, 1080


def get_profile_window_position(profile_id: str, win_w: int) -> tuple[int, int]:
    """Anchor P1/P2/P3 at the top-left, top-center and top-right."""
    left, top, right, _bottom = get_primary_work_area()
    available_w = max(1, int(right) - int(left))
    window_w = max(1, int(win_w))
    max_x = max(int(left), int(right) - window_w)

    pid = str(profile_id or "").upper()
    if pid == "P1":
        x = int(left)
    elif pid == "P3":
        x = max_x
    else:
        x = int(left) + max(0, (available_w - window_w) // 2)
        x = min(max_x, x)
    return x, int(top)


def get_default_chrome_path() -> str:
    """Tìm chrome.exe mặc định trên Windows, nếu không thấy thì trả 'chrome'."""
    candidates = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    ]
    for p in candidates:
        if os.path.exists(p):
            return p
    return "chrome"


def is_official_chromium_path(path: str) -> bool:
    p = (path or "").lower().replace("/", "\\")
    return (
        p.endswith("\\google\\chrome\\application\\chrome.exe")
        or p.endswith("\\microsoft\\edge\\application\\msedge.exe")
    )


def profile_has_tool_extension(user_data_dir: str, ext_dir: str) -> bool:
    pref_path = os.path.join(user_data_dir, "Default", "Preferences")
    if not os.path.exists(pref_path):
        return False
    try:
        with open(pref_path, "r", encoding="utf-8") as f:
            prefs = json.load(f)
        settings = ((prefs.get("extensions") or {}).get("settings") or {})
        ext_abs = os.path.abspath(ext_dir)
        for item in settings.values():
            path = os.path.abspath(str(item.get("path") or ""))
            manifest = item.get("manifest") or {}
            name = str(manifest.get("name") or "")
            if path == ext_abs or name.startswith("Kendz MB Tool"):
                return True
    except Exception:
        return False
    return False


def open_chrome_extensions_page(port: int) -> bool:
    url = f"http://127.0.0.1:{port}/json/new?chrome://extensions/"
    for _ in range(12):
        try:
            requests.put(url, timeout=0.5)
            return True
        except Exception:
            time.sleep(0.25)
    return False


def is_devtools_port_ready(port: int, timeout: float = 0.4) -> bool:
    """Return True only when the DevTools endpoint has an attachable page tab."""
    try:
        r = requests.get(f"http://127.0.0.1:{int(port)}/json", timeout=timeout)
        if r.status_code != 200:
            return False
        tabs = r.json()
        return any(
            t.get("type") == "page" and t.get("webSocketDebuggerUrl")
            for t in tabs
            if isinstance(t, dict)
        )
    except Exception:
        return False


def get_default_user_data_dir(profile_id: str) -> str:
    root = os.path.join(BASE_DIR, "user-data")
    os.makedirs(root, exist_ok=True)
    return os.path.join(root, str(profile_id or "P1"))


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

    def _find_browser_exe_in_dir(self, folder: str) -> Optional[str]:
        """Find the runnable executable in a clean browser/runtime folder."""
        if not os.path.isdir(folder):
            return None

        for name in PREFERRED_BROWSER_EXES:
            p = os.path.join(folder, name)
            if os.path.isfile(p):
                return p

        try:
            for name in os.listdir(folder):
                p = os.path.join(folder, name)
                if os.path.isfile(p) and name.lower().endswith(".exe"):
                    return p
        except Exception:
            return None
        return None

    def _resolve_browser_source_dir(self, chrome_path: str) -> str:
        """
        Resolve user input into a clean browser/profile source folder.

        The browser tab now asks the user for a folder only. If old config still
        points to an exe, keep compatibility by using the exe parent folder.
        """
        raw_input = str(chrome_path or "").strip()
        if not raw_input:
            raise FileNotFoundError("Chưa chọn thư mục Profile sạch/gốc.")
        raw = os.path.abspath(raw_input)
        if os.path.isdir(raw):
            exe = self._find_browser_exe_in_dir(raw)
            if not exe:
                raise FileNotFoundError(f"Không tìm thấy file exe trong thư mục trình duyệt: {raw}")
            return raw

        if os.path.isfile(raw) and raw.lower().endswith(".exe"):
            return os.path.dirname(raw)

        raise FileNotFoundError(f"Đường dẫn trình duyệt không hợp lệ: {chrome_path}")

    def _get_runtime_profile_dir(self, profile_id: str) -> str:
        return os.path.join(RUNTIME_BROWSER_DIR, str(profile_id or "P1"))

    def _terminate_process_tree(self, proc: subprocess.Popen, profile_id: str) -> None:
        """Terminate launcher + child chrome.exe processes for this profile."""
        if proc is None or proc.poll() is not None:
            return
        try:
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                    creationflags=0x08000000,
                )
                try:
                    proc.wait(timeout=5)
                except Exception:
                    pass
            else:
                proc.terminate()
                proc.wait(timeout=5)
            log.info("Chrome process tree for %s terminated", profile_id)
        except Exception as e:
            log.warning("Cannot terminate Chrome process tree for %s: %s", profile_id, e)

    def _get_browser_pids_by_port(self, port: int) -> set[int]:
        """Find browser processes that belong to the profile DevTools port."""
        if os.name != "nt":
            return set()

        needle = f"--remote-debugging-port={int(port)}"
        cmd = (
            "$ErrorActionPreference='SilentlyContinue'; "
            "Get-CimInstance Win32_Process | "
            f"Where-Object {{ $_.CommandLine -like '*{needle}*' }} | "
            "ForEach-Object { $_.ProcessId }"
        )
        try:
            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command", cmd],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=2,
                creationflags=0x08000000,
            )
        except Exception:
            return set()

        pids: set[int] = set()
        for line in (result.stdout or "").splitlines():
            try:
                pids.add(int(line.strip()))
            except ValueError:
                pass
        return pids

    def _focus_browser_window_by_port(self, profile_id: str, port: int) -> bool:
        """Bring the visible Windows browser window for this profile to front."""
        pids = self._get_browser_pids_by_port(port)
        if not pids or os.name != "nt":
            return False

        user32 = ctypes.windll.user32
        hwnds: list[int] = []

        @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
        def enum_proc(hwnd, _lparam):
            if not user32.IsWindowVisible(hwnd):
                return True
            pid = ctypes.c_ulong()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if int(pid.value) in pids and user32.GetWindowTextLengthW(hwnd) > 0:
                hwnds.append(int(hwnd))
            return True

        try:
            user32.EnumWindows(enum_proc, 0)
            if not hwnds:
                return False

            hwnd = hwnds[0]
            SW_RESTORE = 9
            user32.ShowWindow(hwnd, SW_RESTORE)
            user32.BringWindowToTop(hwnd)
            ok = bool(user32.SetForegroundWindow(hwnd))
            log.info("Browser[%s] focused existing window: hwnd=%s ok=%s", profile_id, hwnd, ok)
            return ok
        except Exception as e:
            log.warning("Browser[%s] cannot focus existing window: %s", profile_id, e)
            return False

    def _bring_existing_browser_to_front(self, profile_id: str, port: int) -> None:
        """Reuse an existing browser and guide the user back to its window."""
        try:
            tab = self.ensure_tab(profile_id)
            if tab:
                tab.devtools.install_title_prefix(f"[{profile_id}]")
                tab.devtools.bring_to_front()
        except Exception as e:
            log.warning("Browser[%s] cannot bring DevTools page to front: %s", profile_id, e)
        self._focus_browser_window_by_port(profile_id, port)

    def _install_profile_title_prefix(self, profile_id: str) -> None:
        """Make the profile id visible in the browser title/taskbar preview."""
        try:
            tab = self.ensure_tab(profile_id)
            if tab:
                tab.devtools.install_title_prefix(f"[{profile_id}]")
        except Exception as e:
            log.warning("Browser[%s] cannot install title prefix: %s", profile_id, e)

    def _prepare_runtime_browser_dir(self, profile_id: str, chrome_path: str) -> tuple[str, str]:
        """
        Copy the clean browser source folder into runtime/<profile> on first open.

        The source folder is never launched directly. If runtime/<profile> already
        exists, it is reused as-is.
        """
        template_dir = self._resolve_browser_source_dir(chrome_path)
        runtime_dir = self._get_runtime_profile_dir(profile_id)

        if not os.path.isdir(runtime_dir):
            os.makedirs(os.path.dirname(runtime_dir), exist_ok=True)
            try:
                shutil.copytree(template_dir, runtime_dir)
                log.info(
                    "Browser[%s] runtime browser copied: %s -> %s",
                    profile_id,
                    template_dir,
                    runtime_dir,
                )
            except Exception as e:
                log.error("Browser[%s] cannot copy runtime browser from %s: %s", profile_id, template_dir, e)
                raise

        runtime_exe = self._find_browser_exe_in_dir(runtime_dir)
        if not runtime_exe or not os.path.isfile(runtime_exe):
            raise FileNotFoundError(f"Không tìm thấy file exe trong runtime browser: {runtime_dir}")

        return runtime_dir, runtime_exe

    # luôn load lại config mới nhất trước khi xử lý
    def _load_config_fresh(self) -> dict:
        self.config = load_config()
        return self.config

    def reload_config(self):
        self._load_config_fresh()

    def get_profile_config(self, profile_id: str) -> ProfileConfig:
        """
        Đọc config mới nhất. Không tự sinh user_data_dir nữa vì runtime
        trình duyệt luôn nằm trong tool/runtime/P?.
        """
        cfg = self._load_config_fresh()
        profiles = cfg.get("profiles", {})
        d = profiles.get(profile_id, {})

        # user_data_dir is legacy UI data. Runtime browsers are always managed
        # under tool/runtime/P?, so do not auto-fill or depend on a user path.

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
        return get_profile_port(profile_id)

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

        local_port = get_local_proxy_port(profile_id)

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
        tool_index = get_tool_index()
        tool_name = get_tool_name(tool_index)

        # Chrome Portable may leave the launcher process while the real browser
        # process is already serving DevTools. Treat the DevTools page as the
        # source of truth so repeated "Open" clicks cannot spawn duplicates.
        if is_devtools_port_ready(port):
            log.info("Browser for %s already open on DevTools port %s (reuse).", profile_id, port)
            self._bring_existing_browser_to_front(profile_id, port)
            return

        chrome_path = cfg.chrome_path
        runtime_dir, launch_chrome_path = self._prepare_runtime_browser_dir(profile_id, chrome_path)
        exe_name = os.path.basename(launch_chrome_path).lower()
        user_data_dir = os.path.join(runtime_dir, "user-data")
        ws_ext_dir = get_tool_extension_dir(profile_id, tool_index)
        has_ws_ext = os.path.isdir(ws_ext_dir)
        needs_manual_extension = (
            has_ws_ext
            and is_official_chromium_path(chrome_path)
            and not profile_has_tool_extension(user_data_dir, ws_ext_dir)
        )

        # width/height/scale từ cấu hình window
        width = cfg.window.width
        height = cfg.window.height
        scale = max(10, cfg.window.scale_percent) / 100.0  # tránh 0
        win_w = int(width * scale)
        win_h = int(height * scale)
        win_x, win_y = get_profile_window_position(profile_id, win_w)

        proc = self.processes.get(profile_id)
        if proc and proc.poll() is None:
            if is_devtools_port_ready(port):
                log.info("Browser for %s already running (reuse).", profile_id)
                self._bring_existing_browser_to_front(profile_id, port)
            else:
                log.warning(
                    "Browser for %s has live process but DevTools port %s is not ready; relaunch.",
                    profile_id,
                    port,
                )
                try:
                    tab = self.tabs.pop(profile_id, None)
                    if tab:
                        tab.devtools.disconnect()
                except Exception:
                    pass
                self._terminate_process_tree(proc, profile_id)
                self.processes.pop(profile_id, None)
                proc = None

        if proc and proc.poll() is None:
            pass
        else:
            args = [
                launch_chrome_path,
                f"--remote-debugging-port={port}",

                # Giữ Chrome/tab game hoạt động mạnh hơn khi chạy nền
                "--disable-background-timer-throttling",
                "--disable-backgrounding-occluded-windows",
                "--disable-renderer-backgrounding",

                "--disable-dev-shm-usage",
                "--no-first-run",
                "--no-default-browser-check",
                f"--window-size={win_w},{win_h}",
                f"--window-position={win_x},{win_y}",
                "--remote-allow-origins=*",
            ]
            if exe_name != "googlechromeportable.exe":
                os.makedirs(user_data_dir, exist_ok=True)
                args.insert(2, f"--user-data-dir={user_data_dir}")

            if has_ws_ext:
                if not is_official_chromium_path(chrome_path):
                    args.append(f"--disable-extensions-except={ws_ext_dir}")
                args.append(f"--load-extension={ws_ext_dir}")
                log.info("Browser[%s] load WS extension for %s: %s", profile_id, tool_name, ws_ext_dir)
                if needs_manual_extension:
                    args.append("chrome://extensions/")
                    log.warning(
                        "Browser[%s] can cai extension thu cong cho %s: bat Developer mode, Load unpacked, chon thu muc: %s",
                        profile_id,
                        tool_name,
                        ws_ext_dir,
                    )
            else:
                log.warning(
                    "Browser[%s] khÃ´ng tháº¥y WS extension cho %s: %s",
                    profile_id,
                    tool_name,
                    ws_ext_dir,
                )
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
                    cwd=runtime_dir,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                self.processes[profile_id] = proc
                if needs_manual_extension:
                    if not open_chrome_extensions_page(port):
                        log.warning(
                            "Browser[%s] khong mo duoc chrome://extensions qua DevTools port %s",
                            profile_id,
                            port,
                        )
                log.info(
                    "Launched Chrome for %s (%s) on port %s, window=%sx%s@%s,%s, scale=%.2f, exe=%s",
                    profile_id,
                    tool_name,
                    port,
                    win_w,
                    win_h,
                    win_x,
                    win_y,
                    scale,
                    launch_chrome_path,
                )
            except Exception as e:
                log.error("Không thể mở Chrome cho %s: %s", profile_id, e)
                raise

        # Attach DevTools nếu có
        if hasattr(self, "ensure_tab"):
            try:
                self.ensure_tab(profile_id)
                self._install_profile_title_prefix(profile_id)
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
                self._terminate_process_tree(proc, profile_id)
            except Exception as e:
                log.warning("Không thể terminate Chrome cho %s: %s", profile_id, e)
        if profile_id in self.processes:
            del self.processes[profile_id]

    def get_active_tab(self, profile_id: str) -> Optional[BrowserTab]:
        return self.tabs.get(profile_id)
        
    def delete_profile_user_data(self, profile_id: str) -> bool:
        """Delete runtime/<profile>; the clean browser source folder is untouched."""
        self.close_browser(profile_id)

        runtime_root = os.path.abspath(RUNTIME_BROWSER_DIR)
        path = os.path.abspath(self._get_runtime_profile_dir(profile_id))
        if not (path == runtime_root or path.startswith(runtime_root + os.sep)):
            log.error("Refuse to delete runtime profile outside runtime root: %s", path)
            return False

        if not os.path.isdir(path):
            log.info("Runtime browser profile %s does not exist, already clean: %s", profile_id, path)
            return True

        try:
            shutil.rmtree(path)
            log.info("Deleted runtime browser profile %s: %s", profile_id, path)
            return True
        except Exception as e:
            log.error("Cannot delete runtime browser profile %s (%s): %s", profile_id, path, e)
            return False

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
