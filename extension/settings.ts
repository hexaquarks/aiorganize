import type { Connection, QdrantConnection } from "./types";

import { SUPPORTED_MODELS } from "./model-catalog";

export const DEFAULT_MODEL = SUPPORTED_MODELS[0].id;

interface StoredSettings {
	connection?: Omit<Connection, "remember">;
	apiKey?: string;
	model?: string;
}

async function restrictStorage() {
	await chrome.storage.local.setAccessLevel({ accessLevel: "TRUSTED_CONTEXTS" });
	await chrome.storage.session.setAccessLevel({ accessLevel: "TRUSTED_CONTEXTS" });
}

export async function getSettings(): Promise<Connection> {
	await restrictStorage();
	const local = await chrome.storage.local.get<StoredSettings>(["connection", "apiKey", "model"]);
	const session = await chrome.storage.session.get<StoredSettings>(["connection", "apiKey"]);
	const connection = session.connection || local.connection;
	if (connection) {
		return {
			...connection,
			model: connection.verifiedAt ? connection.model : DEFAULT_MODEL,
			remember: !session.connection,
		};
	}
	// Keep legacy keys, but discard unverified model preferences so setup uses the current default.
	return {
		apiKey: session.apiKey || local.apiKey || "",
		model: DEFAULT_MODEL,
		remember: Boolean(local.apiKey),
		verifiedAt: null,
	};
}

export async function saveSettings({ apiKey, model, remember, verifiedAt }: Connection) {
	await restrictStorage();
	if (!apiKey || !verifiedAt) throw new Error("Test the connection before saving it.");
	const connection = { apiKey, model, verifiedAt };
	const target = remember ? chrome.storage.local : chrome.storage.session;
	const other = remember ? chrome.storage.session : chrome.storage.local;
	// One record keeps the tested key, model, and verification time together.
	await target.set({ connection });
	await other.remove("connection");
	await chrome.storage.session.remove("apiKey");
	await chrome.storage.local.remove(["apiKey", "model"]);
}

export async function clearKey() {
	await restrictStorage();
	await chrome.storage.session.remove(["connection", "apiKey"]);
	await chrome.storage.local.remove(["connection", "apiKey", "model"]);
}

export async function getQdrantSettings(): Promise<QdrantConnection> {
	await restrictStorage();

	const local = await chrome.storage.local.get<{ qdrant?: Omit<QdrantConnection, "remember"> }>("qdrant");
	const session = await chrome.storage.session.get<{ qdrant?: Omit<QdrantConnection, "remember"> }>("qdrant");
	const connection = session.qdrant || local.qdrant;

	if (connection) {
		return { ...connection, remember: !session.qdrant };
	}

	return { url: "", apiKey: "", remember: false, verifiedAt: null };
}

export async function saveQdrantSettings({ url, apiKey, remember, verifiedAt }: QdrantConnection) {
	await restrictStorage();

	if (!url || !apiKey || !verifiedAt) {
		throw new Error("Test the Qdrant connection before saving it.");
	}

	const target = remember ? chrome.storage.local : chrome.storage.session;
	const other = remember ? chrome.storage.session : chrome.storage.local;

	await target.set({ qdrant: { url, apiKey, verifiedAt } });
	await other.remove("qdrant");
}

export async function clearQdrantSettings() {
	await restrictStorage();

	await chrome.storage.session.remove("qdrant");
	await chrome.storage.local.remove("qdrant");
}
