import type { PageInfo, ProposedGroup } from "./types";

function isRecord(value: unknown): value is Record<string, unknown> {
	return typeof value === "object" && value !== null && !Array.isArray(value);
}

function readGroup(value: unknown): ProposedGroup {
	if (
		!isRecord(value) ||
		Object.keys(value).some((key) => !["name", "tab_ids"].includes(key)) ||
		typeof value.name !== "string" ||
		!value.name.trim() ||
		value.name.length > 7 ||
		!Array.isArray(value.tab_ids) ||
		!value.tab_ids.length ||
		!value.tab_ids.every((id): id is string => typeof id === "string")
	) {
		throw new Error("The proposed groups are invalid. Organize again to get a new preview.");
	}
	return { name: value.name, tab_ids: value.tab_ids };
}

// Treat model output as untrusted, including after TypeScript compilation.
export function validateProposal(proposal: unknown, snapshot: PageInfo[]): ProposedGroup[] {
	if (
		!isRecord(proposal) ||
		Object.keys(proposal).some((key) => key !== "groups") ||
		!Array.isArray(proposal.groups) ||
		!proposal.groups.length
	) {
		throw new Error("No groups were returned. Organize again to get a new preview.");
	}

	const groups = proposal.groups.map(readGroup);
	const names = new Set<string>();
	const expectedIds = new Set(snapshot.map((tab) => tab.id));
	const assignedIds = new Set<string>();

	for (const group of groups) {
		const name = group.name.trim().toLowerCase();
		if (names.has(name)) {
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
	return groups.toSorted(
		(a, b) => Number(a.name.trim().toLowerCase() === "other") - Number(b.name.trim().toLowerCase() === "other"),
	);
}
