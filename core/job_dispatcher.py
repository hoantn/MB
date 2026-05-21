import threading
import queue
import traceback


class JobDispatcher:
    """
    Cơ chế đa luồng chuẩn cho Tkinter:
    - Worker thread xử lý nặng (scan, recognize, engine…)
    - UI thread (Tk) chỉ render + update
    - Kết quả worker => queue => UI thread nhận
    """

    def __init__(self, ui_root):
        self.ui_root = ui_root
        self.queue = queue.Queue()
        self._start_poll()

    # ---------------------------------------------------------------
    # Luồng chính Tkinter kiểm tra queue liên tục
    # ---------------------------------------------------------------
    def _start_poll(self):
        """Gọi lại mỗi 40ms để nhận kết quả từ worker"""
        try:
            while True:
                fn, args = self.queue.get_nowait()
                try:
                    fn(*args)      # fn chạy trên UI thread
                except Exception:
                    traceback.print_exc()
        except queue.Empty:
            pass

        # Lập lịch tự gọi lại
        self.ui_root.after(40, self._start_poll)

    # ---------------------------------------------------------------
    # Gọi job trong worker thread
    # ---------------------------------------------------------------
    def run_job(self, worker_fn, *args):
        """
        worker_fn: hàm chạy ở worker thread
        args: đối số truyền sang worker_fn
        """

        thread = threading.Thread(
            target=self._worker_wrapper,
            args=(worker_fn, args),
            daemon=True
        )
        thread.start()

    # ---------------------------------------------------------------
    # Worker thread chạy và gửi kết quả về hàng đợi UI
    # ---------------------------------------------------------------
    def _worker_wrapper(self, worker_fn, args):
        try:
            ui_actions = worker_fn(*args)

            if ui_actions:
                for fn_ui, ui_args in ui_actions:
                    self.queue.put((fn_ui, ui_args))

        except Exception as e:
            traceback.print_exc()
            # Nếu worker lỗi → UI nhận 1 action báo lỗi
            self.queue.put((self._default_error_handler, (e,)))

    # ---------------------------------------------------------------
    # Hàm xử lý lỗi mặc định
    # ---------------------------------------------------------------
    def _default_error_handler(self, e):
        print("Worker failed:", e)
