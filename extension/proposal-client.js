const HOST_NAME = "com.aiorganize.companion";

async function readTab(tab, windowId) {
  const unavailable = {id: tab.id, content: "", note: "Page text unavailable; use the title and URL."};
  try {
    const current = await chrome.tabs.get(tab.chrome_id);
    if (current.windowId !== windowId || current.url !== tab.url || current.title !== tab.title) {
      return unavailable;
    }
    const results = await chrome.scripting.executeScript({
      target: {tabId: tab.chrome_id},
      func: () => (document.body?.innerText || "").slice(0, 4000),
    });
    const after = await chrome.tabs.get(tab.chrome_id);
    if (after.windowId !== windowId || after.url !== tab.url || after.title !== tab.title) {
      return unavailable;
    }
    return {id: tab.id, content: results[0]?.result || ""};
  } catch {
    // Chrome protects internal pages and some documents from script injection.
    return unavailable;
  }
}

export async function requestProposal({snapshot, window_id, onProgress = () => {}}, {hostName = HOST_NAME} = {}) {
  return new Promise((resolve, reject) => {
    let port;
    let finished = false;
    const timer = setTimeout(() => finish(new Error("Grouping timed out. Try Organize again.")), 120000);

    function finish(error, proposal) {
      if (finished) return;
      finished = true;
      clearTimeout(timer);
      port?.disconnect();
      if (error) reject(error);
      else resolve(proposal);
    }

    try {
      port = chrome.runtime.connectNative(hostName);
      port.onDisconnect.addListener(() => {
        const detail = chrome.runtime.lastError?.message || "The companion disconnected.";
        finish(new Error(`Python companion unavailable. Install or check the companion, then retry. ${detail}`));
      });
      port.onMessage.addListener(async message => {
        if (finished) return;
        if (message.type === "progress") {
          onProgress("Finding the best groups…");
        } else if (message.type === "read_tabs") {
          onProgress(`Reading ${message.tab_ids.length} pages…`);
          const results = await Promise.all(message.tab_ids.map(async id => {
            const tab = snapshot.find(tab => tab.id === id);
            return tab ? await readTab(tab, window_id) : {id, error: "Tab not found."};
          }));
          if (!finished) port.postMessage({type: "tabs_content", request_id: message.request_id, results});
        } else if (message.type === "read_tab") {
          onProgress("Taking a closer look…");
          const tab = snapshot.find(tab => tab.id === message.tab_id);
          const result = tab ? await readTab(tab, window_id) : {id: message.tab_id, error: "Tab not found."};
          if (!finished) port.postMessage({type: "tab_content", request_id: message.request_id, result});
        } else if (message.type === "proposal") {
          finish(null, message.proposal);
        } else if (message.type === "error") {
          finish(new Error(message.message));
        } else {
          finish(new Error("The companion returned an invalid response. Try Organize again."));
        }
      });
      port.postMessage({type: "organize", window_id, snapshot});
    } catch {
      finish(new Error("Python companion unavailable. Install or check the companion, then retry."));
    }
  });
}
