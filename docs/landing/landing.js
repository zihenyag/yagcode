const BILIBILI_EMBED_URL = "";

function isAllowedBilibiliUrl(value) {
  try {
    const parsed = new URL(value);
    if (parsed.origin !== "https://player.bilibili.com") return false;
    if (parsed.pathname !== "/player.html") return false;
    if (parsed.username !== "" || parsed.password !== "") return false;
    if (parsed.hash !== "") return false;
    const keys = [...parsed.searchParams.keys()];
    if (!keys.every((key) => key === "bvid" || key === "p")) return false;
    const bvid = parsed.searchParams.get("bvid");
    if (bvid === null || !/^BV[0-9A-Za-z]{10}$/.test(bvid)) return false;
    const page = parsed.searchParams.get("p");
    return page === null || /^[1-9][0-9]*$/.test(page);
  } catch {
    return false;
  }
}

function loadVideo() {
  const panel = document.querySelector("[data-video-panel]");
  const status = document.querySelector("[data-video-status]");
  const button = document.querySelector("[data-load-video]");
  if (!(panel instanceof HTMLElement) || !(status instanceof HTMLElement) || !(button instanceof HTMLButtonElement)) return;
  if (!isAllowedBilibiliUrl(BILIBILI_EMBED_URL)) {
    status.textContent = "Bilibili embed URL 尚未发布；本页面保持无第三方 iframe 状态。";
    return;
  }
  if (panel.querySelector("iframe") !== null) return;
  const frame = document.createElement("iframe");
  frame.className = "video-frame";
  frame.title = "YagCode Bilibili 讲解";
  frame.src = BILIBILI_EMBED_URL;
  frame.referrerPolicy = "no-referrer";
  frame.setAttribute("sandbox", "allow-scripts allow-same-origin allow-presentation");
  frame.setAttribute("allowfullscreen", "");
  panel.append(frame);
  button.disabled = true;
  status.textContent = "Bilibili 播放器已按用户同意加载。";
}

document.querySelector("[data-load-video]")?.addEventListener("click", loadVideo);
