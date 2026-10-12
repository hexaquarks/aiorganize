// Chrome starts this worker; the panel handles grouping and approval.
chrome.runtime.onInstalled.addListener(() => {
	chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: true }).catch(console.error);
});
