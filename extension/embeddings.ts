import OpenAI from "openai";

import { isRecord } from "./types";

export const EMBEDDING_MODEL = "text-embedding-3-small";
export const EMBEDDING_DIMENSIONS = 1536;
const REQUEST_TIMEOUT_MS = 30_000;

export async function embedTexts(texts: string[], apiKey: string, signal?: AbortSignal): Promise<number[][]> {
	const key = apiKey.trim();
	// Printable ASCII runs from ! to ~; exclude whitespace and Unicode from the key header.
	const validKey = /^[!-~]+$/.test(key);

	if (!validKey) {
		throw new Error("Enter a valid OpenAI API key.");
	}

	const validInputs =
		texts.length > 0 && texts.length <= 1000 && texts.every((text) => typeof text === "string" && text.trim());

	if (!validInputs) {
		throw new Error("Enter between 1 and 1,000 nonempty embedding inputs.");
	}

	const client = new OpenAI({
		apiKey: key,
		// The extension uses the owner's key in its trusted panel, never in a web page.
		dangerouslyAllowBrowser: true,
		maxRetries: 0,
		timeout: REQUEST_TIMEOUT_MS,
		fetch: globalThis.fetch,
	});

	const body = await requestEmbeddings(client, texts, signal);

	if (
		!isRecord(body) ||
		body.model !== EMBEDDING_MODEL ||
		!Array.isArray(body.data) ||
		body.data.length !== texts.length
	) {
		throw new Error("OpenAI returned invalid embeddings.");
	}

	const vectors: number[][] = new Array(texts.length);
	const seen = new Set<number>();

	// Providers may return batched embeddings out of order; indices associate them with inputs.
	for (const item of body.data) {
		if (!isRecord(item)) {
			throw new Error("OpenAI returned invalid embeddings.");
		}

		const index = item.index;
		const validIndex = typeof index === "number" && Number.isInteger(index) && index >= 0 && index < texts.length;

		if (!validIndex || seen.has(index) || !isEmbedding(item.embedding)) {
			throw new Error("OpenAI returned invalid embeddings.");
		}

		seen.add(index);
		vectors[index] = item.embedding;
	}

	return vectors;
}

async function requestEmbeddings(client: OpenAI, texts: string[], signal?: AbortSignal) {
	let requestSignal = AbortSignal.timeout(REQUEST_TIMEOUT_MS);

	if (signal) {
		requestSignal = AbortSignal.any([signal, requestSignal]);
	}

	try {
		requestSignal.throwIfAborted();

		const response = await client.embeddings.create(
			{
				model: EMBEDDING_MODEL,
				dimensions: EMBEDDING_DIMENSIONS,
				encoding_format: "float",
				input: texts,
			},
			{
				signal: requestSignal,
				fetchOptions: { redirect: "error", credentials: "omit" },
			},
		);

		requestSignal.throwIfAborted();
		return response;
	} catch (error) {
		if (requestSignal.reason?.name === "TimeoutError" || error instanceof OpenAI.APIConnectionTimeoutError) {
			throw new Error("OpenAI timed out. Try again.");
		}

		if (requestSignal.aborted || error instanceof OpenAI.APIUserAbortError) {
			throw new DOMException("Saved groupings request cancelled.", "AbortError");
		}

		// SDK errors can contain keys or page data. Show only messages we control.
		const status = error instanceof OpenAI.APIError ? error.status : undefined;

		if (status === 401 || status === 403) {
			throw new Error("OpenAI key rejected. Check access to embeddings.");
		}

		if (status === 429) {
			throw new Error("OpenAI is busy or quota is exhausted. Try again shortly.");
		}

		if (status !== undefined) {
			throw new Error(`OpenAI request failed (${status}). Check the connection and try again.`);
		}

		if (error instanceof TypeError || error instanceof OpenAI.APIConnectionError) {
			throw new Error("Could not connect to OpenAI. Check the connection and network.");
		}

		throw new Error("OpenAI returned an invalid response.");
	}
}

function isEmbedding(value: unknown): value is number[] {
	if (!Array.isArray(value) || value.length !== EMBEDDING_DIMENSIONS) {
		return false;
	}

	const finiteNumbers = value.every((number) => typeof number === "number" && Number.isFinite(number));
	const nonzero = value.some((number) => number !== 0);

	return finiteNumbers && nonzero;
}
