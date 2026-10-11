import {validateProposal} from "./proposal.js";
import {requestProposal, testConnection} from "./llm.js";
import {getTabState, applyGroups, groupColor} from "./tabs.js";
import {mountSettings} from "./settings.js";

function siteLabel(url) {
  try {
    const parsed = new URL(url);
    return parsed.hostname.replace(/^www\./, "") || "Blank page";
  } catch {
    return "Local page";
  }
}

function renderGroups(root, groups, snapshot) {
  const byId = new Map(snapshot.map(tab => [tab.id, tab]));
  const container = root.querySelector("#groups");
  container.replaceChildren();
  for (const [index, group] of groups.entries()) {
    const card = document.createElement("article");
    card.className = "group";
    const color = groupColor(group.name, index);
    card.style.setProperty("--group-color", color.hex);
    card.dataset.color = color.name;
    const header = document.createElement("div");
    header.className = "group-header";
    const heading = document.createElement("h3");
    heading.textContent = group.name;
    const count = document.createElement("span");
    count.className = "group-count";
    count.textContent = `${group.tab_ids.length} ${group.tab_ids.length === 1 ? "tab" : "tabs"}`;
    header.append(heading, count);
    const list = document.createElement("ul");
    for (const id of group.tab_ids) {
      const tab = byId.get(id);
      const item = document.createElement("li");
      const title = document.createElement("span");
      title.className = "tab-title";
      title.textContent = tab.title || "Untitled tab";
      title.title = tab.title || "Untitled tab";
      const url = document.createElement("span");
      url.className = "tab-url";
      url.textContent = siteLabel(tab.url);
      const icon = document.createElement("span");
      icon.className = "tab-icon";
      icon.setAttribute("aria-hidden", "true");
      icon.textContent = url.textContent.charAt(0).toUpperCase();
      const text = document.createElement("div");
      text.className = "tab-text";
      text.append(title, url);
      item.append(icon, text);
      list.append(item);
    }
    card.append(header, list);
    container.append(card);
  }
}

// Proposal generation is read-only; browser mutations remain behind explicit approval.
export function mountPanel(root, propose = requestProposal) {
  const listeners = new AbortController();
  const organize = root.querySelector("#organize");
  const approve = root.querySelector("#approve");
  const reject = root.querySelector("#reject");
  const preview = root.querySelector("#preview");
  const status = root.querySelector("#status");
  let pending = null;
  let busy = false;
  let tabCount = 0;

  function reveal(element) {
    element.scrollIntoView({
      block: "start",
      behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "instant" : "smooth",
    });
  }

  function updateOrganize() {
    organize.disabled = busy || root.querySelector("main").dataset.connected !== "true";
    root.querySelector("#organize-label").textContent = busy ? "Working…" :
      (tabCount ? `Organize ${tabCount} ${tabCount === 1 ? "tab" : "tabs"}` : "Organize tabs");
  }

  async function refreshCount() {
    const window = await chrome.windows.getCurrent();
    const state = await getTabState();
    tabCount = state.tabs.filter(tab => tab.window_id === window.id).length;
    updateOrganize();
  }

  root.addEventListener("connectionchange", () => {
    clearPreview();
    if (!busy) status.textContent = "";
    updateOrganize();
  }, {signal: listeners.signal});
  const handleTabsChanged = () => refreshCount().catch(() => {});
  for (const event of [chrome.tabs.onCreated, chrome.tabs.onRemoved, chrome.tabs.onAttached, chrome.tabs.onDetached]) {
    event.addListener(handleTabsChanged);
    listeners.signal.addEventListener("abort", () => event.removeListener(handleTabsChanged));
  }
  refreshCount().catch(() => {});

  function clearPreview() {
    pending = null;
    preview.hidden = true;
    root.querySelector("#groups").replaceChildren();
    approve.disabled = true;
  }

  function setBusy(value) {
    busy = value;
    updateOrganize();
    root.querySelector("#settings-toggle").disabled = busy;
    root.querySelector("#forget-key").disabled = busy;
    root.querySelector("#edit-connection").disabled = busy;
    approve.disabled = busy || pending === null;
    reject.disabled = busy;
    root.querySelector("main").setAttribute("aria-busy", String(busy));
    root.querySelector("#activity").classList.toggle("spinning", busy);
  }

  clearPreview();
  setBusy(false);

  organize.addEventListener("click", async () => {
    clearPreview();
    setBusy(true);
    status.textContent = "Reading this window’s tabs…";
    reveal(status);
    try {
      // Bind to the panel's own window, even if focus moves while generating a proposal.
      const window = await chrome.windows.getCurrent();
      const state = await getTabState();
      const snapshot = state.tabs.filter(tab => tab.window_id === window.id);
      if (!snapshot.length) {
        throw new Error("This window has no tabs to organize.");
      }
      status.textContent = `Preparing groups for ${snapshot.length} tabs…`;
      const proposal = await propose({
        snapshot,
        window_id: window.id,
        signal: listeners.signal,
        onProgress: message => {
          if (!listeners.signal.aborted) status.textContent = message;
        },
      });
      if (listeners.signal.aborted) return;
      const groups = validateProposal(proposal, snapshot);
      pending = {groups, snapshot, window_id: window.id};
      renderGroups(root, groups, snapshot);
      root.querySelector("#summary").textContent = `${snapshot.length} tabs in ${groups.length} groups.`;
      preview.hidden = false;
      status.textContent = "Review the groups below. Your tabs haven’t changed.";
      reveal(preview);
    } catch (error) {
      if (!listeners.signal.aborted) {
        status.textContent = error.message;
        reveal(status);
      }
    } finally {
      if (!listeners.signal.aborted) setBusy(false);
    }
  }, {signal: listeners.signal});

  reject.addEventListener("click", () => {
    clearPreview();
    status.textContent = "Proposal rejected. Your tabs haven’t changed.";
    reveal(status);
  }, {signal: listeners.signal});

  approve.addEventListener("click", async () => {
    if (!pending) return;
    setBusy(true);
    status.textContent = "Applying approved groups…";
    try {
      // Recheck the snapshot before any tab mutations.
      await applyGroups(pending);
      clearPreview();
      status.textContent = "Your tabs are organized.";
    } catch (error) {
      clearPreview();
      status.textContent = error.message;
    } finally {
      reveal(status);
      setBusy(false);
    }
  }, {signal: listeners.signal});

  return {destroy: () => listeners.abort()};
}

// panel.html loads this module after its document has been parsed.
export const panel = mountPanel(document);
await mountSettings(document, testConnection);
