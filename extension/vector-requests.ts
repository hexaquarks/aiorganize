import OpenAI from "openai";

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

export function hasStatus(error: unknown, status: number): boolean {
	return isRecord(error) && error.status === status;
}

export async function runVectorRequest<T>(
	service: "OpenAI" | "Qdrant",
	signal: AbortSignal | undefined,
	request: (options: RequestInit) => Promise<T>,
): Promise<T> {
	let requestSignal = AbortSignal.timeout(30000);

	if (signal) {
		requestSignal = AbortSignal.any([signal, requestSignal]);
	}

	try {
		requestSignal.throwIfAborted();

		const result = await request({ signal: requestSignal, redirect: "error", credentials: "omit" });

		requestSignal.throwIfAborted();
		return result;
	} catch (error) {
		if (requestSignal.reason?.name === "TimeoutError" || error instanceof OpenAI.APIConnectionTimeoutError) {
			throw new Error(`${service} timed out. Try again.`);
		}

		if (requestSignal.aborted || error instanceof OpenAI.APIUserAbortError) {
			throw new DOMException("Saved groupings request cancelled.", "AbortError");
		}

		// SDK errors can contain keys or page data. Show only messages we control.
		if (hasStatus(error, 401) || hasStatus(error, 403)) {
			const requiredAccess = service === "OpenAI" ? "embeddings" : "the saved groupings collection";

			throw new Error(`${service} key rejected. Check access to ${requiredAccess}.`);
		}

		if (hasStatus(error, 429)) {
			throw new Error(`${service} is busy or quota is exhausted. Try again shortly.`);
		}

		if (isRecord(error) && typeof error.status === "number") {
			throw new Error(`${service} request failed (${error.status}). Check the connection and try again.`);
		}

		if (error instanceof TypeError || error instanceof OpenAI.APIConnectionError) {
			throw new Error(`Could not connect to ${service}. Check the connection and network.`);
		}

		throw new Error(`${service} returned an invalid response.`);
	}
}
