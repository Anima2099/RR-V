const HOST_NAME = "com.rrv.browser_bridge";
const LINK_MENU_ID = "rrv-send-link";
const LINK_PATTERNS = ["http://*/*", "https://*/*"];
const FAST_PATH_URL = "http://127.0.0.1:47813/rrv/browser/send";
const FAST_PATH_TOKEN = "rrv-bridge-6a4d40f9a5914cd3a80e4fb78558b27f-13f5";
const FAST_PATH_TIMEOUT_MS = 280;

function isHttpUrl(value) {
  try {
    const url = new URL(value);
    return url.protocol === "http:" || url.protocol === "https:";
  } catch (_) {
    return false;
  }
}

function setBadge(text, success) {
  chrome.action.setBadgeText({ text });
  chrome.action.setBadgeBackgroundColor({
    color: success ? "#6F8F78" : "#A56464",
  });
  setTimeout(() => chrome.action.setBadgeText({ text: "" }), 1600);
}

function normalizeCurrentPageUrl(value) {
  if (!isHttpUrl(value)) {
    return value;
  }
  try {
    const url = new URL(value);
    const host = url.hostname.toLowerCase();
    const isYouTube =
      host === "youtube.com" ||
      host.endsWith(".youtube.com") ||
      host === "youtu.be" ||
      host.endsWith(".youtu.be");
    if (!isYouTube) {
      return value;
    }

    if (host === "youtu.be" || host.endsWith(".youtu.be")) {
      url.searchParams.delete("list");
      url.searchParams.delete("index");
      return url.toString();
    }

    if (url.pathname === "/watch" && url.searchParams.get("v")) {
      const videoId = url.searchParams.get("v");
      return `${url.origin}/watch?v=${encodeURIComponent(videoId)}`;
    }

    if (url.pathname.startsWith("/shorts/") || url.pathname.startsWith("/live/")) {
      url.searchParams.delete("list");
      url.searchParams.delete("index");
      return url.toString();
    }
  } catch (_) {
    return value;
  }
  return value;
}

async function tryRunningRrvFastPath(validUrls) {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), FAST_PATH_TIMEOUT_MS);
  try {
    const response = await fetch(FAST_PATH_URL, {
      method: "POST",
      cache: "no-store",
      headers: {
        "Content-Type": "application/json",
        "X-RRV-Bridge-Key": FAST_PATH_TOKEN,
      },
      body: JSON.stringify({ action: "send_urls", urls: validUrls }),
      signal: controller.signal,
    });
    if (!response.ok) {
      return null;
    }
    const payload = await response.json();
    return { reached: true, payload };
  } catch (_) {
    return null;
  } finally {
    clearTimeout(timeoutId);
  }
}

function sendViaNativeMessaging(validUrls) {
  chrome.runtime.sendNativeMessage(
    HOST_NAME,
    { action: "send_urls", urls: validUrls },
    (response) => {
      if (chrome.runtime.lastError) {
        console.warn("RR-V native messaging failed:", chrome.runtime.lastError.message);
        setBadge("!", false);
        return;
      }
      if (!response || !response.ok) {
        console.warn("RR-V rejected URL:", response && response.error);
        setBadge("!", false);
        return;
      }
      setBadge("✓", true);
    },
  );
}

async function sendUrls(urls) {
  const validUrls = urls.filter(isHttpUrl);
  if (!validUrls.length) {
    setBadge("!", false);
    return;
  }

  // RR-V가 이미 실행/트레이 상주 중이면 loopback으로 직접 전달해서
  // Native Host용 RR-V onefile EXE 시작 비용을 완전히 피한다.
  const fastResult = await tryRunningRrvFastPath(validUrls);
  if (fastResult && fastResult.reached) {
    if (!fastResult.payload || !fastResult.payload.ok) {
      console.warn(
        "RR-V fast path rejected URL:",
        fastResult.payload && fastResult.payload.error,
      );
      setBadge("!", false);
      return;
    }
    setBadge("✓", true);
    return;
  }

  // RR-V가 꺼져 있거나 빠른 입구를 열지 못한 경우에는 검증된 Native
  // Messaging 경로로 자동 폴백한다. 이 경로는 필요하면 RR-V를 새로 실행한다.
  sendViaNativeMessaging(validUrls);
}

function resetLinkContextMenu() {
  // DEV13 초기 버전에서 확장 아이콘(action) 컨텍스트에 만들어진 메뉴가
  // Chrome 프로필에 남아 있을 수 있다. update()로 속성만 바꾸지 않고
  // 이 확장이 만든 메뉴를 전부 지운 뒤 웹페이지 링크 전용으로 다시 만든다.
  chrome.contextMenus.removeAll(() => {
    if (chrome.runtime.lastError) {
      console.warn(
        "RR-V context menu cleanup failed:",
        chrome.runtime.lastError.message,
      );
    }

    chrome.contextMenus.create(
      {
        id: LINK_MENU_ID,
        title: "RR-V로 링크 보내기",
        contexts: ["link"],
        targetUrlPatterns: LINK_PATTERNS,
      },
      () => {
        if (chrome.runtime.lastError) {
          console.warn(
            "RR-V link context menu creation failed:",
            chrome.runtime.lastError.message,
          );
        }
      },
    );
  });
}

// 설치/업데이트/브라우저 시작뿐 아니라 unpacked 확장의 Service Worker가
// 다시 올라왔을 때도 오래된 action 메뉴 정의를 확실히 청소한다.
chrome.runtime.onInstalled.addListener(resetLinkContextMenu);
chrome.runtime.onStartup.addListener(resetLinkContextMenu);
resetLinkContextMenu();

chrome.action.onClicked.addListener((tab) => {
  const currentUrl = tab && tab.url ? normalizeCurrentPageUrl(tab.url) : "";
  sendUrls([currentUrl]);
});

chrome.contextMenus.onClicked.addListener((info) => {
  if (info.menuItemId === LINK_MENU_ID && info.linkUrl) {
    sendUrls([info.linkUrl]);
  }
});
