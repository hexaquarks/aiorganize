import { clearQdrantSettings, getQdrantSettings, saveQdrantSettings } from "./settings";
import { testQdrantConnection } from "./qdrant";
import type { QdrantConnection } from "./types";

function emptyConnection(): QdrantConnection {
	return { url: "", apiKey: "", remember: false, verifiedAt: null };
}

export class QdrantConnectionState {
	saved = $state<QdrantConnection>(emptyConnection());
	draft = $state<QdrantConnection>(emptyConnection());
	testing = $state(false);
	feedback = $state("");

	private controller = new AbortController();

	async load() {
		try {
			const saved = await getQdrantSettings();

			if (this.controller.signal.aborted) {
				return;
			}

			this.saved = saved;
			this.reset();
		} catch {
			this.feedback = "Could not load Qdrant settings. Reload the extension.";
		}
	}

	reset() {
		if (this.testing) {
			return;
		}

		this.draft = { ...this.saved };
		this.feedback = "";
	}

	async verify() {
		if (this.testing) {
			return;
		}

		this.testing = true;
		this.feedback = "";

		try {
			const verified = await testQdrantConnection({ ...this.draft }, this.controller.signal);

			if (this.controller.signal.aborted) {
				return;
			}

			verified.verifiedAt = new Date().toISOString();
			await saveQdrantSettings(verified);

			this.saved = verified;
			this.draft = { ...verified };
			this.feedback = "Qdrant connection verified and saved.";
		} catch (error) {
			if (this.controller.signal.aborted) {
				return;
			}

			this.feedback = error instanceof Error ? error.message : "Could not save Qdrant settings. Try again.";
		} finally {
			this.testing = false;
		}
	}

	async forget() {
		if (this.testing) {
			return;
		}

		try {
			await clearQdrantSettings();

			this.saved = emptyConnection();
			this.reset();
		} catch {
			this.feedback = "Could not remove the Qdrant connection. Try again.";
		}
	}

	destroy() {
		this.controller.abort();
	}
}
