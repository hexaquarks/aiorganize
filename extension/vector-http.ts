export function isRecord(value: unknown): value is Record<string, unknown> {
	return value !== null && typeof value === "object" && !Array.isArray(value);
}

export function validateApiKey(value: string, service: string): string {
	const key = value.trim();

	// Keys become HTTP headers; reject spaces, line breaks, and non-ASCII characters.
	if (!/^[\x21-\x7e]+$/.test(key)) {
		throw new Error(`Enter a valid ${service} API key.`);
	}

	return key;
}

export async function requestVectorJson(
	url: string,
	options: RequestInit,
	service: "OpenAI" | "Qdrant",
	signal?: AbortSignal,
	allowedStatuses: number[] = [],
): Promise<{ status: number; body: unknown }> {
	const signals = [AbortSignal.timeout(30000)];

	if (signal) {
		signals.push(signal);
	}

	const requestSignal = AbortSignal.any(signals);

	try {
		requestSignal.throwIfAborted();

		const response = await fetch(url, {
			...options,
			signal: requestSignal,
			redirect: "error",
			credentials: "omit",
		});

		requestSignal.throwIfAborted();

		if (allowedStatuses.includes(response.status)) {
			return { status: response.status, body: null };
		}

		// Provider error bodies may contain keys or page data; never surface their messages.
		if (response.status === 401 || response.status === 403) {
			const requiredAccess = service === "OpenAI" ? "embeddings" : "the memory collection";

			throw new Error(`${service} key rejected. Check access to ${requiredAccess}.`);
		}

		if (response.status === 429) {
			throw new Error(`${service} is busy or quota is exhausted. Try again shortly.`);
		}

		if (!response.ok) {
			throw new Error(`${service} request failed (${response.status}). Check the connection and try again.`);
		}

		let body: unknown;

		try {
			body = await response.json();
			requestSignal.throwIfAborted();
		} catch {
			requestSignal.throwIfAborted();
			throw new Error(`${service} returned an invalid response.`);
		}

		return { status: response.status, body };
	} catch (error) {
		if (requestSignal.reason?.name === "TimeoutError") {
			throw new Error(`${service} timed out. Try again.`);
		}

		if (requestSignal.aborted) {
			throw new DOMException("Memory request cancelled.", "AbortError");
		}

		if (error instanceof TypeError) {
			throw new Error(`Could not connect to ${service}. Check the connection and network.`);
		}

		throw error;
	}
}
