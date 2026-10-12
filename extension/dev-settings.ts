import { testQdrantConnection } from "./qdrant";
import { getQdrantSettings, saveQdrantSettings } from "./settings";

export async function loadDevSettings() {
	if (import.meta.env.MODE !== "development" && import.meta.env.MODE !== "qdrant-test") {
		return;
	}

	const url = import.meta.env.QDRANT_ENDPOINT;
	const apiKey = import.meta.env.QDRANT_API_KEY;

	if (!url || !apiKey) {
		return;
	}

	try {
		const saved = await getQdrantSettings();

		if (saved.url === url && saved.apiKey === apiKey && saved.verifiedAt) {
			return;
		}

		const verified = await testQdrantConnection({ url, apiKey, remember: false, verifiedAt: null });

		verified.verifiedAt = new Date().toISOString();
		await saveQdrantSettings(verified);

		console.debug("Development Qdrant connection verified from .env.");
	} catch (error) {
		const message = error instanceof Error ? error.message : "Connection setup failed.";

		console.warn(`Development Qdrant setup failed: ${message}`);
	}
}
