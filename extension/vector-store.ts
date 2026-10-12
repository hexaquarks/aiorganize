import type { QdrantConnection } from "./types";

import { v5 as uuidv5 } from "uuid";

import { embedTexts, EMBEDDING_DIMENSIONS, EMBEDDING_MODEL } from "./embeddings";
import { normalizeQdrantUrl } from "./qdrant";
import { isRecord, requestVectorJson, validateApiKey } from "./vector-http";

export const SAVED_GROUPINGS_COLLECTION = "aiorganize_groups_v1_text_embedding_3_small_1536";
const SCHEMA_VERSION = 1;
const SAVED_GROUPINGS_INDEXES = [
	{ field_name: "schemaVersion", field_schema: "integer" },
	{ field_name: "embeddingModel", field_schema: "keyword" },
	{ field_name: "embeddingDimensions", field_schema: "integer" },
];

export interface ApprovedGroup {
	name: string;
	pages: { title: string; url: string }[];
	approvedAt: string;
}

export interface SavedGrouping extends ApprovedGroup {
	schemaVersion: number;
	embeddingModel: string;
	embeddingDimensions: number;
}

export interface GroupMatch {
	id: string;
	score: number;
	savedGrouping: SavedGrouping;
}

export class GroupingVectorStore {
	private readonly connection: QdrantConnection;
	private readonly apiKey: string;

	constructor(connection: QdrantConnection, apiKey: string) {
		this.connection = { ...connection };
		this.apiKey = apiKey;
	}

	// The caller must supply only groups whose application in Chrome completed successfully.
	async saveGroups(groups: ApprovedGroup[], signal?: AbortSignal): Promise<string[]> {
		if (groups.length === 0) {
			return [];
		}

		if (groups.length > 1000 || !groups.every(isApprovedGroup)) {
			throw new Error("Invalid approved groups. Include a name, pages, and approval timestamp.");
		}

		// Keep only saved grouping fields before hashing, embedding, or uploading caller objects.
		const savedGroupings = groups.map(savedGroupingPayload);
		const texts = savedGroupings.map(groupText);

		this.validateConnection();
		let collection = await this.readCollection(signal);
		const vectors = await embedTexts(texts, this.apiKey, signal);
		const ids = texts.map(savedGroupingId);

		// Validate embeddings before creating a collection or making any database write.
		if (!collection) {
			collection = await this.createCollection(signal);
		}

		await this.ensureIndexes(collection, signal);

		const points = savedGroupings.map((payload, index) => ({ id: ids[index], vector: vectors[index], payload }));
		const { body } = await this.request("/points?wait=true", "PUT", { points }, signal);
		const result = qdrantResult(body);

		if (!isRecord(result) || result.status !== "completed") {
			throw new Error(
				"Qdrant did not confirm saving the groupings. Retry to confirm it without duplicating records.",
			);
		}

		return ids;
	}

	async search(query: string, limit = 5, signal?: AbortSignal): Promise<GroupMatch[]> {
		if (typeof query !== "string" || !query.trim()) {
			throw new Error("Enter a nonempty saved grouping search query.");
		}

		if (!Number.isInteger(limit) || limit < 1 || limit > 20) {
			throw new Error("Saved grouping search limit must be between 1 and 20.");
		}

		this.validateConnection();

		const collection = await this.readCollection(signal);

		if (!collection) {
			return [];
		}

		if (missingIndexes(collection).length) {
			throw new Error("Saved grouping search indexes are missing. Save an approved group to finish setup.");
		}

		const [vector] = await embedTexts([query], this.apiKey, signal);
		const { body } = await this.request(
			"/points/query",
			"POST",
			{
				query: vector,
				limit,
				with_payload: true,
				with_vector: false,
				filter: {
					must: [
						{ key: "schemaVersion", match: { value: SCHEMA_VERSION } },
						{ key: "embeddingModel", match: { value: EMBEDDING_MODEL } },
						{ key: "embeddingDimensions", match: { value: EMBEDDING_DIMENSIONS } },
					],
				},
			},
			signal,
		);
		const result = qdrantResult(body);

		if (!isRecord(result) || !Array.isArray(result.points) || result.points.length > limit) {
			throw new Error("Qdrant returned invalid search results.");
		}

		const matches: GroupMatch[] = [];

		for (const point of result.points) {
			if (
				!isRecord(point) ||
				typeof point.id !== "string" ||
				typeof point.score !== "number" ||
				!Number.isFinite(point.score)
			) {
				throw new Error("Qdrant returned an invalid search record.");
			}

			const payload = point.payload;

			if (!isRecord(payload)) {
				throw new Error("Qdrant returned an invalid saved grouping record.");
			}

			const compatible =
				payload.schemaVersion === SCHEMA_VERSION &&
				payload.embeddingModel === EMBEDDING_MODEL &&
				payload.embeddingDimensions === EMBEDDING_DIMENSIONS;

			if (!compatible) {
				continue;
			}

			if (!isApprovedGroup(payload)) {
				throw new Error("Qdrant returned an invalid saved grouping record.");
			}

			matches.push({ id: point.id, score: point.score, savedGrouping: savedGroupingPayload(payload) });
		}

		return matches;
	}

