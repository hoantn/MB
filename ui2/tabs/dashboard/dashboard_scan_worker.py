# ui2/dashboard/dashboard_scan_worker.py
from typing import List, Optional

from PySide6.QtCore import QObject, Signal

from capture.capture_manager import CaptureManager
from core.logger import log
from vision.cropper import crop_slots
from vision.recognizer import recognize_card


class ScanWorker(QObject):
    """Worker chạy trong QThread để scan 1 hoặc nhiều profile."""

    finished = Signal()
    profile_scanned = Signal(str, object, object, object)  # pid, codes, confs, pil_images
    error = Signal(str, str)  # pid, message

    def __init__(self, profiles: List[str], capture_manager: CaptureManager) -> None:
        super().__init__()
        self._profiles = profiles
        self._capture_manager = capture_manager

    def _slot(self) -> int:
        try:
            browser_manager = getattr(self._capture_manager, "browser_manager", None)
            return int(getattr(browser_manager, "_slot", 1) or 1)
        except Exception:
            return 1

    def run(self) -> None:
        from PIL import Image  # type: ignore

        for pid in self._profiles:
            try:
                img = self._capture_manager.capture_region(pid)
                if img is None:
                    self.error.emit(pid, "Không capture được vùng game.")
                    continue

                pil_slots = crop_slots(pid, img, slot=self._slot())
                codes: List[Optional[str]] = [None] * 13
                confs: List[float] = [0.0] * 13
                images: List[Optional[Image.Image]] = [None] * 13  # type: ignore

                for i, card_img in enumerate(pil_slots):
                    if card_img is None:
                        codes[i] = None
                        confs[i] = 0.0
                        images[i] = None
                        continue
                    try:
                        code, conf, _ = recognize_card(card_img)
                    except Exception as e:
                        log.error(
                            "ScanWorker: lỗi recognize_card slot %s của %s: %s",
                            i + 1,
                            pid,
                            e,
                        )
                        code, conf = None, 0.0
                    codes[i] = code
                    confs[i] = float(conf or 0.0)
                    images[i] = card_img

                self.profile_scanned.emit(pid, codes, confs, images)
            except Exception as e:
                log.exception("ScanWorker: lỗi khi scan profile %s: %s", pid, e)
                self.error.emit(pid, str(e))

        self.finished.emit()
