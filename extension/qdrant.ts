import type { QdrantConnection } from "./types";

export function normalizeQdrantUrl(value: string): string {
	let url: URL;

	try {
		url = new URL(value.trim());
	} catch {
		throw new Error("Enter a valid Qdrant Cloud HTTPS URL.");
	}

	// Limit credentials to the Cloud hosts covered by the extension's permissions.
	if (
		url.protocol !== "https:" ||
		!url.hostname.endsWith(".cloud.qdrant.io") ||
		url.username ||
		url.password ||
		url.search ||
		url.hash ||
		url.pathname !== "/" ||
		(url.port && url.port !== "6333")
	) {
		throw new Error("Use your Qdrant Cloud cluster URL (HTTPS, port 6333 or 443, without a path).");
	}

	return url.origin;
}

function isCollection(value: unknown): boolean {
	if (value === null || typeof value !== "object") {
		return false;
	}

	return "name" in value && typeof value.name === "string";
}

export async function testQdrantConnection(connection: QdrantConnection, signal?: AbortSignal) {
	const url = normalizeQdrantUrl(connection.url);
	const apiKey = connection.apiKey.trim();

	// Header values must contain printable ASCII without spaces or line breaks.
	const validApiKey = /^[\x21-\x7e]+$/.test(apiKey);

	if (!validApiKey) {
		throw new Error("Enter a valid Qdrant database API key.");
	}

	const signals = [AbortSignal.timeout(15000)];

	if (signal) {
		signals.push(signal);
	}

	const requestSignal = AbortSignal.any(signals);

	try {
		// Reading the list verifies database access without creating or changing data.
		const response = await fetch(`${url}/collections`, {
			headers: { "api-key": apiKey },
			signal: requestSignal,
			redirect: "error",
			credentials: "omit",
		});

		if (response.status === 401 || response.status === 403) {
			throw new Error("Key rejected. Use a database API key with access to list collections.");
		}

		if (response.status === 404) {
			throw new Error("Qdrant endpoint not found. Check the cluster URL.");
		}

		if (response.status === 429) {
			throw new Error("Qdrant is busy. Try again shortly.");
		}

		if (!response.ok) {
			throw new Error("Qdrant is unavailable. Try again shortly.");
		}

		let body;

		try {
			body = await response.json();
		} catch {
			throw new Error("Qdrant returned an invalid response. Check the cluster URL.");
		}

		const collections = body?.result?.collections;
		const validCollections = Array.isArray(collections) && collections.every(isCollection);

		if (body?.status !== "ok" || !validCollections) {
			throw new Error("Qdrant returned an invalid response. Check the cluster URL.");
		}
	} catch (error) {
		if (requestSignal.reason?.name === "TimeoutError") {
			throw new Error("Qdrant timed out. Try again.");
		}

		if (requestSignal.aborted) {
			throw new DOMException("Connection test cancelled.", "AbortError");
		}

		if (error instanceof TypeError) {
			throw new Error("Could not connect to Qdrant. Check the URL and network.");
		}

		throw error;
	}

	return { ...connection, url, apiKey };
}
