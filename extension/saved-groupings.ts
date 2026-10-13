import { embedTexts } from "./embeddings";
import { isRecord } from "./types";
import type { GroupingExample } from "./types";

const API_URL = import.meta.env.APP_API_URL;

export interface ApprovedGroup extends GroupingExample {
	approvedAt: string;
}

async function request(path: string, body: unknown, token?: string, signal?: AbortSignal): Promise<unknown> {
	const headers: Record<string, string> = { "Content-Type": "application/json" };

	if (token) {
		headers.Authorization = `Bearer ${token}`;
	}

	const signals = [AbortSignal.timeout(30000)];

	if (signal) {
		signals.push(signal);
	}

	const response = await fetch(`${API_URL}${path}`, {
		method: "POST",
		headers,
		body: JSON.stringify(body),
		signal: AbortSignal.any(signals),
		redirect: "error",
		credentials: "omit",
	});

	if (!response.ok) {
		throw new Error("Saved groupings are temporarily unavailable.");
	}

	return response.json();
}

export async function getInstallationToken(signal?: AbortSignal): Promise<string> {
	await chrome.storage.local.setAccessLevel({ accessLevel: "TRUSTED_CONTEXTS" });

	// One server-issued credential per installation, even when several panels open together.
	return navigator.locks.request("saved-groupings-installation", { signal }, async () => {
		const { savedGroupingsInstallation } = await chrome.storage.local.get("savedGroupingsInstallation");

		if (savedGroupingsInstallation) {
			if (
				!isRecord(savedGroupingsInstallation) ||
				savedGroupingsInstallation.apiUrl !== API_URL ||
				typeof savedGroupingsInstallation.token !== "string"
			) {
				throw new Error("Saved grouping configuration changed. Contact the app owner.");
			}

			return savedGroupingsInstallation.token;
		}

		const response = await request("/v1/installations", {}, undefined, signal);

		if (!isRecord(response) || typeof response.token !== "string" || !response.token) {
			throw new Error("Could not set up saved groupings.");
		}

		await chrome.storage.local.set({ savedGroupingsInstallation: { apiUrl: API_URL, token: response.token } });
		return response.token;
	});
}

export class SavedGroupings {
	constructor(private readonly openaiKey: string) {}

	async saveGroups(groups: ApprovedGroup[], signal?: AbortSignal): Promise<string[]> {
		if (!groups.length) {
			return [];
		}

		const token = await getInstallationToken(signal);
		const cleanGroups = groups.map(({ name, pages, approvedAt }) => ({
			name,
			pages: pages.map(({ title, url }) => ({ title, url })),
			approvedAt,
		}));
		const texts = cleanGroups.map(({ name, pages }) => JSON.stringify({ name, pages }));
		const vectors = await embedTexts(texts, this.openaiKey, signal);
		const body = { groups: cleanGroups.map((group, index) => ({ ...group, vector: vectors[index] })) };
		const response = await request("/v1/groupings", body, token, signal);

		if (
			!isRecord(response) ||
			!Array.isArray(response.ids) ||
			response.ids.length !== groups.length ||
			!response.ids.every((id) => typeof id === "string")
		) {
			throw new Error("Saving groupings was not confirmed.");
		}

		return response.ids;
	}

	async search(query: string, signal?: AbortSignal): Promise<GroupingExample[]> {
		const token = await getInstallationToken(signal);
		const [vector] = await embedTexts([query], this.openaiKey, signal);
		const response = await request("/v1/groupings/search", { vector, limit: 5 }, token, signal);

		if (!isRecord(response) || !Array.isArray(response.groups) || response.groups.length > 5) {
			throw new Error("Invalid saved grouping response.");
		}

		return response.groups.map((group) => {
			if (!isRecord(group) || typeof group.name !== "string" || !Array.isArray(group.pages)) {
				throw new Error("Invalid saved grouping response.");
			}

			const pages = group.pages.map((page) => {
				if (!isRecord(page) || typeof page.title !== "string" || typeof page.url !== "string") {
					throw new Error("Invalid saved grouping response.");
				}

				return { title: page.title, url: page.url };
			});

			return { name: group.name, pages };
		});
	}
}
