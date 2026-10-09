from pydantic import BaseModel, Field


class TabGroup(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    tab_ids: list[str] = Field(min_length=1)


class GroupingProposal(BaseModel):
    groups: list[TabGroup] = Field(min_length=1)

    def validate_tabs(self, tabs: list[dict[str, str]]) -> None:
        """Require one assignment per input tab before offering to apply anything."""
        proposed_ids = [tab_id for group in self.groups for tab_id in group.tab_ids]
        expected_ids = {tab["id"] for tab in tabs}
        if len(proposed_ids) != len(set(proposed_ids)):
            raise ValueError("A tab appears in more than one group.")
        if set(proposed_ids) != expected_ids:
            raise ValueError("Proposal contains missing or invented tab IDs.")
        names = [group.name.strip().casefold() for group in self.groups]
        if any(not name for name in names) or len(names) != len(set(names)):
            raise ValueError("Group names must be nonempty and unique.")


def print_preview(proposal: GroupingProposal, tabs: list[dict[str, str]]) -> None:
    by_id = {tab["id"]: tab for tab in tabs}
    print("\nProposed browser groups:", flush=True)
    for group in proposal.groups:
        print(f"\n{group.name}")
        for tab_id in group.tab_ids:
            tab = by_id[tab_id]
            print(f"  - {tab['title'] or '(empty title)'} — {tab['url']}")
