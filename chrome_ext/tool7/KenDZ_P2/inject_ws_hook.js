// inject_ws_hook.js
// Chạy trong page: hook WebSocket và forward frame ra extension,
// đồng thời nhận command (ws_payload) từ extension để gửi vào đúng WS.

(function () {
  const OriginalWebSocket = window.WebSocket;
  if (!OriginalWebSocket) return;

  const sockets = new Set();

  const WS_STATS_INTERVAL_MS = 60000;
  let wsStats = createWsStats();

  function createWsStats() {
    return {
      framesTotal: 0,
      framesSend: 0,
      framesRecv: 0,
      forwardedTotal: 0,
      forwardedSend: 0,
      forwardedRecv: 0,
      parseErrors: 0,
      forwardErrors: 0,
      cmdCounts: {},
    };
  }

  function bumpWsStatMap(map, key) {
    try {
      const k = String(key);
      map[k] = (map[k] || 0) + 1;
    } catch (e) {}
  }

  function extractCmdForStats(payload) {
    try {
      if (payload && typeof payload === "object" && !Array.isArray(payload)) {
        return payload.cmd ?? payload.CMD ?? null;
      }
      if (Array.isArray(payload)) {
        for (let i = payload.length - 1; i >= 0; i -= 1) {
          const item = payload[i];
          if (item && typeof item === "object" && !Array.isArray(item)) {
            return item.cmd ?? item.CMD ?? null;
          }
        }
      }
    } catch (e) {}
    return null;
  }

  function recordWsFrame(direction, payload) {
    wsStats.framesTotal += 1;
    if (direction === "send") wsStats.framesSend += 1;
    else if (direction === "recv") wsStats.framesRecv += 1;
    const cmd = extractCmdForStats(payload);
    if (cmd !== null && cmd !== undefined) bumpWsStatMap(wsStats.cmdCounts, cmd);
  }

  function recordWsForward(direction) {
    wsStats.forwardedTotal += 1;
    if (direction === "send") wsStats.forwardedSend += 1;
    else if (direction === "recv") wsStats.forwardedRecv += 1;
  }

  function flushWsStats() {
    try {
      const stats = Object.assign({}, wsStats, {
        cmdCounts: Object.assign({}, wsStats.cmdCounts),
      });
      window.postMessage(
        {
          source: "mb-ws-hook-stats",
          reported_at_ms: Date.now(),
          open_sockets: sockets.size,
          stats,
        },
        "*"
      );
    } catch (e) {}
    wsStats = createWsStats();
  }

  setInterval(flushWsStats, WS_STATS_INTERVAL_MS);

  function log() {
    try {
      console.log.apply(console, ["[MB WS INJECT]", ...arguments]);
    } catch (e) {}
  }

  function postFrameToContentScript(direction, ws, data) {
    let payload = data;
    try {
      try {
        if (typeof data === "string") {
          payload = JSON.parse(data);
        }
      } catch (e) {
        wsStats.parseErrors += 1;
      }

      recordWsFrame(direction, payload);
      window.postMessage(
        {
          source: "mb-ws-hook",
          direction,
          url: ws.url,
          payload,
        },
        "*"
      );
      recordWsForward(direction);
    } catch (e) {
      wsStats.forwardErrors += 1;
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
