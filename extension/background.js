// Python calls these functions through the isolated browser's debugging connection.
// There is no page message listener, so website content cannot request mutations.
chrome.runtime.onInstalled.addListener(() => {});

async function tabGroupState() {
  const targets = await chrome.debugger.getTargets();
  const tabs = (await chrome.tabs.query({})).filter(tab =>
    tab.url !== chrome.runtime.getURL("control.html")
  );
  const targetByTab = new Map(
    targets.filter(target => target.tabId !== undefined).map(target => [target.tabId, target.id])
  );
  const groups = await chrome.tabGroups.query({});
  return {
    tabs: tabs.map(tab => ({
      id: targetByTab.get(tab.id),
      chrome_id: tab.id,
      // Chrome may use the URL as its label for an untitled blank page.
      title: tab.url === "about:blank" && tab.title === "about:blank" ? "" : (tab.title || ""),
      url: tab.url || "",
      window_id: tab.windowId,
      group_id: tab.groupId,
      index: tab.index,
    })),
    groups: groups.map(group => ({
      id: group.id,
      name: group.title || "",
      color: group.color,
      window_id: group.windowId,
    })),
  };
}

async function activeWindowId() {
  const window = await chrome.windows.getLastFocused({windowTypes: ["normal"]});
  if (!window) {
    throw new Error("Focus the Chrome window to organize, then try again.");
  }
  return window.id;
}

async function applyApprovedGroups({groups, snapshot, window_id}) {
  const before = await tabGroupState();
  const byId = new Map(before.tabs.map(tab => [tab.id, tab]));
  const expectedIds = new Set(snapshot.map(tab => tab.id));
  const proposedIds = groups.flatMap(group => group.tab_ids);
  if (new Set(proposedIds).size !== proposedIds.length ||
      proposedIds.length !== expectedIds.size ||
      proposedIds.some(id => !expectedIds.has(id))) {
    throw new Error("Proposal has duplicate, missing, or invented tab IDs.");
  }

  // Validate the entire proposal before the first mutation, including navigation changes.
  for (const expected of snapshot) {
    const current = byId.get(expected.id);
    if (!current || current.url !== expected.url || current.title !== expected.title) {
      throw new Error("Tabs changed after preview. Generate and review a new proposal.");
    }
  }
  const windows = new Set(snapshot.map(tab => byId.get(tab.id).window_id));
  if (windows.size !== 1) {
    throw new Error("This demo only supports one browser window.");
  }
  const windowId = [...windows][0];
  if (window_id != null && windowId !== window_id) {
    throw new Error("The selected Chrome window changed. Generate and review a new proposal.");
  }
  const windowTabs = before.tabs.filter(tab => tab.window_id === windowId);
  if (windowTabs.length !== snapshot.length) {
    throw new Error("Tabs were added after preview. Generate and review a new proposal.");
  }

  const colors = ["blue", "green", "yellow", "purple", "cyan", "orange", "pink", "red"];
  const applied = [];
  let otherGroupId;
  try {
    for (const [index, group] of groups.entries()) {
      const tabIds = group.tab_ids.map(id => byId.get(id).chrome_id);
      const groupId = await chrome.tabs.group({tabIds, createProperties: {windowId}});
      applied.push(group.name);
      await chrome.tabGroups.update(groupId, {
        title: group.name,
        color: group.name.toLowerCase() === "other" ? "grey" : colors[index % colors.length],
        collapsed: false,
      });
      if (group.name.toLowerCase() === "other") {
        otherGroupId = groupId;
      }
    }
    if (otherGroupId !== undefined) {
      await chrome.tabGroups.move(otherGroupId, {index: -1});
    }
  } catch (error) {
    // Browser mutations are not transactional; report partial work instead of claiming success.
    throw new Error(`Application stopped; groups already started: ${applied.join(", ")}. ${error.message}`);
  }
  return await tabGroupState();
}
