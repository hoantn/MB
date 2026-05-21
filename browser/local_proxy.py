import base64
import socket
import threading
import select
from typing import Tuple

from core.logger import log


# Cố định port local cho từng profile để dễ debug
LOCAL_PROXY_PORTS = {
    "P1": 19081,
    "P2": 19082,
    "P3": 19083,
}


class AuthHttpForwardProxy(threading.Thread):
    """
    HTTP forward proxy rất đơn giản:
    - Lắng nghe trên 127.0.0.1:local_port
    - Nhận request HTTP từ Chrome
    - Thêm header Proxy-Authorization: Basic user:pass
    - Forward tới upstream proxy (host, port)
    """

    def __init__(
        self,
        listen_host: str,
        listen_port: int,
        upstream_host: str,
        upstream_port: int,
        username: str,
        password: str,
    ) -> None:
        super().__init__(daemon=True)
        self.listen_host = listen_host
        self.listen_port = listen_port
        self.upstream_host = upstream_host
        self.upstream_port = upstream_port
        self.username = username
        self.password = password
        self._stop_event = threading.Event()

    def stop(self) -> None:
        self._stop_event.set()

    # --------------------- core loop ---------------------

    def run(self) -> None:
        try:
            server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server.bind((self.listen_host, self.listen_port))
            server.listen(100)
            log.info(
                "Local proxy started on %s:%s -> upstream %s:%s",
                self.listen_host,
                self.listen_port,
                self.upstream_host,
                self.upstream_port,
            )
        except Exception as e:
            log.error("Không thể start local proxy %s:%s: %s",
                      self.listen_host, self.listen_port, e)
            return

        while not self._stop_event.is_set():
            try:
                client_sock, addr = server.accept()
            except OSError:
                break

            t = threading.Thread(
                target=self._handle_client,
                args=(client_sock, addr),
                daemon=True,
            )
            t.start()

        try:
            server.close()
        except Exception:
            pass

    # --------------------- helpers ---------------------

    def _build_auth_header(self) -> bytes:
        token = f"{self.username}:{self.password}".encode("utf-8")
        b64 = base64.b64encode(token).decode("ascii")
        return f"Proxy-Authorization: Basic {b64}\r\n".encode("ascii")

    def _recv_until_headers_end(self, sock: socket.socket) -> Tuple[bytes, bytes]:
        """
        Đọc từ client tới khi gặp \r\n\r\n (kết thúc header).
        Trả về (header_bytes, phần_data_còn_lại).
        """
        data = b""
        while b"\r\n\r\n" not in data:
            chunk = sock.recv(4096)
            if not chunk:
                break
            data += chunk
            if len(data) > 65536:  # 64KB header là quá đủ
                break
        if b"\r\n\r\n" in data:
            idx = data.index(b"\r\n\r\n") + 4
            return data[:idx], data[idx:]
        return data, b""

    def _patch_headers(self, header_bytes: bytes) -> bytes:
        """
        Thêm Proxy-Authorization vào block header.
        """
        try:
            header_text = header_bytes.decode("iso-8859-1")
        except UnicodeDecodeError:
            return header_bytes

        lines = header_text.split("\r\n")
        if len(lines) <= 1:
            return header_bytes

        # Không thêm nếu đã có sẵn
        lower_lines = [ln.lower() for ln in lines]
        if any(ln.startswith("proxy-authorization:") for ln in lower_lines):
            return header_bytes

        auth_header = self._build_auth_header().decode("ascii").rstrip("\r\n")

        # Chèn ngay sau dòng request đầu tiên
        new_lines = [lines[0], auth_header] + lines[1:]
        patched = "\r\n".join(new_lines)
        return patched.encode("iso-8859-1")

    def _handle_client(self, client_sock: socket.socket, addr) -> None:
        upstream = None
        try:
            upstream = socket.create_connection(
                (self.upstream_host, self.upstream_port), timeout=10
            )

            header_bytes, rest = self._recv_until_headers_end(client_sock)
            if not header_bytes:
                return

            patched_header = self._patch_headers(header_bytes)
            upstream.sendall(patched_header)
            if rest:
                upstream.sendall(rest)

            # Relay 2 chiều
            sockets = [client_sock, upstream]
            while True:
                r, _, _ = select.select(sockets, [], [], 60)
                if not r:
                    break
                if client_sock in r:
                    chunk = client_sock.recv(4096)
                    if not chunk:
                        break
                    upstream.sendall(chunk)
                if upstream in r:
                    chunk = upstream.recv(4096)
                    if not chunk:
                        break
                    client_sock.sendall(chunk)

        except Exception as e:
            log.warning("Local proxy client error from %s: %s", addr, e)
        finally:
            try:
                client_sock.close()
            except Exception:
                pass
            if upstream:
                try:
                    upstream.close()
                except Exception:
                    pass
