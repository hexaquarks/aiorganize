import { afterEach, expect, test, vi } from "vitest";

import { loadDevSettings } from "../../extension/dev-settings";
import { testQdrantConnection } from "../../extension/qdrant";
import { getQdrantSettings, saveQdrantSettings } from "../../extension/settings";

vi.mock("../../extension/qdrant", () => ({ testQdrantConnection: vi.fn() }));
vi.mock("../../extension/settings", () => ({ getQdrantSettings: vi.fn(), saveQdrantSettings: vi.fn() }));

const connection = {
	url: "https://example.cloud.qdrant.io",
	apiKey: "test-key",
	remember: false,
	verifiedAt: null,
};

afterEach(() => {
	vi.unstubAllEnvs();
	vi.restoreAllMocks();
	vi.resetAllMocks();
});

test("development settings verify environment credentials before saving them to the session", async () => {
	vi.stubEnv("MODE", "development");
	vi.stubEnv("QDRANT_ENDPOINT", connection.url);
	vi.stubEnv("QDRANT_API_KEY", connection.apiKey);
	vi.spyOn(console, "debug").mockImplementation(() => {});
	vi.mocked(getQdrantSettings).mockResolvedValue({ ...connection, url: "", apiKey: "" });
	vi.mocked(testQdrantConnection).mockResolvedValue({ ...connection });

	await loadDevSettings();

	expect(testQdrantConnection).toHaveBeenCalledWith(connection);
	expect(saveQdrantSettings).toHaveBeenCalledWith({ ...connection, verifiedAt: expect.any(String) });
});

test("production ignores environment credentials", async () => {
	vi.stubEnv("MODE", "production");
	vi.stubEnv("QDRANT_ENDPOINT", connection.url);
	vi.stubEnv("QDRANT_API_KEY", connection.apiKey);

	await loadDevSettings();

	expect(getQdrantSettings).not.toHaveBeenCalled();
	expect(testQdrantConnection).not.toHaveBeenCalled();
	expect(saveQdrantSettings).not.toHaveBeenCalled();
});

test("development without environment credentials preserves manual settings", async () => {
	vi.stubEnv("MODE", "development");
	vi.stubEnv("QDRANT_ENDPOINT", "");
	vi.stubEnv("QDRANT_API_KEY", "");

	await loadDevSettings();

	expect(getQdrantSettings).not.toHaveBeenCalled();
	expect(saveQdrantSettings).not.toHaveBeenCalled();
});

test("failed verification is logged and never saved as a working connection", async () => {
	vi.stubEnv("MODE", "development");
	vi.stubEnv("QDRANT_ENDPOINT", connection.url);
	vi.stubEnv("QDRANT_API_KEY", connection.apiKey);
	vi.mocked(getQdrantSettings).mockResolvedValue({ ...connection, verifiedAt: null });
	vi.mocked(testQdrantConnection).mockRejectedValue(new Error("provider-secret test-key"));
	const warning = vi.spyOn(console, "warn").mockImplementation(() => {});

	await expect(loadDevSettings()).resolves.toBeUndefined();

	expect(saveQdrantSettings).not.toHaveBeenCalled();
	expect(warning).toHaveBeenCalledWith(
		"Development Qdrant setup failed. Check the endpoint, database key, and network.",
	);
});
