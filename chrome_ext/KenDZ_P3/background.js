const LOG_PREFIX = "[MB WS BG]";
const BRIDGE_BASE = "http://127.0.0.1:9527";
const PROFILE_ID = "P3";  // extension này gắn với profile P3

// ===== CPU SAFETY SWITCHES =====
// Tắt log toàn bộ frame để tránh ngốn CPU. Bật khi cần debug.
const DEBUG_ALL_FRAMES = false;
// Log các cmd quan trọng (nhẹ hơn rất nhiều so với log toàn frame)
const DEBUG_IMPORTANT_CMDS = false;

// Lưu vài frame gần nhất để debug (giữ lại, nhưng không log liên tục)
const lastFrames = [];

function pushFrame(frame) {
  try {
    lastFrames.push({
      ts: Date.now(),
      direction: frame.direction,
      url: frame.url,
      data: frame.data,
    });
    if (lastFrames.length > 200) lastFrames.shift();
  } catch (e) {}
}

function log() {
  try {
    console.log.apply(console, [LOG_PREFIX, ...arguments]);
  } catch (e) {}
}
function tryExtractTaiXiuFrame(url, data) {
  let parsed = data;

  try {
    if (typeof parsed === "string") {
      parsed = JSON.parse(parsed);
    }
  } catch (e) {}

  // Client gửi dạng:
  // ["6","MiniGame","taixiuPlugin",{"cmd":1005}]
  if (Array.isArray(parsed) && parsed.length >= 4) {
    const zone = parsed[1];
    const plugin = parsed[2];
    const payload = parsed[3];

    if (zone === "MiniGame" && plugin === "taixiuPlugin" && payload && typeof payload === "object") {
      activeTaiXiuWsUrls.add(url);
      return {
        frame: parsed,
        payload: payload,
      };
    }
  }

  // Sau khi đã biết URL là WS Tài/Xỉu, server thường trả object thẳng
  if (activeTaiXiuWsUrls.has(url)) {
    if (parsed && typeof parsed === "object") {
      return {
        frame: parsed,
        payload: parsed,
      };
    }
  }

  return null;
}
// ===================== GỬI EVENT VỀ PYTHON =====================

async function sendEventToPython(event) {
  try {
    const body = JSON.stringify({
      profile_id: PROFILE_ID,
      ...event,
    });
    await fetch(BRIDGE_BASE + "/mb-ws-event", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body,
      keepalive: true,
    });
  } catch (e) {
    // HTTP bridge chưa chạy thì thôi
  }
}

// URL WebSocket của game Mậu Binh sẽ dùng để gửi command
let activeGameWsUrl = null;
// URL WebSocket đã thấy traffic Tài/Xỉu
const activeTaiXiuWsUrls = new Set();
// ===================== NHẬN FRAME TỪ CONTENT SCRIPT =====================

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (!message || message.type !== "MB_WS_FRAME") return;

  const { direction, url, data } = message;
  const frame = { direction, url, data };
  pushFrame(frame);
  // ===== TÀI/XỈU: forward raw WS về Python =====
  try {
    const txInfo = tryExtractTaiXiuFrame(url, data);
    if (txInfo) {
      sendEventToPython({
        kind: "taixiu_ws",
        direction,
        url,
        payload: txInfo.payload,
        frame: txInfo.frame,
      });
    }
  } catch (e) {}
  // ⚠️ Trước đây log mọi SEND/RECV sẽ cực ngốn CPU (đặc biệt khi WS bắn liên tục).
  // Chỉ log nếu bật DEBUG_ALL_FRAMES.
  if (DEBUG_ALL_FRAMES) {
    if (direction === "send") {
      log("SEND", url, data);
    } else {
      log("RECV", url, data);
    }
  }

  // Chỉ parse khi là frame RECV để tìm cmd=300/200/202/606/205
  if (direction === "recv") {
    try {
      let payload = null;

      if (Array.isArray(data) && data.length >= 2 && typeof data[1] === "object") {
        // [x, {...}]
        payload = data[1];
      } else if (Array.isArray(data) && data.length >= 4 && typeof data[3] === "object") {
        // [x, "Simms", "...", {...}]
        payload = data[3];
      } else if (typeof data === "string") {
        const parsed = JSON.parse(data);
        if (Array.isArray(parsed)) {
          if (parsed.length >= 2 && typeof parsed[1] === "object") {
            payload = parsed[1];
          } else if (parsed.length >= 4 && typeof parsed[3] === "object") {
            payload = parsed[3];
          }
        }
      }

      if (payload && typeof payload === "object") {
        const cmd = payload.cmd;

        // Thấy cmd=300 hoặc cmd=202 → gán URL này làm "game socket"
        if (cmd === 300 || cmd === 202) {
          activeGameWsUrl = url;
        }

        if (DEBUG_IMPORTANT_CMDS && (cmd === 200 || cmd === 202 || cmd === 300 || cmd === 600)) {
          log("CMD", cmd, "payload=", payload);
        }

        // 300: danh sách phòng lobby
        if (cmd === 300) {
          sendEventToPython({ kind: "room_list", payload });

        // 200: realtime event trong phòng (join/leave/...)
        } else if (cmd === 200) {
          // P3 only: forward JOIN (t=1) + LEAVE (t=2)
          const t = payload?.t;
          const uid = payload?.p?.uid;

          if ((t === 1 || t === 2) && uid) {
            sendEventToPython({ kind: "room_event", payload });
          }
        // 100: thông tin chính mình (uid, dn, gold...)
        } else if (cmd === 100) {
          sendEventToPython({ kind: "self_info", payload });
        // 202: snapshot phòng hiện tại
        } else if (cmd === 202) {
          sendEventToPython({ kind: "room_snapshot", payload });

		// 850..854: PHỎM (deal / discard / snapshot / eat / other actions)
		} else if (cmd === 850 || cmd === 851 || cmd === 852 || cmd === 853 || cmd === 854) {
		  // Gửi raw payload về Python (để engine/phom tự parse)
		  sendEventToPython({ kind: "phom_ws", payload });

        // 750: POKER - phân vai Dealer/SB/BB + lpi (vòng xoay)
        } else if (cmd === 750) {
          // Gửi raw payload về Python để UI + predictor xử lý
          sendEventToPython({ kind: "poker_roles", payload });

        // 600: bài (13 lá) của người chơi (tuỳ game dùng mã nào)
        } else if (cmd === 600 && Array.isArray(payload.cs)) {
          sendEventToPython({
            kind: "cards_snapshot",
            payload: {
              cmd: 600,
              cs: payload.cs,
            },
          });
        }
      }
    } catch (e) {
      if (DEBUG_ALL_FRAMES || DEBUG_IMPORTANT_CMDS) log("parse error", e);
    }
  }

  if (sendResponse) sendResponse({ ok: true });
  return true;
});

