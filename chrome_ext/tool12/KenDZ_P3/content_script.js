// content_script.js
// Inject inject_ws_hook.js và bridge window.postMessage <-> background.

(function () {
  const LOG_PREFIX = "[MB WS CS]";

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

  // 2) Nhận frame từ page → gửi lên background
  window.addEventListener("message", (event) => {
    const data = event.data;
    if (!data || data.source !== "mb-ws-hook") return;

    const { direction, url, payload } = data;
    if (!direction || !url) return;

    try {
      chrome.runtime.sendMessage(
        {
          type: "MB_WS_FRAME",
          direction,
          url,
          data: payload,
        },
        () => {}
      );
    } catch (e) {
      console.warn(LOG_PREFIX, "sendMessage error", e);
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
