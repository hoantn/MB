import os
import threading
import time
from typing import Any

from .constants import LOG_DIR


TRACE_PATH = os.path.join(LOG_DIR, "apply_trace.log")


def apply_trace(stage: str, profile_id: str = "-", **data: Any) -> None:
    """
    Breadcrumb cuc nhe cho luong xep bai.

    File nay duoc mo/ghi/dong ngay moi lan de khi ban exe thoat dot ngot,
    dong cuoi cung van cho biet tool dang dung o moc nao.
    """
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        ms = int((time.time() % 1) * 1000)
        thread_name = threading.current_thread().name
        extra = " ".join(f"{k}={repr(v)}" for k, v in sorted(data.items()))
        line = f"{ts}.{ms:03d} [{thread_name}] pid={profile_id} stage={stage}"
        if extra:
            line += " " + extra
        with open(TRACE_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
            f.flush()
    except Exception:
        # Trace khong bao gio duoc lam gay luong chinh.
        pass
