export async function readTab(tab, windowId) {
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

