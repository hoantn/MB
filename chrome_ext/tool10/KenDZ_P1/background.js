const LOG_PREFIX = "[MB WS BG]";
const BRIDGE_BASE = "http://127.0.0.1:9536";
const PROFILE_ID = "P1";  // extension nÃ y gáº¯n vá»›i profile P1

// ===== CPU SAFETY SWITCHES =====
// Táº¯t log toÃ n bá»™ frame Ä‘á»ƒ trÃ¡nh ngá»‘n CPU. Báº­t khi cáº§n debug.
const DEBUG_ALL_FRAMES = false;
// Log cÃ¡c cmd quan trá»ng (nháº¹ hÆ¡n ráº¥t nhiá»u so vá»›i log toÃ n frame)
const DEBUG_IMPORTANT_CMDS = false;

// LÆ°u vÃ i frame gáº§n nháº¥t Ä‘á»ƒ debug (giá»¯ láº¡i, nhÆ°ng khÃ´ng log liÃªn tá»¥c)
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

  // Client gá»­i dáº¡ng:
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

  // Sau khi Ä‘Ã£ biáº¿t URL lÃ  WS TÃ i/Xá»‰u, server thÆ°á»ng tráº£ object tháº³ng
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
// ===================== Gá»¬I EVENT Vá»€ PYTHON =====================

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
    // HTTP bridge chÆ°a cháº¡y thÃ¬ thÃ´i
  }
}

// URL WebSocket cá»§a game Máº­u Binh sáº½ dÃ¹ng Ä‘á»ƒ gá»­i command
let activeGameWsUrl = null;
// URL WebSocket Ä‘Ã£ tháº¥y traffic TÃ i/Xá»‰u
const activeTaiXiuWsUrls = new Set();
// ===================== NHáº¬N FRAME Tá»ª CONTENT SCRIPT =====================

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (!message || message.type !== "MB_WS_FRAME") return;

  const { direction, url, data } = message;
  const frame = { direction, url, data };
  pushFrame(frame);
  // ===== TÃ€I/Xá»ˆU: forward raw WS vá» Python =====
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
  // âš ï¸ TrÆ°á»›c Ä‘Ã¢y log má»i SEND/RECV sáº½ cá»±c ngá»‘n CPU (Ä‘áº·c biá»‡t khi WS báº¯n liÃªn tá»¥c).
  // Chá»‰ log náº¿u báº­t DEBUG_ALL_FRAMES.
  if (DEBUG_ALL_FRAMES) {
    if (direction === "send") {
      log("SEND", url, data);
    } else {
      log("RECV", url, data);
    }
  }

  // Chá»‰ parse khi lÃ  frame RECV Ä‘á»ƒ tÃ¬m cmd=300/200/202/606/205
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

        // Tháº¥y cmd=300 hoáº·c cmd=202 â†’ gÃ¡n URL nÃ y lÃ m "game socket"
        if (cmd === 300 || cmd === 202) {
          activeGameWsUrl = url;
        }

        if (DEBUG_IMPORTANT_CMDS && (cmd === 200 || cmd === 202 || cmd === 300 || cmd === 600)) {
          log("CMD", cmd, "payload=", payload);
        }

        // 300: danh sÃ¡ch phÃ²ng lobby
        if (cmd === 300) {
          sendEventToPython({ kind: "room_list", payload });

        // 200: realtime event trong phÃ²ng (join/leave/...)
        } else if (cmd === 200) {
          // P1 only: forward JOIN (t=1) + LEAVE (t=2)
          const t = payload?.t;
          const uid = payload?.p?.uid;

          if ((t === 1 || t === 2) && uid) {
            sendEventToPython({ kind: "room_event", payload });
          }
        // 100: table identity only. Mini-game sockets also emit cmd=100 with id=1.
        } else if (cmd === 100) {
          const isGameSelfInfo = payload?.id === 0 || (activeGameWsUrl && url === activeGameWsUrl);
          if (isGameSelfInfo) {
            sendEventToPython({ kind: "self_info", payload });
          }
        // 205: realtime table balances (uid -> gold)
        } else if (cmd === 205) {
          sendEventToPython({ kind: "room_balance", payload });
        // 202: snapshot phÃ²ng hiá»‡n táº¡i
        } else if (cmd === 202) {
          sendEventToPython({ kind: "room_snapshot", payload });

		// 850..854: PHá»ŽM (deal / discard / snapshot / eat / other actions)
		} else if (cmd === 850 || cmd === 851 || cmd === 852 || cmd === 853 || cmd === 854) {
		  // Gá»­i raw payload vá» Python (Ä‘á»ƒ engine/phom tá»± parse)
		  sendEventToPython({ kind: "phom_ws", payload });

        // 750: POKER - phÃ¢n vai Dealer/SB/BB + lpi (vÃ²ng xoay)
        } else if (cmd === 750) {
          // Gá»­i raw payload vá» Python Ä‘á»ƒ UI + predictor xá»­ lÃ½
          sendEventToPython({ kind: "poker_roles", payload });

        // 600: bÃ i (13 lÃ¡) cá»§a ngÆ°á»i chÆ¡i (tuá»³ game dÃ¹ng mÃ£ nÃ o)
        } else if (cmd === 600 && Array.isArray(payload.cs)) {
          sendEventToPython({
            kind: "cards_snapshot",
            payload: {
              cmd: 600,
              cs: payload.cs,
              lpi: Array.isArray(payload.lpi) ? payload.lpi : [],
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

// ===================== BUILD PAYLOAD Gá»¬I NGÆ¯á»¢C GAME =====================

function buildWsPayload(cmd) {
  const action = cmd.action;
  if (!action) return null;

  if (action === "update_room_list") {
    // YÃªu cáº§u server gá»­i láº¡i danh sÃ¡ch phÃ²ng ChinesePoker (gid=4)
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

// ===================== PULL COMMAND Tá»ª PYTHON =====================

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
        // Command khÃ´ng há»£p lá»‡ â†’ bá»
        setTimeout(pollCommandsLoop, 150);
        return;
      }

      // Gáº¯n payload + URL game socket hiá»‡n táº¡i (náº¿u Ä‘Ã£ biáº¿t)
      cmd.ws_payload = wsPayload;
      if (activeGameWsUrl) {
        cmd.target_ws_url = activeGameWsUrl;
      }

      // Gá»­i command xuá»‘ng táº¥t cáº£ tab (chá»‰ tab cÃ³ content_script má»›i nháº­n)
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
    // bridge chÆ°a cháº¡y / lá»—i máº¡ng
  } finally {
    setTimeout(pollCommandsLoop, 150);
  }
}

pollCommandsLoop();
log("service worker started");

// ===================== Láº¤Y PROXY CREDS Tá»ª PYTHON =====================

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

// ===================== PROXY AUTH (Láº¤Y Tá»ª CONFIG QUA BRIDGE) =====================

const MAX_PROXY_AUTH_RETRIES = 3;
const retryMap = new Map();

console.log("MB Proxy Auth", PROFILE_ID, "loaded");

chrome.webRequest.onAuthRequired.addListener(
  (details, callback) => {
    // DÃ¹ng IIFE async Ä‘á»ƒ cÃ³ thá»ƒ await fetch nhÆ°ng váº«n gá»i callback theo asyncBlocking
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

        // Chá»‰ xá»­ lÃ½ auth cho proxy (407 tá»« proxy), trÃ¡nh Ä‘á»¥ng 401 cá»§a website
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
          // KhÃ´ng láº¥y Ä‘Æ°á»£c credential â†’ Ä‘á»ƒ Chrome tá»± xá»­ lÃ½ (popup, v.v.)
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

