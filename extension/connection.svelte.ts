import { clearKey, DEFAULT_MODEL, getSettings, saveSettings } from "./settings";
import { ConnectionError, testConnection } from "./llm";
import { ModelDiscovery } from "./discovery.svelte";
import type { Connection } from "./types";

function emptyConnection(): Connection {
	return { apiKey: "", model: DEFAULT_MODEL, remember: false, verifiedAt: null };
}

export class ConnectionState {
	saved = $state<Connection>(emptyConnection());
	draft = $state<Connection>(emptyConnection());
	editing = $state(true);
	testing = $state(false);
	feedback = $state<ConnectionError | null>(null);
	discovery = new ModelDiscovery();

	private controller = new AbortController();

	get connected() {
		return Boolean(this.saved.apiKey && this.saved.verifiedAt) && !this.editing;
	}

	async load() {
		try {
			this.saved = await getSettings();

			if (this.controller.signal.aborted) {
				return;
			}

			if (this.saved.apiKey && this.saved.verifiedAt) {
				this.showSaved();
			} else {
				this.edit();
			}
		} catch {
			this.feedback = new ConnectionError("invalid", "Could not load settings. Reload the extension.", "Retry");
		}
	}

	edit() {
		if (this.testing) {
			return;
		}

		this.draft = { ...this.saved };
		this.editing = true;
		this.feedback = null;

		this.discovery.preserve(this.draft.model);
		void this.discovery.refresh(this.draft.apiKey, this.draft.model);
	}

	showSaved() {
		this.editing = false;
		this.draft = { ...this.saved, apiKey: "" };
		this.feedback = null;
	}

	async forget() {
		if (this.testing) {
			return;
		}

		await clearKey();

		this.saved = emptyConnection();
		this.discovery.reset();
		this.edit();
	}

	async verify() {
		if (this.testing || !this.draft.apiKey.trim()) {
			return;
		}

		const draft = { ...this.draft, apiKey: this.draft.apiKey.trim() };

		const keyHasLineBreaks = /[\r\n]/.test(draft.apiKey);
		// Model IDs are short identifiers, not URLs or arbitrary input.
		const validModelId = /^[a-zA-Z0-9._:-]{1,100}$/.test(draft.model);

		if (keyHasLineBreaks || !validModelId) {
			this.feedback = new ConnectionError("invalid", "Enter a valid key and model ID.", "Retry");
			return;
		}

		this.discovery.cancel();
		this.testing = true;
		this.feedback = null;

		try {
			await testConnection(draft, this.controller.signal);

			draft.verifiedAt = new Date().toISOString();
			await saveSettings(draft);

			this.saved = draft;
			this.showSaved();
		} catch (error) {
			if (this.controller.signal.aborted) {
				return;
			}

			this.feedback =
				error instanceof ConnectionError
					? error
					: new ConnectionError(
							"invalid",
							"Could not verify the response. Retry or choose another model.",
							"Retry",
						);
		} finally {
			this.testing = false;
		}
	}

	destroy() {
		this.controller.abort();
		this.discovery.cancel();
	}
}
