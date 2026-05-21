from typing import List, Optional, Tuple

from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QComboBox,
    QPushButton,
    QCheckBox,
    QDoubleSpinBox,
    QGridLayout,
    QMessageBox,
    QDialog,
    QDialogButtonBox,
)
from PySide6.QtGui import QPixmap
from PySide6.QtCore import Signal, Qt

from browser.manager import BrowserManager
from capture.capture_manager import CaptureManager
from vision.cropper import crop_slots
from vision.recognizer import recognize_card
from vision.variants_manager import add_variant
from core.logger import log


class ClickableLabel(QLabel):
    clicked = Signal()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


class VisionTab(QWidget):
    """Vision / Recognizer tab.

    - Scan 13 lá từ vùng game (CaptureManager.capture_region).
    - Crop 13 slot theo config.
    - Recognize từng lá với recognize_card.
    - Hiển thị ảnh + code + confidence.
    - Auto-farm variant nếu bật.
    - Click một ô mở popup preview + thêm variant thủ công.
    """

    def __init__(
        self,
        browser_manager: BrowserManager,
        capture_manager: CaptureManager,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.browser_manager = browser_manager
        self.capture_manager = capture_manager

        self.profile_combo = QComboBox()
        self.profile_combo.addItems(["P1", "P2", "P3"])

        self.auto_farm_check = QCheckBox("Auto-farm variant (conf ≥ ngưỡng)")
        self.threshold_spin = QDoubleSpinBox()
        self.threshold_spin.setRange(0.0, 1.0)
        self.threshold_spin.setSingleStep(0.05)
        self.threshold_spin.setValue(0.85)

        self.scan_once_btn = QPushButton("Scan + nhận diện 1 lần")
        self.scan_once_btn.clicked.connect(self.scan_once)

        self.card_labels: List[ClickableLabel] = []
        self.card_code_labels: List[QLabel] = []
        self.card_conf_labels: List[QLabel] = []
        self.card_images_pil: List[Optional["Image.Image"]] = [None] * 13  # type: ignore
        self.card_results: List[Optional[Tuple[str, float]]] = [None] * 13

        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)

        top = QHBoxLayout()
        top.addWidget(QLabel("Profile:"))
        top.addWidget(self.profile_combo)
        top.addWidget(self.scan_once_btn)
        top.addStretch()
        top.addWidget(self.auto_farm_check)
        top.addWidget(QLabel("Ngưỡng conf:"))
        top.addWidget(self.threshold_spin)
        root.addLayout(top)

        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(8)

        idx = 0
        for row in range(3):
            col_count = 5 if row < 2 else 3
            for col in range(col_count):
                if idx >= 13:
                    break
                card_box = QVBoxLayout()
                img_label = ClickableLabel()
                img_label.setFixedSize(80, 110)
                img_label.setStyleSheet(
                    "background-color: #111111; border: 1px solid #444444;"
                )
                img_label.setAlignment(Qt.AlignCenter)

                code_label = QLabel("--")
                conf_label = QLabel("")

                img_label.clicked.connect(lambda _=None, i=idx: self._on_card_clicked(i))

                card_box.addWidget(img_label)
                card_box.addWidget(code_label)
                card_box.addWidget(conf_label)

                container = QWidget()
                container.setLayout(card_box)
                grid.addWidget(container, row, col)

                self.card_labels.append(img_label)
                self.card_code_labels.append(code_label)
                self.card_conf_labels.append(conf_label)
                idx += 1

        root.addLayout(grid)
        root.addStretch()

    def scan_once(self) -> None:
        """Capture vùng game của profile, crop 13 slot và nhận diện từng lá."""
        from PIL.ImageQt import ImageQt  # type: ignore

        pid = self.profile_combo.currentText()
        img = self.capture_manager.capture_region(pid)
        if img is None:
            QMessageBox.warning(self, "Lỗi", f"Không capture được vùng game của {pid}.")
            return

        crops = crop_slots(pid, img)

        self.card_images_pil = [None] * 13
        self.card_results = [None] * 13

        thr = float(self.threshold_spin.value())
        auto_farm = self.auto_farm_check.isChecked()
        auto_added = 0

        for i in range(13):
            card_img = crops[i]
            lbl_img = self.card_labels[i]
            lbl_code = self.card_code_labels[i]
            lbl_conf = self.card_conf_labels[i]

            if card_img is None:
                lbl_img.clear()
                lbl_code.setText("--")
                lbl_conf.setText("")
                continue

            self.card_images_pil[i] = card_img

            qimage = ImageQt(card_img.convert("RGB"))
            pix = QPixmap.fromImage(qimage).scaled(
                lbl_img.width(),
                lbl_img.height(),
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation,
            )
            lbl_img.setPixmap(pix)

            try:
                # recognize_card: (code, conf, is_new_shape)
                code, conf, _ = recognize_card(card_img)
                self.card_results[i] = (code, conf)
                lbl_code.setText(code)
                lbl_conf.setText(f"{conf:.3f}")
            except Exception as e:
                log.error("Lỗi recognize card slot %s: %s", i + 1, e)
                lbl_code.setText("ERR")
                lbl_conf.setText("")
                continue

            if auto_farm and conf >= thr:
                try:
                    ok = add_variant(code, card_img)
                    if ok:
                        auto_added += 1
                except Exception as e:
                    log.error("Auto-farm variant lỗi slot %s: %s", i + 1, e)

        if auto_farm:
            QMessageBox.information(
                self,
                "Auto-farm",
                f"Đã auto-add {auto_added} variant (conf ≥ {thr:.2f}).",
            )

    def _on_card_clicked(self, index: int) -> None:
        if index < 0 or index >= 13:
            return

        result = self.card_results[index]
        img = self.card_images_pil[index]
        if not result or img is None:
            QMessageBox.information(self, "Thông tin", "Lá này chưa có dữ liệu nhận diện.")
            return

        code, conf = result
        thr = float(self.threshold_spin.value())

        from PIL.ImageQt import ImageQt  # type: ignore

        dlg = QDialog(self)
        dlg.setWindowTitle(f"Preview slot {index+1} – {code} ({conf:.3f})")
        v = QVBoxLayout(dlg)

        img_label = QLabel()
        qimage = ImageQt(img.convert("RGB"))
        pix = QPixmap.fromImage(qimage).scaled(
            200,
            260,
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation,
        )
        img_label.setPixmap(pix)
        img_label.setAlignment(Qt.AlignCenter)

        info_label = QLabel(
            f"Code: {code}\nConf: {conf:.3f}\nNgưỡng hiện tại: {thr:.3f}"
        )

        v.addWidget(img_label)
        v.addWidget(info_label)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Close | QDialogButtonBox.Ok, parent=dlg
        )
        buttons.button(QDialogButtonBox.Ok).setText("Thêm variant")
        buttons.button(QDialogButtonBox.Close).setText("Đóng")
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        v.addWidget(buttons)

        if dlg.exec() == QDialog.Accepted:
            try:
                ok = add_variant(code, img)
                if ok:
                    QMessageBox.information(
                        self,
                        "Đã thêm variant",
                        f"Đã thêm variant cho {code} từ slot {index+1}.",
                    )
                else:
                    QMessageBox.warning(
                        self,
                        "Không thêm được",
                        f"Không thể thêm variant cho {code}. Xem log để biết chi tiết.",
                    )
            except Exception as e:
                log.error("Lỗi thêm variant thủ công: %s", e)
                QMessageBox.warning(
                    self,
                    "Lỗi",
                    f"Lỗi khi thêm variant: {e}",
                )
