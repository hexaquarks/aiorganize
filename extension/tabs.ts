import type { PendingProposal, TabInfo } from "./types";

const GROUP_COLORS: { name: `${chrome.tabGroups.Color}`; hex: string }[] = [
	{ name: "blue", hex: "#1a73e8" },
	{ name: "green", hex: "#188038" },
	{ name: "yellow", hex: "#f9ab00" },
	{ name: "purple", hex: "#a142f4" },
	{ name: "cyan", hex: "#007b83" },
	{ name: "orange", hex: "#e8710a" },
	{ name: "pink", hex: "#d01884" },
	{ name: "red", hex: "#d93025" },
];

// Share the palette so preview colors describe the groups Chrome will actually apply.
export function groupColor(name: string, index: number): { name: `${chrome.tabGroups.Color}`; hex: string } {
	return name.toLowerCase() === "other"
		? { name: "grey", hex: "#737b89" }
		: GROUP_COLORS[index % GROUP_COLORS.length];
}

export async function getTabState() {
	const tabs = (await chrome.tabs.query({})).filter((tab) => !tab.url?.startsWith(chrome.runtime.getURL("")));
	const groups = await chrome.tabGroups.query({});
	return {
		tabs: tabs
			.filter((tab) => tab.id !== undefined)
			.map((tab): TabInfo => ({
				id: `tab-${tab.id}`,
				chrome_id: tab.id!,
				// Chrome may use the URL as its label for an untitled blank page.
				title: tab.url === "about:blank" && tab.title === "about:blank" ? "" : tab.title || "",
				url: tab.url || "",
				window_id: tab.windowId,
				group_id: tab.groupId,
				index: tab.index,
			})),
		groups: groups.map((group) => ({
			id: group.id,
			name: group.title || "",
			color: group.color,
			window_id: group.windowId,
		})),
	};
}

export async function applyGroups({ groups, snapshot, window_id }: PendingProposal) {
	const before = await getTabState();
	const byId = new Map(before.tabs.map((tab) => [tab.id, tab]));
	const expectedIds = new Set(snapshot.map((tab) => tab.id));
	const proposedIds = groups.flatMap((group) => group.tab_ids);
	if (
		new Set(proposedIds).size !== proposedIds.length ||
		proposedIds.length !== expectedIds.size ||
		proposedIds.some((id) => !expectedIds.has(id))
	) {
		throw new Error("Proposal has duplicate, missing, or invented tab IDs.");
	}

	// Validate the entire proposal before the first mutation, including navigation changes.
	for (const expected of snapshot) {
		const current = byId.get(expected.id);
		if (!current || current.url !== expected.url || current.title !== expected.title) {
			throw new Error("Tabs changed after preview. Generate and review a new proposal.");
		}
	}
	const windows = new Set(snapshot.map((tab) => byId.get(tab.id)!.window_id));
	if (windows.size !== 1) {
		throw new Error("Organize one browser window at a time.");
	}
	const windowId = [...windows][0];
	if (window_id != null && windowId !== window_id) {
		throw new Error("The selected Chrome window changed. Generate and review a new proposal.");
	}
	const windowTabs = before.tabs.filter((tab) => tab.window_id === windowId);
	if (windowTabs.length !== snapshot.length) {
		throw new Error("Tabs were added after preview. Generate and review a new proposal.");
	}

	const applied = [];
	let otherGroupId;
	try {
		for (const [index, group] of groups.entries()) {
			const tabIds = group.tab_ids.map((id) => byId.get(id)!.chrome_id);
			if (!tabIds.length) throw new Error("Cannot apply an empty group.");
			const groupId = await chrome.tabs.group({
				tabIds: tabIds as [number, ...number[]],
				createProperties: { windowId },
			});
			applied.push(group.name);
			await chrome.tabGroups.update(groupId, {
				title: group.name,
				color: groupColor(group.name, index).name as chrome.tabGroups.Color,
				collapsed: false,
			});
			if (group.name.toLowerCase() === "other") {
				otherGroupId = groupId;
			}
		}
		if (otherGroupId !== undefined) {
			await chrome.tabGroups.move(otherGroupId, { index: -1 });
		}
	} catch (error) {
		// Browser mutations are not transactional; report partial work instead of claiming success.
		throw new Error(
			`Application stopped; groups already started: ${applied.join(", ")}. ${error instanceof Error ? error.message : "Chrome request failed."}`,
		);
	}
	return await getTabState();
}
