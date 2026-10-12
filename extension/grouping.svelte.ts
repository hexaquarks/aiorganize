import { requestProposal } from "./llm";
import { validateProposal } from "./proposal";
import { applyGroups, getTabState } from "./tabs";
import { getQdrantSettings, getSettings } from "./settings";
import { GroupingVectorStore } from "./vector-store";
import type { ApprovedGroup } from "./vector-store";
import type { GroupingExample, PageInfo, PendingProposal } from "./types";

export class GroupingState {
	pending = $state<PendingProposal | null>(null);
	busy = $state(false);
	tabCount = $state(0);
	status = $state("");
	savedGroupingsStatus = $state("");
	retrievalStatus = $state("");
	canRetrySave = $state(false);

	private controller = new AbortController();
	private groupsToSave: ApprovedGroup[] | null = null;

	async refreshCount() {
		const window = await chrome.windows.getCurrent();
		const state = await getTabState();

		this.tabCount = state.tabs.filter((tab) => tab.window_id === window.id).length;
	}

	async organize() {
		if (this.busy) {
			return;
		}

		this.pending = null;
		this.groupsToSave = null;
		this.savedGroupingsStatus = "";
		this.retrievalStatus = "";
		this.canRetrySave = false;
		this.busy = true;
		this.status = "Reading this window’s tabs…";

		try {
			const window = await chrome.windows.getCurrent();
			const state = await getTabState();
			const snapshot = state.tabs.filter((tab) => tab.window_id === window.id);

			if (!snapshot.length) {
				throw new Error("This window has no tabs to organize.");
			}

			if (window.id === undefined) {
				throw new Error("The selected Chrome window is unavailable.");
			}

			const savedGroupings = await this.retrieveGroupings(snapshot);

			const proposal = await requestProposal({
				snapshot,
				savedGroupings,
				signal: this.controller.signal,
				onProgress: (message) => {
					this.status = message;
				},
			});

			if (this.controller.signal.aborted) {
				return;
			}

			this.pending = { groups: validateProposal(proposal, snapshot), snapshot, window_id: window.id };
			this.status = "Review the groups below. Your tabs haven’t changed.";
		} catch (error) {
			if (!this.controller.signal.aborted) {
				this.status = error instanceof Error ? error.message : "Could not organize tabs.";
			}
		} finally {
			this.busy = false;
		}
	}

	reject() {
		this.pending = null;
		this.retrievalStatus = "";
		this.status = "Proposal rejected. Your tabs haven’t changed.";
	}

	private async retrieveGroupings(snapshot: PageInfo[]): Promise<GroupingExample[]> {
		try {
			const qdrant = await getQdrantSettings();

			if (!qdrant.verifiedAt) {
				return [];
			}

			this.status = "Finding saved grouping examples…";
			const openai = await getSettings();
			const store = new GroupingVectorStore(qdrant, openai.apiKey);
			const query = JSON.stringify({ pages: snapshot.map(({ title, url }) => ({ title, url })) });

			const matches = await store.search(query, 5, this.controller.signal);
			const examples = matches.map((match) => match.savedGrouping);

			if (examples.length) {
				const label = examples.length === 1 ? "example" : "examples";

				this.retrievalStatus = `Using ${examples.length} saved grouping ${label}.`;
			} else {
				this.retrievalStatus = "No saved grouping examples found.";
			}

			return examples;
		} catch (error) {
			if (this.controller.signal.aborted) {
				throw error;
			}

			this.retrievalStatus = "Saved groupings unavailable. Using current tabs only.";
			return [];
		}
	}

	async approve() {
		if (!this.pending || this.busy) {
			return;
		}

		this.busy = true;
		this.status = "Applying approved groups…";
		const proposal = this.pending;

		try {
			await applyGroups(proposal);

			this.status = "Your tabs are organized.";
			this.pending = null;
			this.groupsToSave = approvedGroupings(proposal);

			await this.saveGroupings();
		} catch (error) {
			this.status = error instanceof Error ? error.message : "Could not apply groups.";
		} finally {
			this.pending = null;
			this.busy = false;
		}
	}

	async retrySave() {
		if (this.busy || !this.canRetrySave || !this.groupsToSave) {
			return;
		}

		this.busy = true;

		try {
			await this.saveGroupings();
		} finally {
			this.busy = false;
		}
	}

	private async saveGroupings() {
		if (!this.groupsToSave) {
			return;
		}

		this.canRetrySave = false;
		this.savedGroupingsStatus = "";

		try {
			const qdrant = await getQdrantSettings();

			if (!qdrant.verifiedAt) {
				this.groupsToSave = null;
				console.debug("Skipping saved groupings: Qdrant has no verified connection.");

				return;
			}

			this.savedGroupingsStatus = "Saving approved groupings…";

			const openai = await getSettings();

			if (!openai.verifiedAt) {
				throw new Error("Connect OpenAI to save approved groupings.");
			}

			const store = new GroupingVectorStore(qdrant, openai.apiKey);

			await store.saveGroups(this.groupsToSave, this.controller.signal);

			this.groupsToSave = null;
			this.savedGroupingsStatus = "Approved groupings saved.";
		} catch (error) {
			if (this.controller.signal.aborted) {
				return;
			}

			// Keep this failure separate from Chrome application, which already completed.
			const message = error instanceof Error ? error.message : "Could not save approved groupings.";

			this.savedGroupingsStatus = `Groupings weren’t saved. ${message}`;
			this.canRetrySave = true;
		}
	}

	watch() {
		const refresh = () => void this.refreshCount().catch(() => {});
		const events = [chrome.tabs.onCreated, chrome.tabs.onRemoved, chrome.tabs.onAttached, chrome.tabs.onDetached];

		events.forEach((event) => event.addListener(refresh));
		refresh();

		return () => {
			this.controller.abort();
			events.forEach((event) => event.removeListener(refresh));
		};
	}
}

function approvedGroupings(proposal: PendingProposal): ApprovedGroup[] {
	// Chrome application already validated every proposed ID against this snapshot.
	const pages = new Map(proposal.snapshot.map(({ id, title, url }) => [id, { title, url }]));
	const approvedAt = new Date().toISOString();

	return proposal.groups.map((group) => ({
		name: group.name,
		pages: group.tab_ids.map((id) => pages.get(id)!),
		approvedAt,
	}));
}
