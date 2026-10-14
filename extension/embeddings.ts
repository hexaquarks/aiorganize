import { OpenAIEmbeddings } from "@langchain/openai";
import { StatusCodes } from "http-status-codes";

import { modelErrorName, modelErrorStatus } from "./model-errors";

import { isRecord } from "./types";

export const EMBEDDING_MODEL = "text-embedding-3-small";
export const EMBEDDING_DIMENSIONS = 1536;
const REQUEST_TIMEOUT_MS = 30_000;
const MAX_EMBEDDING_INPUTS = 1000;

export async function embedTexts(texts: string[], apiKey: string, signal?: AbortSignal): Promise<number[][]> {
	const key = apiKey.trim();
	// Printable ASCII runs from ! to ~; exclude whitespace and Unicode from the key header.
	const validKey = /^[!-~]+$/.test(key);

	if (!validKey) {
		throw new Error("Enter a valid OpenAI API key.");
	}

	const validInputs =
		texts.length > 0 &&
		texts.length <= MAX_EMBEDDING_INPUTS &&
		texts.every((text) => typeof text === "string" && text.trim());

	if (!validInputs) {
		throw new Error(
			`Enter between 1 and ${MAX_EMBEDDING_INPUTS.toLocaleString("en-US")} nonempty embedding inputs.`,
		);
	}

	let requestSignal = AbortSignal.timeout(REQUEST_TIMEOUT_MS);

	if (signal) {
		requestSignal = AbortSignal.any([signal, requestSignal]);
	}

	const embeddings = new OpenAIEmbeddings({
		apiKey: key,
		model: EMBEDDING_MODEL,
		dimensions: EMBEDDING_DIMENSIONS,
		encodingFormat: "float",
		// Preserve the exact embedding inputs used by the existing collection.
		stripNewLines: false,
		batchSize: MAX_EMBEDDING_INPUTS,
		maxRetries: 0,
		timeout: REQUEST_TIMEOUT_MS,
		configuration: {
			// LangChain embeddings do not accept a signal; cancel through the transport.
			fetch: async (url, options) => {
				const response = await globalThis.fetch(url, {
					...options,
					signal: requestSignal,
					redirect: "error",
					credentials: "omit",
				});

				if (!response.ok) {
					return response;
				}

				const body = await response.json();
				const vectors = readEmbeddings(body, texts.length);

				// LangChain reads response order rather than indices; validate and order the batch first.
				const data = vectors.map((embedding, index) => ({ index, embedding }));
				return Response.json({ model: EMBEDDING_MODEL, data });
			},
		},
	});

	try {
		requestSignal.throwIfAborted();

		const vectors = await embeddings.embedDocuments(texts);

		requestSignal.throwIfAborted();
		return vectors;
	} catch (error) {
		const status = modelErrorStatus(error);
		const cause = isRecord(error) ? error.cause : undefined;

		if (requestSignal.reason?.name === "TimeoutError") {
			throw new Error("OpenAI timed out. Try again.");
		}

		if (requestSignal.aborted) {
			throw new DOMException("Saved groupings request cancelled.", "AbortError");
		}

		if (["TimeoutError", "APIConnectionTimeoutError"].includes(modelErrorName(error))) {
			throw new Error("OpenAI timed out. Try again.");
		}

		// Provider errors can contain keys or page data. Show only messages we control.
		if (status === StatusCodes.UNAUTHORIZED || status === StatusCodes.FORBIDDEN) {
			throw new Error("OpenAI key rejected. Check access to embeddings.");
		}

		if (status === StatusCodes.TOO_MANY_REQUESTS) {
			throw new Error("OpenAI is busy or quota is exhausted. Try again shortly.");
		}

		if (status !== undefined) {
			throw new Error(`OpenAI request failed (${status}). Check the connection and try again.`);
		}

		if (error instanceof SyntaxError || cause instanceof SyntaxError) {
			throw new Error("OpenAI returned an invalid response.");
		}

		if (cause instanceof TypeError) {
			throw new Error("Could not connect to OpenAI. Check the connection and network.");
		}

		throw new Error("OpenAI returned invalid embeddings.");
	}
}

function readEmbeddings(body: unknown, inputCount: number): number[][] {
	if (
		!isRecord(body) ||
		body.model !== EMBEDDING_MODEL ||
		!Array.isArray(body.data) ||
		body.data.length !== inputCount
	) {
		throw new Error("OpenAI returned invalid embeddings.");
	}

	const vectors: number[][] = new Array(inputCount);
	const seen = new Set<number>();

	// Providers may return batched embeddings out of order; indices associate them with inputs.
	for (const item of body.data) {
		if (!isRecord(item)) {
			throw new Error("OpenAI returned invalid embeddings.");
		}

		const index = item.index;
		const validIndex = typeof index === "number" && Number.isInteger(index) && index >= 0 && index < inputCount;

		if (!validIndex || seen.has(index) || !isEmbedding(item.embedding)) {
			throw new Error("OpenAI returned invalid embeddings.");
		}

		seen.add(index);
		vectors[index] = item.embedding;
	}

	return vectors;
}

function isEmbedding(value: unknown): value is number[] {
	if (!Array.isArray(value) || value.length !== EMBEDDING_DIMENSIONS) {
		return false;
	}

	const finiteNumbers = value.every((number) => typeof number === "number" && Number.isFinite(number));
	const nonzero = value.some((number) => number !== 0);

	return finiteNumbers && nonzero;
}
