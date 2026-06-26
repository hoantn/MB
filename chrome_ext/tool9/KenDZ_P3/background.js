const LOG_PREFIX = "[MB WS BG]";
const BRIDGE_BASE = "http://127.0.0.1:9535";
const PROFILE_ID = "P3";  // extension nÃƒÂ y gÃ¡ÂºÂ¯n vÃ¡Â»â€ºi profile P3
const EXTENSION_VERSION = "0.2.1";

// ===== CPU SAFETY SWITCHES =====
// TÃ¡ÂºÂ¯t log toÃƒÂ n bÃ¡Â»â„¢ frame Ã„â€˜Ã¡Â»Æ’ trÃƒÂ¡nh ngÃ¡Â»â€˜n CPU. BÃ¡ÂºÂ­t khi cÃ¡ÂºÂ§n debug.
const DEBUG_ALL_FRAMES = false;
// Log cÃƒÂ¡c cmd quan trÃ¡Â»Âng (nhÃ¡ÂºÂ¹ hÃ†Â¡n rÃ¡ÂºÂ¥t nhiÃ¡Â»Âu so vÃ¡Â»â€ºi log toÃƒÂ n frame)
const DEBUG_IMPORTANT_CMDS = false;

// LÃ†Â°u vÃƒÂ i frame gÃ¡ÂºÂ§n nhÃ¡ÂºÂ¥t Ã„â€˜Ã¡Â»Æ’ debug (giÃ¡Â»Â¯ lÃ¡ÂºÂ¡i, nhÃ†Â°ng khÃƒÂ´ng log liÃƒÂªn tÃ¡Â»Â¥c)
const lastFrames = [];

const WS_STATS_INTERVAL_MS = 60000;
let bgStats = createBgStats();
let latestHookStats = null;
let latestContentStats = null;
let pendingStatsFlushTimer = null;
let lastBackgroundStatsFlushAt = Date.now();

function createBgStats() {
  return {
    framesFromContent: 0,
    framesSend: 0,
    framesRecv: 0,
    hookStatsFromContent: 0,
    contentStatsFromContent: 0,
    parseErrors: 0,
    pythonEvents: 0,
    pythonEventsOk: 0,
    pythonEventsFail: 0,
    commandPolls: 0,
    commandErrors: 0,
    frameCmdCounts: {},
    pythonEventsByKind: {},
    pythonStatus: {},
    commandStatus: {},
  };
}

function bumpMap(map, key) {
  try {
    const k = String(key);
    map[k] = (map[k] || 0) + 1;
  } catch (e) {}
}

function cloneMap(map) {
  return Object.assign({}, map || {});
}

function snapshotBgStats() {
  return {
    framesFromContent: bgStats.framesFromContent,
    framesSend: bgStats.framesSend,
    framesRecv: bgStats.framesRecv,
    hookStatsFromContent: bgStats.hookStatsFromContent,
    contentStatsFromContent: bgStats.contentStatsFromContent,
    parseErrors: bgStats.parseErrors,
    pythonEvents: bgStats.pythonEvents,
    pythonEventsOk: bgStats.pythonEventsOk,
    pythonEventsFail: bgStats.pythonEventsFail,
    commandPolls: bgStats.commandPolls,
    commandErrors: bgStats.commandErrors,
    frameCmdCounts: cloneMap(bgStats.frameCmdCounts),
    pythonEventsByKind: cloneMap(bgStats.pythonEventsByKind),
    pythonStatus: cloneMap(bgStats.pythonStatus),
    commandStatus: cloneMap(bgStats.commandStatus),
    latestHookStats,
    latestContentStats,
  };
}

function flushBackgroundStats(reason = "timer") {
  const reportedAt = Date.now();
  lastBackgroundStatsFlushAt = reportedAt;
  const stats = snapshotBgStats();
  bgStats = createBgStats();
  sendEventToPython({
    kind: "extension_stats",
    reported_at_ms: reportedAt,
    reason,
    stats,
  });
}

function scheduleBackgroundStatsFlush(reason = "scheduled") {
  try {
    if (pendingStatsFlushTimer) return;
    pendingStatsFlushTimer = setTimeout(() => {
      pendingStatsFlushTimer = null;
      flushBackgroundStats(reason);
    }, 500);
  } catch (e) {
    flushBackgroundStats(reason);
  }
}

