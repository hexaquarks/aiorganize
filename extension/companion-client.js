import {readTab} from "./page-reader.js";

const HOST_NAME = "com.aiorganize.companion";

export async function requestProposal(
  {snapshot, window_id, signal, onProgress = () => {}},
  {hostName = HOST_NAME} = {},
) {
  return new Promise((resolve, reject) => {
    const byId = new Map(snapshot.map(tab => [tab.id, tab]));
    let port;
    let finished = false;
    const timer = setTimeout(() => finish(new Error("Grouping timed out. Try Organize again.")), 120000);

    function finish(error, proposal) {
      if (finished) return;
      finished = true;
      clearTimeout(timer);
      signal?.removeEventListener("abort", cancel);
      port?.disconnect();
      if (error) reject(error);
      else resolve(proposal);
    }

    function cancel() {
      finish(new DOMException("Grouping cancelled.", "AbortError"));
    }

    if (signal?.aborted) {
      cancel();
      return;
    }
    signal?.addEventListener("abort", cancel, {once: true});

    try {
      port = chrome.runtime.connectNative(hostName);
      port.onDisconnect.addListener(() => {
        const detail = chrome.runtime.lastError?.message || "The companion disconnected.";
        finish(new Error(`Python companion unavailable. Install or check the companion, then retry. ${detail}`));
      });
      port.onMessage.addListener(async message => {
        if (finished) return;
        try {
          if (message.type === "progress") {
            onProgress("Finding the best groups…");
          } else if (message.type === "read_tabs") {
            onProgress(`Reading ${message.tab_ids.length} pages…`);
            const results = await Promise.all(message.tab_ids.map(async id => {
              const tab = byId.get(id);
              return tab ? await readTab(tab, window_id) : {id, error: "Tab not found."};
            }));
            if (!finished) port.postMessage({type: "tabs_content", request_id: message.request_id, results});
          } else if (message.type === "proposal") {
            finish(null, message.proposal);
          } else if (message.type === "error") {
            finish(new Error(message.message));
          } else {
            finish(new Error("The companion returned an invalid response. Try Organize again."));
          }
        } catch {
          finish(new Error("The companion returned an invalid response. Try Organize again."));
        }
      });
      port.postMessage({type: "organize", window_id, snapshot});
    } catch {
      finish(new Error("Python companion unavailable. Install or check the companion, then retry."));
    }
  });
}
