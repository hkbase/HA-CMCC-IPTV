"use strict";

const state = {
  data: null,
  items: [],
  filtered: [],
  reviews: {},
  currentId: null,
  saveTimer: null,
};

const elements = {};
let toastTimer = null;

function $(id) {
  return document.getElementById(id);
}

function currentItem() {
  return state.items.find((item) => item.id === state.currentId) || null;
}

function reviewFor(item) {
  return state.reviews[item.url] || null;
}

function decisionClass(decision) {
  if (decision === "一致") return "match";
  if (decision === "不一致") return "mismatch";
  if (decision === "无法确定") return "uncertain";
  return "pending";
}

function showToast(message) {
  elements.toast.textContent = message;
  elements.toast.classList.add("visible");
  window.clearTimeout(toastTimer);
  toastTimer = window.setTimeout(() => elements.toast.classList.remove("visible"), 1800);
}

function setImage(image, link, empty, url) {
  if (url) {
    image.src = url;
    image.hidden = false;
    link.href = url;
    link.removeAttribute("aria-disabled");
    empty.classList.remove("visible");
  } else {
    image.removeAttribute("src");
    image.hidden = true;
    link.removeAttribute("href");
    link.setAttribute("aria-disabled", "true");
    empty.classList.add("visible");
  }
}

function saveLocal() {
  try {
    localStorage.setItem(
      `iptv-logo-reviewer:v1:${state.data.datasetId}`,
      JSON.stringify(state.reviews),
    );
  } catch (error) {
    console.warn("浏览器本地备份失败", error);
  }
}

function currentReviews() {
  const allowed = new Set(state.items.map((item) => item.url));
  return Object.fromEntries(
    Object.entries(state.reviews).filter(
      ([url, review]) => allowed.has(url) && review && review.decision,
    ),
  );
}

function scheduleSave() {
  saveLocal();
  elements.saveStatus.textContent = "保存中";
  elements.saveStatus.classList.remove("error");
  window.clearTimeout(state.saveTimer);
  state.saveTimer = window.setTimeout(saveServer, 250);
}

async function saveServer() {
  try {
    const response = await fetch("/api/reviews", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ reviews: currentReviews() }),
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || "保存失败");
    elements.saveStatus.textContent = "已保存到报告";
    elements.saveStatus.title = payload.csv || "";
  } catch (error) {
    elements.saveStatus.textContent = "仅保存在浏览器";
    elements.saveStatus.classList.add("error");
    console.error(error);
  }
}

function updateStats() {
  const reviews = state.items.map(reviewFor).filter(Boolean);
  const count = (decision) => reviews.filter((review) => review.decision === decision).length;
  elements.reviewedCount.textContent = String(reviews.length);
  elements.matchCount.textContent = String(count("一致"));
  elements.mismatchCount.textContent = String(count("不一致"));
  elements.uncertainCount.textContent = String(count("无法确定"));
}

function matchesFilters(item) {
  const query = elements.searchInput.value.trim().toLocaleLowerCase("zh-CN");
  if (query && !`${item.name} ${item.group} ${item.url}`.toLocaleLowerCase("zh-CN").includes(query)) {
    return false;
  }
  const decision = reviewFor(item)?.decision || "pending";
  if (elements.decisionFilter.value !== "all" && elements.decisionFilter.value !== decision) {
    return false;
  }
  const hasFrame = Boolean(item.frame_url);
  if (elements.captureFilter.value === "available" && !hasFrame) return false;
  if (elements.captureFilter.value === "missing" && hasFrame) return false;
  return true;
}

function renderList() {
  state.filtered = state.items.filter(matchesFilters);
  elements.visibleCount.textContent = `${state.filtered.length} 条`;
  elements.channelList.replaceChildren();
  const fragment = document.createDocumentFragment();
  for (const item of state.filtered) {
    const review = reviewFor(item);
    const row = document.createElement("button");
    row.type = "button";
    row.className = `channel-row${item.id === state.currentId ? " selected" : ""}`;
    row.dataset.id = item.id;
    row.setAttribute("role", "option");
    row.setAttribute("aria-selected", item.id === state.currentId ? "true" : "false");

    const text = document.createElement("span");
    const primary = document.createElement("span");
    primary.className = "channel-primary";
    primary.textContent = item.name;
    const secondary = document.createElement("span");
    secondary.className = "channel-secondary";
    secondary.textContent = `${item.group} · 源 ${item.source_no} · ${item.frame_url ? "有画面" : "无画面"}`;
    text.append(primary, secondary);

    const status = document.createElement("span");
    status.className = `row-status ${decisionClass(review?.decision)}`;
    status.title = review?.decision || "待复核";
    row.append(text, status);
    row.addEventListener("click", () => selectItem(item.id));
    fragment.append(row);
  }
  elements.channelList.append(fragment);
}

