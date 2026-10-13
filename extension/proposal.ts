import type { PageInfo, ProposedGroup } from "./types";
import { isRecord } from "./types";

function readGroup(value: unknown): ProposedGroup {
	const invalidGroupMessage = "The proposed groups are invalid. Organize again to get a new preview.";

	if (!isRecord(value)) {
		throw new Error(invalidGroupMessage);
	}

	const hasUnexpectedFields = Object.keys(value).some((key) => !["name", "tab_ids"].includes(key));

	if (hasUnexpectedFields || typeof value.name !== "string" || !Array.isArray(value.tab_ids)) {
		throw new Error(invalidGroupMessage);
	}

	const name = value.name;
	const tabIds = value.tab_ids;
	const validName = Boolean(name.trim()) && name.length <= 7;

	if (!validName || !tabIds.length || !tabIds.every((id): id is string => typeof id === "string")) {
		throw new Error(invalidGroupMessage);
	}

	return { name, tab_ids: tabIds };
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

	return groups.toSorted((first, second) => {
		const firstIsOther = first.name.trim().toLowerCase() === "other";
		const secondIsOther = second.name.trim().toLowerCase() === "other";

		if (firstIsOther === secondIsOther) {
			return 0;
		}

		return firstIsOther ? 1 : -1;
	});
}
