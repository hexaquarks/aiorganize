import type { QdrantConnection } from "./types";

import { v5 as uuidv5, validate as isUuid } from "uuid";
import { QdrantClient } from "@qdrant/js-client-rest";

import { embedTexts, EMBEDDING_DIMENSIONS, EMBEDDING_MODEL } from "./embeddings";
import { normalizeQdrantUrl } from "./qdrant";
import { hasStatus, isRecord, runVectorRequest, validateApiKey } from "./vector-requests";

const USER_COLLECTION = "aiorganize_groups_v1_text_embedding_3_small_1536";
export const SAVED_GROUPINGS_COLLECTION =
	import.meta.env.MODE === "qdrant-test" ? `${USER_COLLECTION}_test` : USER_COLLECTION;
const SCHEMA_VERSION = 1;
const SAVED_GROUPINGS_INDEXES = [
	{ field_name: "userId", field_schema: "keyword" },
	{ field_name: "schemaVersion", field_schema: "integer" },
	{ field_name: "embeddingModel", field_schema: "keyword" },
	{ field_name: "embeddingDimensions", field_schema: "integer" },
] as const;

export interface ApprovedGroup {
	name: string;
	pages: { title: string; url: string }[];
	approvedAt: string;
}

export interface SavedGrouping extends ApprovedGroup {
	userId: string;
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
	private readonly userId: string;

	constructor(connection: QdrantConnection, apiKey: string, userId: string) {
		if (!isUuid(userId)) {
			throw new Error("A valid user identity is required for saved groupings.");
		}

		this.connection = { ...connection };
		this.apiKey = apiKey;
		this.userId = userId;
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
		const savedGroupings = groups.map((group) => savedGroupingPayload(group, this.userId));
		const texts = savedGroupings.map(groupText);

		const client = this.client();
		let collection = await this.readCollection(client, signal);
		const vectors = await embedTexts(texts, this.apiKey, signal);
		const ids = texts.map((text) => savedGroupingId(text, this.userId));

		// Validate embeddings before creating a collection or making any database write.
		if (!collection) {
			collection = await this.createCollection(client, signal);
		}

		await this.ensureIndexes(client, collection, signal);

		const points = savedGroupings.map((payload, index) => ({
			id: ids[index],
			vector: vectors[index],
			payload: { ...payload },
		}));
		const response = await runVectorRequest("Qdrant", signal, (options) =>
			client.api().upsertPoints(
				{
					collection_name: SAVED_GROUPINGS_COLLECTION,
					wait: true,
					points,
				},
				options,
			),
		);
		const result = qdrantResult(response.data);

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

		const client = this.client();

		const collection = await this.readCollection(client, signal);

		if (!collection) {
			return [];
		}

		if (missingIndexes(collection).length) {
			throw new Error("Saved grouping search indexes are missing. Save an approved group to finish setup.");
		}

		const [vector] = await embedTexts([query], this.apiKey, signal);
		const response = await runVectorRequest("Qdrant", signal, (options) =>
			client.api().queryPoints(
				{
					collection_name: SAVED_GROUPINGS_COLLECTION,
					query: vector,
					limit,
					with_payload: true,
					with_vector: false,
					filter: {
						must: [
							{ key: "userId", match: { value: this.userId } },
							{ key: "schemaVersion", match: { value: SCHEMA_VERSION } },
							{ key: "embeddingModel", match: { value: EMBEDDING_MODEL } },
							{ key: "embeddingDimensions", match: { value: EMBEDDING_DIMENSIONS } },
						],
					},
				},
				options,
			),
		);
		const result = qdrantResult(response.data);

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

			// Never pass another user's record or older records without an owner to the model.
			if (payload.userId !== this.userId) {
				continue;
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

			matches.push({
				id: point.id,
				score: point.score,
				savedGrouping: savedGroupingPayload(payload, this.userId),
			});
		}

		return matches;
	}

	private client(): QdrantClient {
		if (!this.connection.verifiedAt) {
			throw new Error("Test and save your Qdrant connection before using saved groupings.");
		}

		const url = normalizeQdrantUrl(this.connection.url);
		const apiKey = validateApiKey(this.connection.apiKey, "Qdrant");

		validateApiKey(this.apiKey, "OpenAI");

		return new QdrantClient({
			url,
			apiKey,
			port: null,
			checkCompatibility: false,
			// Its generated API accepts our per-request signal. The SDK timeout would replace that signal.
			timeout: Infinity,
		});
	}

	private async readCollection(client: QdrantClient, signal?: AbortSignal): Promise<Record<string, unknown> | null> {
		const response = await runVectorRequest("Qdrant", signal, async (options) => {
			try {
				return await client.api().getCollection({ collection_name: SAVED_GROUPINGS_COLLECTION }, options);
			} catch (error) {
				if (hasStatus(error, 404)) {
					return null;
				}

				throw error;
			}
		});

		if (!response) {
			return null;
		}

		const result = qdrantResult(response.data);
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

	private async createCollection(
		client: QdrantClient,
		signal?: AbortSignal,
	): Promise<Record<string, unknown> | null> {
		const response = await runVectorRequest("Qdrant", signal, async (options) => {
			try {
				return await client.api().createCollection(
					{
						collection_name: SAVED_GROUPINGS_COLLECTION,
						vectors: { size: EMBEDDING_DIMENSIONS, distance: "Cosine" },
					},
					options,
				);
			} catch (error) {
				if (hasStatus(error, 400) || hasStatus(error, 409)) {
					return null;
				}

				throw error;
			}
		});

		// Another panel may have created it after our first read. Check it before writing points.
		if (!response) {
			const collection = await this.readCollection(client, signal);

			if (!collection) {
				throw new Error(
					"Qdrant could not create the saved groupings collection. Check write access and try again.",
				);
			}

			return collection;
		}

		if (qdrantResult(response.data) !== true) {
			throw new Error("Qdrant returned an invalid collection creation response.");
		}

		return null;
	}

	private async ensureIndexes(
		client: QdrantClient,
		collection: Record<string, unknown> | null,
		signal?: AbortSignal,
	) {
		// Cloud rejects filters on unindexed fields; create these before points enter the collection.
		for (const index of missingIndexes(collection)) {
			const response = await runVectorRequest("Qdrant", signal, (options) =>
				client.api().createFieldIndex(
					{
						collection_name: SAVED_GROUPINGS_COLLECTION,
						wait: true,
						...index,
					},
					options,
				),
			);
			const result = qdrantResult(response.data);

			if (!isRecord(result) || result.status !== "completed") {
				throw new Error("Qdrant did not confirm saved grouping index setup. Try saving again.");
			}
		}
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

function savedGroupingPayload(group: ApprovedGroup, userId: string): SavedGrouping {
	return {
		userId,
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
	const pages = group.pages.map(({ title, url }) => ({ title, url }));

	pages.sort((left, right) => {
		// Keep the original ordering for escaped titles and URLs, preserving saved IDs.
		const leftText = JSON.stringify(left);
		const rightText = JSON.stringify(right);

		if (leftText === rightText) {
			return 0;
		}

		return leftText < rightText ? -1 : 1;
	});

	return JSON.stringify({ name: group.name, pages });
}

function savedGroupingId(text: string, userId: string): string {
	// The same grouping gets the same ID, so retries update it instead of creating duplicates.
	return uuidv5(`${SAVED_GROUPINGS_COLLECTION}:${userId}:${text}`, uuidv5.URL);
}
