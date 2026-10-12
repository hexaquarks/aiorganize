import { afterEach, expect, test, vi } from "vitest";
import { validate as isUuid } from "uuid";

import { clearKey, clearQdrantSettings, getSavedGroupingsUserId } from "../../extension/settings";

function mockStorage(records: Record<string, unknown> = {}) {
	const local = {
		setAccessLevel: vi.fn(),
		get: vi.fn(async (key: string) => ({ [key]: records[key] })),
		set: vi.fn(async (value: Record<string, unknown>) => Object.assign(records, value)),
		remove: vi.fn(async (keys: string | string[]) => {
			for (const key of Array.isArray(keys) ? keys : [keys]) {
				delete records[key];
			}
		}),
	};
	const session = { setAccessLevel: vi.fn(), remove: vi.fn() };
	const request = vi.fn(async (_name: string, callback: () => Promise<string>) => callback());

	vi.stubGlobal("chrome", { storage: { local, session } });
	vi.stubGlobal("navigator", { locks: { request } });

	return { records, local, request };
}

afterEach(() => {
	vi.unstubAllGlobals();
});

test("a profile receives one stored UUID and reuses it for subsequent requests", async () => {
	const { records, local, request } = mockStorage();

	const first = await getSavedGroupingsUserId();
	const second = await getSavedGroupingsUserId();

	expect(isUuid(first)).toBe(true);
	expect(second).toBe(first);
	expect(records.savedGroupingsUserId).toBe(first);
	expect(local.set).toHaveBeenCalledTimes(1);
	expect(request).toHaveBeenCalledWith("saved-groupings-user-id", expect.any(Function));
});

test("removing provider keys preserves the user's grouping identity", async () => {
	const userId = "661f4c48-e00e-4d83-8126-a3a78fd3dd10";
	mockStorage({ savedGroupingsUserId: userId, connection: {}, apiKey: "key", qdrant: {} });

	await clearKey();
	await clearQdrantSettings();

	expect(await getSavedGroupingsUserId()).toBe(userId);
});

test("a corrupted identity fails instead of selecting someone else's history", async () => {
	const { local } = mockStorage({ savedGroupingsUserId: "invalid" });

	await expect(getSavedGroupingsUserId()).rejects.toThrow("identity is invalid");
	expect(local.set).not.toHaveBeenCalled();
});