	private validateConnection() {
		if (!this.connection.verifiedAt) {
			throw new Error("Test and save your Qdrant connection before using saved groupings.");
		}

		normalizeQdrantUrl(this.connection.url);
		validateApiKey(this.connection.apiKey, "Qdrant");
		validateApiKey(this.apiKey, "OpenAI");
	}

	private async readCollection(signal?: AbortSignal): Promise<Record<string, unknown> | null> {
		const response = await this.request("", "GET", undefined, signal, [404]);

		if (response.status === 404) {
			return null;
		}

		const result = qdrantResult(response.body);
		const config = isRecord(result) ? result.config : undefined;
		const params = isRecord(config) ? config.params : undefined;
		const vectors = isRecord(params) ? params.vectors : undefined;
		const compatible = isRecord(vectors) && vectors.size === EMBEDDING_DIMENSIONS && vectors.distance === "Cosine";

		if (!compatible || !isRecord(result)) {
			throw new Error("The Qdrant saved groupings collection is incompatible. Existing data has been preserved.");
		}

		missingIndexes(result);

		return result;
	}

	private async createCollection(signal?: AbortSignal): Promise<Record<string, unknown> | null> {
		const response = await this.request(
			"",
			"PUT",
			{
				vectors: { size: EMBEDDING_DIMENSIONS, distance: "Cosine" },
			},
			signal,
			[400, 409],
		);

		// Another panel may have created it after our first read. Never assume that it is compatible.
		if (response.status === 400 || response.status === 409) {
			const collection = await this.readCollection(signal);

			if (!collection) {
				throw new Error(
					"Qdrant could not create the saved groupings collection. Check write access and try again.",
				);
			}

			return collection;
		}

		if (qdrantResult(response.body) !== true) {
			throw new Error("Qdrant returned an invalid collection creation response.");
		}

		return null;
	}

	private async ensureIndexes(collection: Record<string, unknown> | null, signal?: AbortSignal) {
		// Cloud rejects filters on unindexed fields; create these before points enter the collection.
		for (const index of missingIndexes(collection)) {
			const { body } = await this.request("/index?wait=true", "PUT", index, signal);
			const result = qdrantResult(body);

			if (!isRecord(result) || result.status !== "completed") {
				throw new Error("Qdrant did not confirm saved grouping index setup. Try saving again.");
			}
		}
	}

	private request(
		path: string,
		method: string,
		body?: unknown,
		signal?: AbortSignal,
		allowedStatuses: number[] = [],
	) {
		const url = normalizeQdrantUrl(this.connection.url);
		const key = validateApiKey(this.connection.apiKey, "Qdrant");

		return requestVectorJson(
			`${url}/collections/${SAVED_GROUPINGS_COLLECTION}${path}`,
			{
				method,
				headers: { "api-key": key, "Content-Type": "application/json" },
				body: body === undefined ? undefined : JSON.stringify(body),
			},
			"Qdrant",
			signal,
			allowedStatuses,
		);
	}
}

function missingIndexes(collection: Record<string, unknown> | null) {
	const schema = collection?.payload_schema ?? {};

	if (!isRecord(schema)) {
		throw new Error("Qdrant returned an invalid saved grouping index schema.");
	}

	const missing = [];

	for (const index of SAVED_GROUPINGS_INDEXES) {
		const existing = schema[index.field_name];

		if (existing === undefined) {
			missing.push(index);
			continue;
		}

		if (!isRecord(existing) || existing.data_type !== index.field_schema) {
			throw new Error("The Qdrant saved grouping index is incompatible. Existing data has been preserved.");
		}
	}

	return missing;
}

function qdrantResult(body: unknown): unknown {
	if (!isRecord(body) || body.status !== "ok" || !("result" in body)) {
		throw new Error("Qdrant returned an invalid response.");
	}

	return body.result;
}

function isApprovedGroup(value: unknown): value is ApprovedGroup {
	if (!isRecord(value) || typeof value.name !== "string" || !value.name.trim() || value.name.length > 7) {
		return false;
	}

	const validApprovalTime =
		typeof value.approvedAt === "string" &&
		/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,3})?Z$/.test(value.approvedAt) &&
		!Number.isNaN(Date.parse(value.approvedAt));

	if (!validApprovalTime) {
		return false;
	}

	if (!Array.isArray(value.pages) || value.pages.length === 0 || value.pages.length > 1000) {
		return false;
	}

	return value.pages.every(
		(page) => isRecord(page) && typeof page.title === "string" && typeof page.url === "string",
	);
}

function savedGroupingPayload(group: ApprovedGroup): SavedGrouping {
	return {
		schemaVersion: SCHEMA_VERSION,
		embeddingModel: EMBEDDING_MODEL,
		embeddingDimensions: EMBEDDING_DIMENSIONS,
		name: group.name,
		pages: group.pages.map(({ title, url }) => ({ title, url })),
		approvedAt: group.approvedAt,
	};
}

function groupText(group: ApprovedGroup): string {
	// Browser order and approval time do not change what a group means or its identity.
	const pages = group.pages.map(({ title, url }) => JSON.stringify({ title, url })).sort();

	return JSON.stringify({ name: group.name, pages: pages.map((page) => JSON.parse(page)) });
}

function savedGroupingId(text: string): string {
	// The same grouping gets the same ID, so retries update it instead of creating duplicates.
	return uuidv5(`${SAVED_GROUPINGS_COLLECTION}:${text}`, uuidv5.URL);
}
