import { afterEach, expect, test, vi } from "vitest";

import { getInstallationToken, SavedGroupings } from "../../extension/saved-groupings";
import { clearKey, removeLegacyDatabaseCredentials } from "../../extension/settings";

const apiUrl = "http://127.0.0.1:8765";

function storage(records: Record<string, unknown> = {}) {
	const area = {
		setAccessLevel: vi.fn(),
		get: vi.fn(async (key: string) => ({ [key]: records[key] })),
		set: vi.fn(async (value: Record<string, unknown>) => Object.assign(records, value)),
		remove: vi.fn(async (keys: string | string[]) => {
			for (const key of Array.isArray(keys) ? keys : [keys]) {
				delete records[key];
			}
		}),
	};
	vi.stubGlobal("chrome", { storage: { local: area, session: area } });
	vi.stubGlobal("navigator", {
		locks: { request: async (_name: string, _options: unknown, callback: () => unknown) => callback() },
	});
	return records;
}

afterEach(() => vi.unstubAllGlobals());

test("anonymous credential comes from the server and survives removing model keys", async () => {
	storage({ qdrant: { apiKey: "legacy-secret" } });
	const fetch = vi.fn(async () => Response.json({ token: "server-signed-installation" }));
	vi.stubGlobal("fetch", fetch);

	expect(await getInstallationToken()).toBe("server-signed-installation");
	await clearKey();
	await removeLegacyDatabaseCredentials();
	expect(await getInstallationToken()).toBe("server-signed-installation");
	expect(fetch).toHaveBeenCalledTimes(1);
	expect(fetch.mock.calls[0]).toMatchObject([
		`${apiUrl}/v1/installations`,
		{ redirect: "error", credentials: "omit" },
	]);
});

test("a failed credential is never silently replaced with a new identity", async () => {
	storage({ savedGroupingsInstallation: { token: "old-token", apiUrl } });
	const fetch = vi.fn(async (_url: string) => Response.json({ detail: "provider-secret" }, { status: 401 }));
	vi.stubGlobal("fetch", fetch);

	await expect(new SavedGroupings("openai-key").search("tabs")).rejects.toThrow();
	expect(fetch.mock.calls.every((call) => !String(call[0]).includes("/installations"))).toBe(true);
	expect(await getInstallationToken()).toBe("old-token");
});

test("database requests contain neither provider keys nor client-selected ownership", async () => {
	storage({ savedGroupingsInstallation: { token: "installation-token", apiUrl } });
	const calls: { url: string; options: RequestInit }[] = [];
	vi.stubGlobal("fetch", async (url: string, options: RequestInit) => {
		calls.push({ url: String(url), options });
		if (String(url).includes("api.openai.com")) {
			return Response.json({
				model: "text-embedding-3-small",
				data: [{ index: 0, embedding: [1, ...Array(1535).fill(0)] }],
			});
		}
		return Response.json({ ids: ["saved-id"] });
	});

	await new SavedGroupings("openai-key").saveGroups([
		{
			name: "Dev",
			pages: [{ title: "Python", url: "https://python.org" }],
			approvedAt: "2026-10-13T12:00:00Z",
		},
	]);
	const saved = calls.find((call) => call.url.endsWith("/v1/groupings"))!;
	expect(new Headers(saved.options.headers).get("authorization")).toBe("Bearer installation-token");
	expect(String(saved.options.body)).not.toContain("openai-key");
	expect(String(saved.options.body)).not.toContain("userId");
	expect(calls.some((call) => call.url.includes("qdrant"))).toBe(false);
});