function maybeFlushBackgroundStats(reason = "poll_loop") {
  try {
    if (Date.now() - lastBackgroundStatsFlushAt >= WS_STATS_INTERVAL_MS) {
      flushBackgroundStats(reason);
    }
  } catch (e) {}
}

setInterval(flushBackgroundStats, WS_STATS_INTERVAL_MS);

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

  // Client gÃ¡Â»Â­i dÃ¡ÂºÂ¡ng:
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

  // Sau khi Ã„â€˜ÃƒÂ£ biÃ¡ÂºÂ¿t URL lÃƒÂ  WS TÃƒÂ i/XÃ¡Â»â€°u, server thÃ†Â°Ã¡Â»Âng trÃ¡ÂºÂ£ object thÃ¡ÂºÂ³ng
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
// ===================== GÃ¡Â»Â¬I EVENT VÃ¡Â»â‚¬ PYTHON =====================

async function sendEventToPython(event) {
  const kind = String((event && event.kind) || "unknown");
  bgStats.pythonEvents += 1;
  bumpMap(bgStats.pythonEventsByKind, kind);
  try {
    const body = JSON.stringify({
      profile_id: PROFILE_ID,
      ...event,
    });
    const resp = await fetch(BRIDGE_BASE + "/mb-ws-event", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body,
      keepalive: true,
    });
    bgStats.pythonEventsOk += 1;
    bumpMap(bgStats.pythonStatus, resp.status);
  } catch (e) {
    bgStats.pythonEventsFail += 1;
    // HTTP bridge chua chay thi thoi
  }
}