function renderCurrent() {
  const item = currentItem();
  if (!item) {
    elements.channelName.textContent = state.filtered.length ? "选择频道" : "没有符合条件的频道";
    elements.channelMeta.textContent = "";
    return;
  }
  const review = reviewFor(item);
  const decision = review?.decision || "待复核";
  const cssClass = decisionClass(decision);
  elements.channelName.textContent = item.name;
  elements.channelMeta.textContent = `${item.group} · 源 ${item.source_no} · 捕获 ${item.capture_index || "-"}`;
  elements.decisionBadge.textContent = decision;
  elements.decisionBadge.className = `decision-badge ${cssClass}`;
  elements.captureStatus.textContent = item.frame_url ? "已捕获" : item.capture_status || "无画面";
  elements.sourceUrl.textContent = item.url;
  elements.noteInput.value = review?.note || "";
  elements.noteInput.disabled = !review;
  for (const button of elements.decisionButtons) {
    button.classList.toggle("active", button.dataset.decision === review?.decision);
    button.setAttribute("aria-pressed", button.dataset.decision === review?.decision ? "true" : "false");
  }
  setImage(elements.logoImage, elements.logoLink, elements.logoEmpty, item.logo_url);
  setImage(elements.cropImage, elements.cropLink, elements.cropEmpty, item.crop_url);
  setImage(elements.frameImage, elements.frameLink, elements.frameEmpty, item.frame_url);
}

function selectItem(id) {
  state.currentId = id;
  renderList();
  renderCurrent();
  const selected = elements.channelList.querySelector(".channel-row.selected");
  selected?.scrollIntoView({ block: "nearest" });
}

function navigate(step) {
  if (!state.filtered.length) return;
  let index = state.filtered.findIndex((item) => item.id === state.currentId);
  if (index < 0) index = step > 0 ? -1 : 0;
  const target = state.filtered[(index + step + state.filtered.length) % state.filtered.length];
  selectItem(target.id);
}

function selectNextPending() {
  if (!state.filtered.length) return;
  const start = state.filtered.findIndex((item) => item.id === state.currentId);
  for (let offset = 1; offset <= state.filtered.length; offset += 1) {
    const item = state.filtered[(start + offset) % state.filtered.length];
    if (!reviewFor(item)) {
      selectItem(item.id);
      return;
    }
  }
  showToast("当前列表已全部复核");
}

function setDecision(decision) {
  const item = currentItem();
  if (!item) return;
  state.reviews[item.url] = {
    decision,
    note: state.reviews[item.url]?.note || "",
  };
  scheduleSave();
  updateStats();
  renderList();
  renderCurrent();
  if (elements.autoAdvance.checked) selectNextPending();
}

function clearDecision() {
  const item = currentItem();
  if (!item || !state.reviews[item.url]) return;
  delete state.reviews[item.url];
  scheduleSave();
  updateStats();
  renderList();
  renderCurrent();
}

function updateNote() {
  const item = currentItem();
  const review = item ? state.reviews[item.url] : null;
  if (!item || !review) return;
  review.note = elements.noteInput.value.slice(0, 500);
  scheduleSave();
}

function csvCell(value) {
  return `"${String(value ?? "").replaceAll('"', '""')}"`;
}

function exportCsv() {
  const fields = [
    "name",
    "group",
    "source_no",
    "url",
    "decision",
    "note",
    "capture_status",
    "capture_index",
    "logo_path",
    "crop_path",
    "frame_path",
  ];
  const lines = [fields.map(csvCell).join(",")];
  for (const item of state.items) {
    const review = reviewFor(item) || {};
    const row = { ...item, decision: review.decision || "", note: review.note || "" };
    lines.push(fields.map((field) => csvCell(row[field])).join(","));
  }
  const blob = new Blob(["\ufeff", lines.join("\r\n"), "\r\n"], { type: "text/csv;charset=utf-8" });
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = "iptv-logo-frame-reviews.csv";
  link.click();
  URL.revokeObjectURL(link.href);
}

