import { requestProposal } from "./llm";
import { validateProposal } from "./proposal";
import { applyGroups, getTabState } from "./tabs";
import type { PendingProposal } from "./types";

export class GroupingState {
	pending = $state<PendingProposal | null>(null);
	busy = $state(false);
	tabCount = $state(0);
	status = $state("");

	private controller = new AbortController();

	async refreshCount() {
		const window = await chrome.windows.getCurrent();
		const state = await getTabState();

		this.tabCount = state.tabs.filter((tab) => tab.window_id === window.id).length;
	}

	async organize() {
		this.pending = null;
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

			const proposal = await requestProposal({
				snapshot,
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
		this.status = "Proposal rejected. Your tabs haven’t changed.";
	}

	async approve() {
		if (!this.pending) {
			return;
		}

		this.busy = true;
		this.status = "Applying approved groups…";

		try {
			await applyGroups(this.pending);

			this.status = "Your tabs are organized.";
		} catch (error) {
			this.status = error instanceof Error ? error.message : "Could not apply groups.";
		} finally {
			this.pending = null;
			this.busy = false;
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