// URL WebSocket cÃ¡Â»Â§a game MÃ¡ÂºÂ­u Binh sÃ¡ÂºÂ½ dÃƒÂ¹ng Ã„â€˜Ã¡Â»Æ’ gÃ¡Â»Â­i command
let activeGameWsUrl = null;
// URL WebSocket Ã„â€˜ÃƒÂ£ thÃ¡ÂºÂ¥y traffic TÃƒÂ i/XÃ¡Â»â€°u
const activeTaiXiuWsUrls = new Set();
// ===================== NHÃ¡ÂºÂ¬N FRAME TÃ¡Â»Âª CONTENT SCRIPT =====================

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (!message) return;

  if (message.type === "MB_WS_HOOK_STATS") {
    bgStats.hookStatsFromContent += 1;
    latestHookStats = {
      reported_at_ms: message.reported_at_ms || Date.now(),
      open_sockets: message.open_sockets,
      stats: message.stats || {},
    };
    scheduleBackgroundStatsFlush("hook_stats");
    if (sendResponse) sendResponse({ ok: true });
    return true;
  }

  if (message.type === "MB_WS_CONTENT_STATS") {
    bgStats.contentStatsFromContent += 1;
    latestContentStats = {
      reported_at_ms: message.reported_at_ms || Date.now(),
      stats: message.stats || {},
    };
    scheduleBackgroundStatsFlush("content_stats");
    if (sendResponse) sendResponse({ ok: true });
    return true;
  }

  if (message.type !== "MB_WS_FRAME") return;

  const { direction, url, data } = message;
  bgStats.framesFromContent += 1;
  if (direction === "send") bgStats.framesSend += 1;
  else if (direction === "recv") bgStats.framesRecv += 1;
  const frame = { direction, url, data };
  pushFrame(frame);
  // ===== TÃƒâ‚¬I/XÃ¡Â»Ë†U: forward raw WS vÃ¡Â»Â Python =====
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
  // Ã¢Å¡Â Ã¯Â¸Â TrÃ†Â°Ã¡Â»â€ºc Ã„â€˜ÃƒÂ¢y log mÃ¡Â»Âi SEND/RECV sÃ¡ÂºÂ½ cÃ¡Â»Â±c ngÃ¡Â»â€˜n CPU (Ã„â€˜Ã¡ÂºÂ·c biÃ¡Â»â€¡t khi WS bÃ¡ÂºÂ¯n liÃƒÂªn tÃ¡Â»Â¥c).
  // ChÃ¡Â»â€° log nÃ¡ÂºÂ¿u bÃ¡ÂºÂ­t DEBUG_ALL_FRAMES.
  if (DEBUG_ALL_FRAMES) {
    if (direction === "send") {
      log("SEND", url, data);
    } else {
      log("RECV", url, data);
    }
  }

  // cmd=606 la snapshot thu tu 13 slot do client gui dinh ky. Chi forward
  // frame nay de Python xac nhan thao tac keo, khong forward moi SEND frame.
  if (direction === "send") {
    try {
      let sentPayload = null;
      const parsed = typeof data === "string" ? JSON.parse(data) : data;
      if (Array.isArray(parsed)) {
        for (let i = parsed.length - 1; i >= 0; i -= 1) {
          if (parsed[i] && typeof parsed[i] === "object" && !Array.isArray(parsed[i])) {
            sentPayload = parsed[i];
            break;
          }
        }
      } else if (parsed && typeof parsed === "object") {
        sentPayload = parsed;
      }
      const cards = sentPayload?.cs;
      if (
        sentPayload?.cmd === 606 &&
        Array.isArray(cards) &&
        cards.length === 13 &&
        new Set(cards).size === 13 &&
        cards.every((value) => Number.isInteger(value) && value >= 0 && value <= 51)
      ) {
        sendEventToPython({
          kind: "layout_snapshot",
          sent_at_ms: Date.now(),
          payload: { cmd: 606, cs: cards },
        });
      }
    } catch (e) {
      bgStats.parseErrors += 1;
    }
  }

  // ChÃ¡Â»â€° parse khi lÃƒÂ  frame RECV Ã„â€˜Ã¡Â»Æ’ tÃƒÂ¬m cmd=300/200/202/606/205
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
        if (cmd !== undefined && cmd !== null) bumpMap(bgStats.frameCmdCounts, cmd);

        // ThÃ¡ÂºÂ¥y cmd=300 hoÃ¡ÂºÂ·c cmd=202 Ã¢â€ â€™ gÃƒÂ¡n URL nÃƒÂ y lÃƒÂ m "game socket"
        if (cmd === 300 || cmd === 202) {
          activeGameWsUrl = url;
        }

        if (DEBUG_IMPORTANT_CMDS && (cmd === 200 || cmd === 202 || cmd === 300 || cmd === 600)) {
          log("CMD", cmd, "payload=", payload);
        }

        // 300: danh sÃƒÂ¡ch phÃƒÂ²ng lobby
        if (cmd === 300) {
          sendEventToPython({ kind: "room_list", payload });

        // 200: realtime event trong phÃƒÂ²ng (join/leave/...)
        } else if (cmd === 200) {
          // P3 only: forward JOIN (t=1) + LEAVE (t=2)
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
        // 202: snapshot phÃƒÂ²ng hiÃ¡Â»â€¡n tÃ¡ÂºÂ¡i
        } else if (cmd === 202) {
          sendEventToPython({ kind: "room_snapshot", payload });

		// 850..854: PHÃ¡Â»Å½M (deal / discard / snapshot / eat / other actions)
		} else if (cmd === 850 || cmd === 851 || cmd === 852 || cmd === 853 || cmd === 854) {
		  // GÃ¡Â»Â­i raw payload vÃ¡Â»Â Python (Ã„â€˜Ã¡Â»Æ’ engine/phom tÃ¡Â»Â± parse)
		  sendEventToPython({ kind: "phom_ws", payload });

        // 750: POKER - phÃƒÂ¢n vai Dealer/SB/BB + lpi (vÃƒÂ²ng xoay)
        } else if (cmd === 750) {
          // GÃ¡Â»Â­i raw payload vÃ¡Â»Â Python Ã„â€˜Ã¡Â»Æ’ UI + predictor xÃ¡Â»Â­ lÃƒÂ½
          sendEventToPython({ kind: "poker_roles", payload });

        // 600: bÃƒÂ i (13 lÃƒÂ¡) cÃ¡Â»Â§a ngÃ†Â°Ã¡Â»Âi chÃ†Â¡i (tuÃ¡Â»Â³ game dÃƒÂ¹ng mÃƒÂ£ nÃƒÂ o)
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
      bgStats.parseErrors += 1;
      if (DEBUG_ALL_FRAMES || DEBUG_IMPORTANT_CMDS) log("parse error", e);
    }
  }

  if (sendResponse) sendResponse({ ok: true });
  return true;
});

// ===================== BUILD PAYLOAD GÃ¡Â»Â¬I NGÃ†Â¯Ã¡Â»Â¢C GAME =====================

