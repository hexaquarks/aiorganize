// Both connection tests and organization require a valid schema and complete tab coverage.
export function validateProposal(proposal, snapshot) {
  if (!proposal || Object.keys(proposal).some(key => key !== "groups") ||
      !Array.isArray(proposal?.groups) || proposal.groups.length === 0) {
    throw new Error("No groups were returned. Organize again to get a new preview.");
  }
  const names = new Set();
  const expectedIds = new Set(snapshot.map(tab => tab.id));
  const assignedIds = new Set();
  for (const group of proposal.groups) {
    if (!group || Object.keys(group).some(key => !["name", "tab_ids"].includes(key))) {
      throw new Error("The proposed groups are invalid. Organize again to get a new preview.");
    }
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

