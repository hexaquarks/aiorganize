import { isRecord, requestVectorJson, validateApiKey } from "./vector-http";

export const EMBEDDING_MODEL = "text-embedding-3-small";
export const EMBEDDING_DIMENSIONS = 1536;

export async function embedTexts(texts: string[], apiKey: string, signal?: AbortSignal): Promise<number[][]> {
	const key = validateApiKey(apiKey, "OpenAI");
	const validInputs =
		texts.length > 0 && texts.length <= 1000 && texts.every((text) => typeof text === "string" && text.trim());

	if (!validInputs) {
		throw new Error("Enter between 1 and 1,000 nonempty embedding inputs.");
	}

	const { body } = await requestVectorJson(
		"https://api.openai.com/v1/embeddings",
		{
			method: "POST",
			headers: { Authorization: `Bearer ${key}`, "Content-Type": "application/json" },
			body: JSON.stringify({
				model: EMBEDDING_MODEL,
				dimensions: EMBEDDING_DIMENSIONS,
				encoding_format: "float",
				input: texts,
			}),
		},
		"OpenAI",
		signal,
	);

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

function isEmbedding(value: unknown): value is number[] {
	if (!Array.isArray(value) || value.length !== EMBEDDING_DIMENSIONS) {
		return false;
	}

	const finiteNumbers = value.every((number) => typeof number === "number" && Number.isFinite(number));
	const nonzero = value.some((number) => number !== 0);

	return finiteNumbers && nonzero;
}