function buildWsPayload(cmd) {
  const action = cmd.action;
  if (!action) return null;

  if (action === "update_room_list") {
    // YÃƒÂªu cÃ¡ÂºÂ§u server gÃ¡Â»Â­i lÃ¡ÂºÂ¡i danh sÃƒÂ¡ch phÃƒÂ²ng ChinesePoker (gid=4)
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

// ===================== PULL COMMAND TÃ¡Â»Âª PYTHON =====================

async function pollCommandsLoop() {
  try {
    bgStats.commandPolls += 1;
    const body = JSON.stringify({ profile_id: PROFILE_ID });
    const resp = await fetch(BRIDGE_BASE + "/mb-ws-command-pop", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body,
    });

    bumpMap(bgStats.commandStatus, resp.status);

    if (resp.status === 200) {
      const cmd = await resp.json();
      if (DEBUG_IMPORTANT_CMDS) log("POP CMD", cmd);

      const wsPayload = buildWsPayload(cmd);
      if (!wsPayload) {
        // Command khÃƒÂ´ng hÃ¡Â»Â£p lÃ¡Â»â€¡ Ã¢â€ â€™ bÃ¡Â»Â
        setTimeout(pollCommandsLoop, 150);
        return;
      }

      // GÃ¡ÂºÂ¯n payload + URL game socket hiÃ¡Â»â€¡n tÃ¡ÂºÂ¡i (nÃ¡ÂºÂ¿u Ã„â€˜ÃƒÂ£ biÃ¡ÂºÂ¿t)
      cmd.ws_payload = wsPayload;
      if (activeGameWsUrl) {
        cmd.target_ws_url = activeGameWsUrl;
      }

      // GÃ¡Â»Â­i command xuÃ¡Â»â€˜ng tÃ¡ÂºÂ¥t cÃ¡ÂºÂ£ tab (chÃ¡Â»â€° tab cÃƒÂ³ content_script mÃ¡Â»â€ºi nhÃ¡ÂºÂ­n)
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
    bgStats.commandErrors += 1;
    // bridge chÃ†Â°a chÃ¡ÂºÂ¡y / lÃ¡Â»â€”i mÃ¡ÂºÂ¡ng
  } finally {
    maybeFlushBackgroundStats("poll_loop");
    setTimeout(pollCommandsLoop, 150);
  }
}

sendEventToPython({ kind: "extension_ready", version: EXTENSION_VERSION });
flushBackgroundStats("startup");
pollCommandsLoop();
log("service worker started");

// ===================== LÃ¡ÂºÂ¤Y PROXY CREDS TÃ¡Â»Âª PYTHON =====================

function sleepProxyCreds(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function getProxyCredsOnce() {
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

async function getProxyCreds() {
  for (let attempt = 1; attempt <= 8; attempt++) {
    const creds = await getProxyCredsOnce();
    if (creds) {
      return creds;
    }
    await sleepProxyCreds(150);
  }
  return null;
}

// ===================== PROXY AUTH (LÃ¡ÂºÂ¤Y TÃ¡Â»Âª CONFIG QUA BRIDGE) =====================

const MAX_PROXY_AUTH_RETRIES = 3;
const retryMap = new Map();

console.log("MB Proxy Auth", PROFILE_ID, "loaded");

chrome.webRequest.onAuthRequired.addListener(
  (details, callback) => {
    // DÃƒÂ¹ng IIFE async Ã„â€˜Ã¡Â»Æ’ cÃƒÂ³ thÃ¡Â»Æ’ await fetch nhÃ†Â°ng vÃ¡ÂºÂ«n gÃ¡Â»Âi callback theo asyncBlocking
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

        // ChÃ¡Â»â€° xÃ¡Â»Â­ lÃƒÂ½ auth cho proxy (407 tÃ¡Â»Â« proxy), trÃƒÂ¡nh Ã„â€˜Ã¡Â»Â¥ng 401 cÃ¡Â»Â§a website
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
          // KhÃƒÂ´ng lÃ¡ÂºÂ¥y Ã„â€˜Ã†Â°Ã¡Â»Â£c credential Ã¢â€ â€™ Ã„â€˜Ã¡Â»Æ’ Chrome tÃ¡Â»Â± xÃ¡Â»Â­ lÃƒÂ½ (popup, v.v.)
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