// ===================== BUILD PAYLOAD GỬI NGƯỢC GAME =====================

function buildWsPayload(cmd) {
  const action = cmd.action;
  if (!action) return null;

  if (action === "update_room_list") {
    // Yêu cầu server gửi lại danh sách phòng ChinesePoker (gid=4)
    const payload = [6, "Simms", "channelPlugin", { cmd: 300, aid: "1", gid: 4 }];
    return JSON.stringify(payload);
  }

  if (action === "join_room") {
    const rid = Number(cmd.room_id);
    if (!rid || !Number.isFinite(rid)) return null;
    const payload = [3, "Simms", rid, ""];
    return JSON.stringify(payload);
  }

  if (action === "leave_room") {
    const payload = [4, "Simms", -1];
    return JSON.stringify(payload);
  }

  return null;
}

// ===================== PULL COMMAND TỪ PYTHON =====================

async function pollCommandsLoop() {
  try {
    const body = JSON.stringify({ profile_id: PROFILE_ID });
    const resp = await fetch(BRIDGE_BASE + "/mb-ws-command-pop", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body,
    });

    if (resp.status === 200) {
      const cmd = await resp.json();
      if (DEBUG_IMPORTANT_CMDS) log("POP CMD", cmd);

      const wsPayload = buildWsPayload(cmd);
      if (!wsPayload) {
        // Command không hợp lệ → bỏ
        setTimeout(pollCommandsLoop, 150);
        return;
      }

      // Gắn payload + URL game socket hiện tại (nếu đã biết)
      cmd.ws_payload = wsPayload;
      if (activeGameWsUrl) {
        cmd.target_ws_url = activeGameWsUrl;
      }

      // Gửi command xuống tất cả tab (chỉ tab có content_script mới nhận)
      chrome.tabs.query({}, (tabs) => {
        for (const tab of tabs) {
          if (!tab.id) continue;
          try {
            chrome.tabs.sendMessage(
              tab.id,
              { type: "MB_WS_COMMAND", command: cmd },
              () => {}
            );
          } catch (e) {
            // ignore
          }
        }
      });
    }
  } catch (e) {
    // bridge chưa chạy / lỗi mạng
  } finally {
    setTimeout(pollCommandsLoop, 150);
  }
}

pollCommandsLoop();
log("service worker started");

// ===================== LẤY PROXY CREDS TỪ PYTHON =====================

async function getProxyCreds() {
  try {
    const resp = await fetch(BRIDGE_BASE + "/mb-proxy-creds", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ profile_id: PROFILE_ID }),
    });

    if (resp.status !== 200) {
      return null;
    }

    const data = await resp.json();
    if (!data || !data.username) {
      return null;
    }

    return {
      username: data.username,
      password: data.password || "",
    };
  } catch (e) {
    return null;
  }
}

// ===================== PROXY AUTH (LẤY TỪ CONFIG QUA BRIDGE) =====================

const MAX_PROXY_AUTH_RETRIES = 3;
const retryMap = new Map();

console.log("MB Proxy Auth", PROFILE_ID, "loaded");

chrome.webRequest.onAuthRequired.addListener(
  (details, callback) => {
    // Dùng IIFE async để có thể await fetch nhưng vẫn gọi callback theo asyncBlocking
    (async () => {
      try {
        console.log("MB Proxy Auth", PROFILE_ID, "onAuthRequired", {
          url: details.url,
          isProxy: details.isProxy,
          statusCode: details.statusCode,
          method: details.method,
          requestId: details.requestId,
          challenger: details.challenger,
        });

        // Chỉ xử lý auth cho proxy (407 từ proxy), tránh đụng 401 của website
        if (!details.isProxy) {
          callback({});
          return;
        }

        const key =
          details.requestId ||
          (details.challenger
            ? details.challenger.host + ":" + details.challenger.port
            : "unknown");

        const current = retryMap.get(key) || 0;
        if (current >= MAX_PROXY_AUTH_RETRIES) {
          console.warn("MB Proxy Auth", PROFILE_ID, "max retries reached for", key);
          callback({});
          return;
        }
        retryMap.set(key, current + 1);

        const creds = await getProxyCreds();
        if (!creds) {
          // Không lấy được credential → để Chrome tự xử lý (popup, v.v.)
          callback({});
          return;
        }

        callback({
          authCredentials: {
            username: creds.username,
            password: creds.password,
          },
        });
      } catch (e) {
        console.error("MB Proxy Auth", PROFILE_ID, "error in onAuthRequired", e);
        callback({});
      }
    })();
  },
  { urls: ["<all_urls>"] },
  ["asyncBlocking"]
);
