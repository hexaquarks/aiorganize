import {requestProposal} from "./proposal-client.js";

function siteLabel(url) {
  try {
    const parsed = new URL(url);
    return parsed.hostname.replace(/^www\./, "") || "Blank page";
  } catch {
    return "Local page";
  }
}

function validateProposal(proposal, snapshot) {
  if (!Array.isArray(proposal?.groups) || proposal.groups.length === 0) {
    throw new Error("No groups were returned. Organize again to get a new preview.");
  }
  const names = new Set();
  const expectedIds = new Set(snapshot.map(tab => tab.id));
  const assignedIds = new Set();
  for (const group of proposal.groups) {
    const name = typeof group.name === "string" ? group.name.trim().toLowerCase() : "";
    if (!name || group.name.length > 7 || names.has(name) ||
        !Array.isArray(group.tab_ids) || group.tab_ids.length === 0) {
      throw new Error("The proposed groups are invalid. Organize again to get a new preview.");
    }
    names.add(name);
    for (const id of group.tab_ids) {
      if (!expectedIds.has(id) || assignedIds.has(id)) {
        throw new Error("The proposal has missing, duplicate, or unknown tabs. Organize again.");
      }
      assignedIds.add(id);
    }
  }
  if (assignedIds.size !== expectedIds.size) {
    throw new Error("The proposal has missing tabs. Organize again.");
  }
  return proposal.groups.toSorted((a, b) =>
    Number(a.name.trim().toLowerCase() === "other") - Number(b.name.trim().toLowerCase() === "other")
  );
}

function renderGroups(root, groups, snapshot) {
  const byId = new Map(snapshot.map(tab => [tab.id, tab]));
  const container = root.querySelector("#groups");
  container.replaceChildren();
  const colors = ["#8b9cfb", "#64c6a7", "#e4b868", "#cb91dc", "#6bbecf", "#e58f9f"];
  for (const [index, group] of groups.entries()) {
    const card = document.createElement("article");
    card.className = "group";
    const color = group.name.toLowerCase() === "other" ? "#929aab" : colors[index % colors.length];
    card.style.setProperty("--group-color", color);
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

// Keep proposal generation separate so the browser UI does not own model credentials.
export function mountPanel(root, propose = requestProposal) {
  const listeners = new AbortController();
  const organize = root.querySelector("#organize");
  const approve = root.querySelector("#approve");
  const reject = root.querySelector("#reject");
  const preview = root.querySelector("#preview");
  const status = root.querySelector("#status");
  let pending = null;

  function clearPreview() {
    pending = null;
    preview.hidden = true;
    root.querySelector("#groups").replaceChildren();
    approve.disabled = true;
  }

  function setBusy(busy) {
    organize.disabled = busy;
    approve.disabled = busy || pending === null;
    reject.disabled = busy;
    root.querySelector("main").setAttribute("aria-busy", String(busy));
    root.querySelector("#activity").classList.toggle("spinning", busy);
    root.querySelector("#organize-label").textContent = busy ? "Working…" : "Organize tabs";
  }

  clearPreview();
  setBusy(false);

  organize.addEventListener("click", async () => {
    clearPreview();
    setBusy(true);
    status.textContent = "Reading this window’s tabs…";
    try {
      // Bind to the panel's own window, even if focus moves while generating a proposal.
      const window = await chrome.windows.getCurrent();
      const state = await tabGroupState(true);
      const snapshot = state.tabs.filter(tab => tab.window_id === window.id);
      if (!snapshot.length) {
        throw new Error("This window has no tabs to organize.");
      }
      status.textContent = `Preparing groups for ${snapshot.length} tabs…`;
      const proposal = await propose({snapshot, window_id: window.id, onProgress: message => {
        if (!listeners.signal.aborted) status.textContent = message;
      }});
      if (listeners.signal.aborted) return;
      const groups = validateProposal(proposal, snapshot);
      pending = {groups, snapshot, window_id: window.id};
      renderGroups(root, groups, snapshot);
      root.querySelector("#summary").textContent = `${snapshot.length} tabs in ${groups.length} groups.`;
      preview.hidden = false;
      status.textContent = "Review the groups below. Your tabs haven’t changed.";
    } catch (error) {
      status.textContent = error.message;
    } finally {
      if (!listeners.signal.aborted) setBusy(false);
    }
  }, {signal: listeners.signal});

  reject.addEventListener("click", () => {
    clearPreview();
    status.textContent = "Proposal rejected. Your tabs haven’t changed.";
  }, {signal: listeners.signal});

  approve.addEventListener("click", async () => {
    if (!pending) return;
    setBusy(true);
    status.textContent = "Applying approved groups…";
    try {
      // The existing Chrome helper rechecks the snapshot before any tab mutations.
      await applyApprovedGroups(pending);
      clearPreview();
      status.textContent = "Your tabs are organized.";
    } catch (error) {
      clearPreview();
      status.textContent = error.message;
    } finally {
      setBusy(false);
    }
  }, {signal: listeners.signal});

  return {destroy: () => listeners.abort()};
}