async function copyUrl() {
  const item = currentItem();
  if (!item) return;
  try {
    await navigator.clipboard.writeText(item.url);
    showToast("URL 已复制");
  } catch {
    showToast("复制失败");
  }
}

function bindElements() {
  Object.assign(elements, {
    datasetSummary: $("dataset-summary"),
    reviewedCount: $("reviewed-count"),
    matchCount: $("match-count"),
    mismatchCount: $("mismatch-count"),
    uncertainCount: $("uncertain-count"),
    saveStatus: $("save-status"),
    searchInput: $("search-input"),
    decisionFilter: $("decision-filter"),
    captureFilter: $("capture-filter"),
    visibleCount: $("visible-count"),
    channelList: $("channel-list"),
    channelName: $("channel-name"),
    channelMeta: $("channel-meta"),
    decisionBadge: $("decision-badge"),
    captureStatus: $("capture-status"),
    sourceUrl: $("source-url"),
    noteInput: $("note-input"),
    autoAdvance: $("auto-advance"),
    logoImage: $("logo-image"),
    logoLink: $("logo-link"),
    logoEmpty: $("logo-empty"),
    cropImage: $("crop-image"),
    cropLink: $("crop-link"),
    cropEmpty: $("crop-empty"),
    frameImage: $("frame-image"),
    frameLink: $("frame-link"),
    frameEmpty: $("frame-empty"),
    toast: $("toast"),
    decisionButtons: [...document.querySelectorAll("[data-decision]")],
  });

  elements.searchInput.addEventListener("input", renderList);
  elements.decisionFilter.addEventListener("change", renderList);
  elements.captureFilter.addEventListener("change", renderList);
  $("previous-button").addEventListener("click", () => navigate(-1));
  $("next-button").addEventListener("click", () => navigate(1));
  $("next-pending-button").addEventListener("click", selectNextPending);
  $("clear-button").addEventListener("click", clearDecision);
  $("copy-button").addEventListener("click", copyUrl);
  $("export-button").addEventListener("click", exportCsv);
  elements.noteInput.addEventListener("input", updateNote);
  for (const button of elements.decisionButtons) {
    button.addEventListener("click", () => setDecision(button.dataset.decision));
  }
  window.addEventListener("keydown", (event) => {
    if (event.target instanceof HTMLInputElement || event.target instanceof HTMLSelectElement) return;
    if (event.key === "ArrowLeft") navigate(-1);
    if (event.key === "ArrowRight") navigate(1);
    if (event.key === "1") setDecision("一致");
    if (event.key === "2") setDecision("不一致");
    if (event.key === "3") setDecision("无法确定");
  });
}

async function init() {
  bindElements();
  try {
    const response = await fetch("/api/data", { cache: "no-store" });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "载入失败");
    let localReviews = {};
    try {
      const storageKey = `iptv-logo-reviewer:v1:${data.datasetId}`;
      localReviews = JSON.parse(localStorage.getItem(storageKey) || "{}");
    } catch {
      localReviews = {};
    }
    state.data = data;
    state.items = data.items;
    state.reviews = { ...data.reviews, ...localReviews };
    elements.datasetSummary.textContent = `${data.items.length} 条源 · ${data.report.split(/[\\/]/).pop()}`;
    elements.datasetSummary.title = `${data.playlist}\n${data.report}`;
    elements.saveStatus.textContent = Object.keys(data.reviews).length ? "已载入复核记录" : "尚未复核";
    updateStats();
    renderList();
    const first = state.filtered.find((item) => !reviewFor(item)) || state.filtered[0];
    if (first) selectItem(first.id);
  } catch (error) {
    elements.datasetSummary.textContent = "载入失败";
    elements.channelName.textContent = error.message;
    elements.saveStatus.textContent = "服务异常";
    elements.saveStatus.classList.add("error");
    console.error(error);
  }
}

document.addEventListener("DOMContentLoaded", init);
