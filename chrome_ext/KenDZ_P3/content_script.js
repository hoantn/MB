// content_script.js
// Inject inject_ws_hook.js và bridge window.postMessage <-> background.

(function () {
  const LOG_PREFIX = "[MB WS CS]";

  const WS_STATS_INTERVAL_MS = 60000;
  let contentStats = createContentStats();

  function createContentStats() {
    return {
      hookFramesReceived: 0,
      hookStatsReceived: 0,
      backgroundFramesSent: 0,
      backgroundStatsSent: 0,
      sendErrors: 0,
    };
  }

  function sendRuntimeMessage(message) {
    try {
      chrome.runtime.sendMessage(message, () => {});
      return true;
    } catch (e) {
      contentStats.sendErrors += 1;
      return false;
    }
  }

  function flushContentStats() {
    const stats = Object.assign({}, contentStats);
    if (sendRuntimeMessage({
      type: "MB_WS_CONTENT_STATS",
      reported_at_ms: Date.now(),
      stats,
    })) {
      contentStats.backgroundStatsSent += 1;
    }
    contentStats = createContentStats();
  }

  setInterval(flushContentStats, WS_STATS_INTERVAL_MS);

  function log() {
    try {
      console.log.apply(console, [LOG_PREFIX, ...arguments]);
    } catch (e) {}
  }

  // 1) Inject script vào page
  function injectPageScript() {
    try {
      const s = document.createElement("script");
      s.src = chrome.runtime.getURL("inject_ws_hook.js");
      s.type = "text/javascript";
      (document.head || document.documentElement).appendChild(s);
      s.onload = () => s.remove();
      log("inject_ws_hook injected");
    } catch (e) {
      console.warn(LOG_PREFIX, "injectPageScript error", e);
    }
  }

  // 2) Receive frame/stats from page -> background
  window.addEventListener("message", (event) => {
    const data = event.data;
    if (!data) return;

    if (data.source === "mb-ws-hook-stats") {
      contentStats.hookStatsReceived += 1;
      if (sendRuntimeMessage({
        type: "MB_WS_HOOK_STATS",
        reported_at_ms: data.reported_at_ms || Date.now(),
        open_sockets: data.open_sockets,
        stats: data.stats || {},
      })) {
        contentStats.backgroundStatsSent += 1;
      }
      return;
    }

    if (data.source !== "mb-ws-hook") return;

    const { direction, url, payload } = data;
    if (!direction || !url) return;

    contentStats.hookFramesReceived += 1;
    if (sendRuntimeMessage(
      {
        type: "MB_WS_FRAME",
        direction,
        url,
        data: payload,
      }
    )) {
      contentStats.backgroundFramesSent += 1;
    }
  });

  // 3) Nhận command từ background → gửi xuống page
  chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
    if (!msg || msg.type !== "MB_WS_COMMAND") return;

    try {
      window.postMessage(
        {
          source: "mb-ws-command",
          command: msg.command,
        },
        "*"
      );
    } catch (e) {
      console.warn(LOG_PREFIX, "postMessage error", e);
    }

    if (sendResponse) sendResponse({ ok: true });
    return true;
  });

  injectPageScript();
  log("content_script loaded");
})();
