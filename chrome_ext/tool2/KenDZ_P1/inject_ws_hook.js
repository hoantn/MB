// inject_ws_hook.js
// Chạy trong page: hook WebSocket và forward frame ra extension,
// đồng thời nhận command (ws_payload) từ extension để gửi vào đúng WS.

(function () {
  const OriginalWebSocket = window.WebSocket;
  if (!OriginalWebSocket) return;

  const sockets = new Set();

  function log() {
    try {
      console.log.apply(console, ["[MB WS INJECT]", ...arguments]);
    } catch (e) {}
  }

  function postFrameToContentScript(direction, ws, data) {
    try {
      let payload = data;
      try {
        payload = JSON.parse(data);
      } catch (e) {
        // không phải JSON, giữ nguyên string
      }

      window.postMessage(
        {
          source: "mb-ws-hook",
          direction,
          url: ws.url,
          payload,
        },
        "*"
      );
    } catch (e) {
      // ignore
    }
  }

  function hookInstance(ws) {
    const origSend = ws.send.bind(ws);

    ws.send = function (data) {
      postFrameToContentScript("send", ws, data);
      return origSend(data);
    };

    ws.addEventListener("message", (event) => {
      postFrameToContentScript("recv", ws, event.data);
    });

    ws.addEventListener("close", () => {
      sockets.delete(ws);
    });
  }

  function WrappedWebSocket(url, protocols) {
    const ws = protocols ? new OriginalWebSocket(url, protocols) : new OriginalWebSocket(url);
    sockets.add(ws);
    hookInstance(ws);
    return ws;
  }

  WrappedWebSocket.prototype = OriginalWebSocket.prototype;
  WrappedWebSocket.CONNECTING = OriginalWebSocket.CONNECTING;
  WrappedWebSocket.OPEN = OriginalWebSocket.OPEN;
  WrappedWebSocket.CLOSING = OriginalWebSocket.CLOSING;
  WrappedWebSocket.CLOSED = OriginalWebSocket.CLOSED;

  window.WebSocket = WrappedWebSocket;

  function pickSocket(targetUrl) {
    let fallback = null;
    for (const ws of sockets) {
      if (ws.readyState !== WebSocket.OPEN) continue;
      if (targetUrl && ws.url === targetUrl) {
        return ws;
      }
      if (!fallback) {
        fallback = ws;
      }
    }
    return fallback;
  }

  // Nhận command từ extension
  window.addEventListener(
    "message",
    (event) => {
      const data = event.data;
      if (!data || data.source !== "mb-ws-command") return;

      const cmd = data.command || {};
      const raw = cmd.ws_payload;
      if (!raw || typeof raw !== "string") {
        log("Command thiếu ws_payload", cmd);
        return;
      }

      const targetUrl = cmd.target_ws_url || null;
      const ws = pickSocket(targetUrl);
      if (!ws) {
        log("Không tìm thấy WebSocket OPEN để gửi", raw);
        return;
      }

      try {
        ws.send(raw);
        log("Đã gửi ws_payload tới", ws.url, "payload:", raw);
      } catch (e) {
        log("Lỗi khi gửi ws_payload", e);
      }
    },
    false
  );

  log("inject_ws_hook installed");
})();
