import assert from "node:assert/strict";
import { afterEach, test } from "node:test";

import { embedTexts, EMBEDDING_DIMENSIONS, EMBEDDING_MODEL } from "../../extension/embeddings";
import { GroupingVectorStore, MEMORY_COLLECTION } from "../../extension/vector-store";

const connection = {
	url: "https://test.cloud.qdrant.io:6333/",
	apiKey: "qdrant-test-key",
	remember: false,
	verifiedAt: "2026-10-12T12:00:00.000Z",
};
const group = {
	name: "Dev",
	pages: [
		{ title: "Python", url: "https://tabs.test/python" },
		{ title: "TypeScript", url: "https://tabs.test/typescript" },
	],
	approvedAt: "2026-10-12T12:00:00.000Z",
};
const originalFetch = globalThis.fetch;
const originalTimeout = AbortSignal.timeout;
const vector = (): number[] => Array.from({ length: EMBEDDING_DIMENSIONS }, (_, index) => (index === 0 ? 1 : 0));
const ok = (result: unknown) => Response.json({ status: "ok", result });
const payloadSchema = {
	schemaVersion: { data_type: "integer" },
	embeddingModel: { data_type: "keyword" },
	embeddingDimensions: { data_type: "integer" },
};
const compatibleCollection = (indexes: unknown = payloadSchema) =>
	ok({
		config: { params: { vectors: { size: 1536, distance: "Cosine" } } },
		payload_schema: indexes,
	});
const embeddingResponse = (count = 1) =>
	Response.json({
		model: EMBEDDING_MODEL,
		data: Array.from({ length: count }, (_, index) => ({ index, embedding: vector() })),
	});

type Request = { url: string; method: string; body: any; headers: Headers; options: RequestInit };

function mockNetwork(respond: (request: Request) => Response | Promise<Response>) {
	const requests: Request[] = [];

	globalThis.fetch = async (url, options = {}) => {
		const request = {
			url: String(url),
			method: options.method || "GET",
			body: options.body ? JSON.parse(String(options.body)) : undefined,
			headers: new Headers(options.headers),
			options,
		};

		requests.push(request);
		return respond(request);
	};

	return requests;
}

function store() {
	return new GroupingVectorStore(connection, "openai-test-key");
}

function savedPayload(overrides = {}) {
	return {
		schemaVersion: 1,
		embeddingModel: EMBEDDING_MODEL,
		embeddingDimensions: EMBEDDING_DIMENSIONS,
		...group,
		...overrides,
	};
}

afterEach(() => {
	globalThis.fetch = originalFetch;
	AbortSignal.timeout = originalTimeout;
});

test("malformed embeddings are rejected before any database write", async () => {
	for (const data of [
		[],
		[{ index: 0, embedding: [1] }],
		[{ index: 0, embedding: vector().fill(0) }],
		[{ index: 0, embedding: Array(1536).fill(null) }],
		[{ index: 2, embedding: vector() }],
		[
			{ index: 0, embedding: vector() },
			{ index: 0, embedding: vector() },
		],
	]) {
		const requests = mockNetwork((request) => {
			if (request.url.includes("openai.com")) {
				return Response.json({ model: EMBEDDING_MODEL, data });
			}

			return compatibleCollection();
		});

		await assert.rejects(store().saveGroups([group]), /invalid embedding/i);
		assert.equal(requests.filter((request) => request.method === "PUT").length, 0);
	}
});

test("missing collection is created, then groups are saved with isolated credentials", async () => {
	const requests = mockNetwork((request) => {
		if (request.url.includes("openai.com")) {
			return embeddingResponse(request.body.input.length);
		}

		if (request.method === "GET") {
			return new Response("", { status: 404 });
		}

		if (request.url.endsWith("?wait=true")) {
			return ok({ status: "completed", operation_id: 1 });
		}

		return ok(true);
	});
	const other = { ...group, name: "Food", pages: [{ title: "Pasta", url: "https://tabs.test/pasta" }] };

	const ids = await store().saveGroups([group, other]);

	const writes = requests.filter((request) => request.method === "PUT");
	assert.equal(writes.length, 5);
	assert.equal(writes[0].url, `${connection.url.slice(0, -1)}/collections/${MEMORY_COLLECTION}`);
	assert.deepEqual(writes[0].body, { vectors: { size: 1536, distance: "Cosine" } });
	assert.deepEqual(
		writes.slice(1, 4).map((request) => request.body),
		[
			{ field_name: "schemaVersion", field_schema: "integer" },
			{ field_name: "embeddingModel", field_schema: "keyword" },
			{ field_name: "embeddingDimensions", field_schema: "integer" },
		],
	);
	assert.equal(writes[4].body.points.length, 2);
	assert.deepEqual(writes[4].body.points[0].payload, savedPayload());
	assert.deepEqual(writes[4].body.points[0].vector, vector());
	assert.deepEqual(
		writes[4].body.points.map((point: any) => point.id),
		ids,
	);
	assert.match(ids[0], /^[0-9a-f]{8}-[0-9a-f]{4}-5[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);

	for (const request of requests) {
		if (request.url.includes("openai.com")) {
			assert.equal(request.headers.has("api-key"), false);
		} else {
			assert.equal(request.headers.get("api-key"), "qdrant-test-key");
			assert.equal(request.headers.has("authorization"), false);
		}

		assert.equal(JSON.stringify(request.body ?? {}).includes("test-key"), false);
	}
});

test("reusing a collection and retrying a save does not create duplicate identities", async () => {
	const requests = mockNetwork((request) => {
		if (request.url.includes("openai.com")) {
			return embeddingResponse();
		}

		if (request.method === "GET") {
			return compatibleCollection();
		}

		return ok({ status: "completed" });
	});

	const first = await store().saveGroups([group]);
	const retry = await store().saveGroups([
		{ ...group, pages: [...group.pages].reverse(), approvedAt: "2026-10-13T00:00:00Z" },
	]);
	const changed = await store().saveGroups([{ ...group, name: "Code" }]);

	assert.deepEqual(first, retry);
	assert.notDeepEqual(first, changed);
	assert.equal(requests.filter((request) => request.method === "PUT" && !request.url.includes("/points")).length, 0);
});

test("incompatible collections are never modified", async () => {
	for (const vectors of [
		{ size: 3, distance: "Cosine" },
		{ size: 1536, distance: "Dot" },
		{ named: { size: 1536 } },
	]) {
		const requests = mockNetwork(() => ok({ config: { params: { vectors } } }));

		await assert.rejects(store().saveGroups([group]), /incompatible/i);
		assert.equal(requests.length, 1);
		assert.equal(requests[0].method, "GET");
	}
});

test("concurrent collection creation rechecks compatibility", async () => {
	let reads = 0;
	const requests = mockNetwork((request) => {
		if (request.url.includes("openai.com")) {
			return embeddingResponse();
		}

		if (request.method === "GET") {
			reads += 1;
			return reads === 1 ? new Response("", { status: 404 }) : compatibleCollection();
		}

		if (!request.url.includes("/points")) {
			return new Response("already exists", { status: 409 });
		}

		return ok({ status: "completed" });
	});

	await store().saveGroups([group]);
	assert.equal(reads, 2);
	assert.equal(requests.at(-1)?.url.endsWith("/points?wait=true"), true);
});

test("search sends a bounded query with schema/model filtering and preserves ranked scores", async () => {
	const requests = mockNetwork((request) => {
		if (request.url.includes("openai.com")) {
			return embeddingResponse();
		}

		if (request.method === "GET") {
			return compatibleCollection();
		}

		return ok({
			points: [
				{ id: "first", score: 0.9, payload: savedPayload() },
				{ id: "incompatible", score: 0.85, payload: savedPayload({ embeddingModel: "another-model" }) },
				{ id: "second", score: 0.8, payload: savedPayload({ name: "Code" }) },
			],
		});
	});

	const matches = await store().search("Python development", 3);

	assert.deepEqual(
		matches.map((match) => [match.id, match.score]),
		[
			["first", 0.9],
			["second", 0.8],
		],
	);
	assert.deepEqual(requests[1].body.input, ["Python development"]);
	assert.equal(requests[2].url.endsWith("/points/query"), true);
	assert.deepEqual(requests[2].body, {
		query: vector(),
		limit: 3,
		with_payload: true,
		with_vector: false,
		filter: {
			must: [
				{ key: "schemaVersion", match: { value: 1 } },
				{ key: "embeddingModel", match: { value: EMBEDDING_MODEL } },
				{ key: "embeddingDimensions", match: { value: 1536 } },
			],
		},
	});
});

test("searching a missing collection returns no matches without creating it or embedding", async () => {
	const requests = mockNetwork(() => new Response("", { status: 404 }));

	assert.deepEqual(await store().search("Python"), []);
	assert.equal(requests.length, 1);
	assert.equal(requests[0].method, "GET");
});

test("empty search results are valid, malformed envelopes and records are rejected", async () => {
	for (const result of [
		{ points: [] },
		{},
		{ points: [{ id: "bad", score: "secret", payload: savedPayload() }] },
		{ points: [{ id: "bad", score: 0.5, payload: savedPayload({ pages: [null] }) }] },
	]) {
		mockNetwork((request) => {
			if (request.url.includes("openai.com")) {
				return embeddingResponse();
			}

			if (request.method === "GET") {
				return compatibleCollection();
			}

			return ok(result);
		});

		if (result.points?.length === 0) {
			assert.deepEqual(await store().search("Python"), []);
		} else {
			await assert.rejects(store().search("Python"), /invalid/i);
		}
	}
});

test("invalid inputs and credentials fail before network access", async () => {
	const requests = mockNetwork(() => {
		throw new Error("Unexpected network access");
	});

	for (const input of [
		{ ...group, name: "" },
		{ ...group, pages: [] },
		{ ...group, approvedAt: "invalid" },
	]) {
		await assert.rejects(store().saveGroups([input]), /invalid/i);
	}

	for (const limit of [0, -1, 21, 1.5]) {
		await assert.rejects(store().search("Python", limit), /limit/i);
	}

	await assert.rejects(store().search(" "), /query/i);
	await assert.rejects(embedTexts([""], "openai-test-key"), /input/i);
	await assert.rejects(embedTexts(["Python"], "bad\nkey"), /key/i);
	await assert.rejects(
		new GroupingVectorStore({ ...connection, url: "https://evil.test" }, "key").saveGroups([group]),
	);
	await assert.rejects(
		new GroupingVectorStore({ ...connection, verifiedAt: null }, "key").saveGroups([group]),
		/connection/i,
	);
	await assert.rejects(
		new GroupingVectorStore({ ...connection, apiKey: "bad\nkey" }, "key").saveGroups([group]),
		/key/i,
	);
	assert.deepEqual(await store().saveGroups([]), []);
	assert.equal(requests.length, 0);
});

test("API failures are sanitized for both services", async () => {
	for (const status of [401, 403, 429, 500]) {
		mockNetwork(() => Response.json({ error: { message: "provider-secret" } }, { status }));

		await assert.rejects(embedTexts(["Python"], "openai-test-key"), (error: Error) => {
			assert.equal(error.message.includes("provider-secret"), false);
			return /OpenAI/.test(error.message);
		});
		await assert.rejects(store().saveGroups([group]), (error: Error) => {
			assert.equal(error.message.includes("provider-secret"), false);
			return /Qdrant/.test(error.message);
		});
	}
});

test("unconfirmed writes and malformed JSON are not reported as successful saves", async () => {
	for (const result of [{ status: "acknowledged" }, true, null]) {
		mockNetwork((request) => {
			if (request.url.includes("openai.com")) {
				return embeddingResponse();
			}

			return request.method === "GET" ? compatibleCollection() : ok(result);
		});

		await assert.rejects(store().saveGroups([group]), /confirm/i);
	}

	mockNetwork(() => new Response("not-json-provider-secret"));
	await assert.rejects(store().search("Python"), /invalid response/i);
	await assert.rejects(embedTexts(["Python"], "key"), /invalid response/i);
});

test("cancellation and network failures are distinguished from provider responses", async () => {
	const controller = new AbortController();
	controller.abort();
	const requests = mockNetwork(() => {
		throw new Error("Unexpected network access");
	});

	await assert.rejects(store().saveGroups([group], controller.signal), { name: "AbortError" });
	await assert.rejects(embedTexts(["Python"], "key", controller.signal), { name: "AbortError" });
	assert.equal(requests.length, 0);

	mockNetwork(() => {
		throw new TypeError("secret network error");
	});
	await assert.rejects(store().search("Python"), /Could not connect to Qdrant/);
	await assert.rejects(embedTexts(["Python"], "key"), /Could not connect to OpenAI/);
});

test("missing payload indexes are repaired before saving, without replacing existing indexes", async () => {
	const requests = mockNetwork((request) => {
		if (request.url.includes("openai.com")) {
			return embeddingResponse();
		}

		if (request.method === "GET") {
			return compatibleCollection({ embeddingModel: { data_type: "keyword" } });
		}

		return ok({ status: "completed" });
	});

	await store().saveGroups([group]);

	const indexes = requests.filter((request) => request.url.endsWith("/index?wait=true"));
	assert.deepEqual(
		indexes.map((request) => request.body.field_name),
		["schemaVersion", "embeddingDimensions"],
	);
	assert.equal(requests.at(-1)?.url.endsWith("/points?wait=true"), true);
});

test("incompatible indexes and unconfirmed index setup prevent point writes", async () => {
	for (const schema of [{ ...payloadSchema, embeddingModel: { data_type: "integer" } }, {}]) {
		const requests = mockNetwork((request) => {
			if (request.url.includes("openai.com")) {
				return embeddingResponse();
			}

			return request.method === "GET" ? compatibleCollection(schema) : ok({ status: "acknowledged" });
		});

		await assert.rejects(store().saveGroups([group]), /incompatible|confirm/i);
		assert.equal(
			requests.some((request) => request.url.includes("/points")),
			false,
		);
	}
});

test("concurrent creation with an incompatible winner never upserts points", async () => {
	let reads = 0;
	const requests = mockNetwork((request) => {
		if (request.url.includes("openai.com")) {
			return embeddingResponse();
		}

		if (request.method === "GET") {
			reads += 1;
			return reads === 1
				? new Response("", { status: 404 })
				: ok({ config: { params: { vectors: { size: 3 } } } });
		}

		return new Response("provider-secret", { status: 400 });
	});

	await assert.rejects(store().saveGroups([group]), /incompatible/i);
	assert.equal(
		requests.some((request) => request.url.includes("/points")),
		false,
	);
});

test("only approved group fields are embedded or stored, including when callers supply extra data", async () => {
	const requests = mockNetwork((request) => {
		if (request.url.includes("openai.com")) {
			return embeddingResponse();
		}

		return request.method === "GET" ? compatibleCollection() : ok({ status: "completed" });
	});

	await store().saveGroups([
		{
			...group,
			apiKey: "must-not-upload",
			chrome_id: 123,
			pages: group.pages.map((page) => ({ ...page, chrome_id: 456, contents: "must-not-upload" })),
		} as typeof group,
	]);

	assert.equal(JSON.stringify(requests.map((request) => request.body)).includes("must-not-upload"), false);
	assert.equal(JSON.stringify(requests.map((request) => request.body)).includes("chrome_id"), false);
});

test("embedding failures never write collections or points", async () => {
	for (const response of [
		Response.json({ model: "wrong-model", data: [{ index: 0, embedding: vector() }] }),
		Response.json({ error: { message: "provider-secret" } }, { status: 401 }),
	]) {
		const requests = mockNetwork((request) =>
			request.url.includes("openai.com") ? response : new Response("", { status: 404 }),
		);

		await assert.rejects(store().saveGroups([group]));
		assert.equal(
			requests.some((request) => request.method === "PUT"),
			false,
		);
	}
});

test("timeouts have actionable messages without leaking response bodies", async () => {
	AbortSignal.timeout = () => AbortSignal.abort(new DOMException("provider-secret", "TimeoutError"));
	const requests = mockNetwork(() => {
		throw new Error("Unexpected network access");
	});

	await assert.rejects(embedTexts(["Python"], "key"), /OpenAI timed out/);
	await assert.rejects(store().saveGroups([group]), /Qdrant timed out/);
	assert.equal(requests.length, 0);
});

test("cancellation during embedding prevents every database mutation", async () => {
	const controller = new AbortController();
	const requests = mockNetwork((request) => {
		if (request.url.includes("openai.com")) {
			controller.abort();
			return embeddingResponse();
		}

		return new Response("", { status: 404 });
	});

	await assert.rejects(store().saveGroups([group], controller.signal), { name: "AbortError" });
	assert.equal(
		requests.some((request) => request.method === "PUT"),
		false,
	);
});

test("retry after an uncertain write overwrites the same point instead of duplicating it", async () => {
	const points = new Map<string, unknown>();
	let writes = 0;
	mockNetwork((request) => {
		if (request.url.includes("openai.com")) {
			return embeddingResponse();
		}

		if (request.method === "GET") {
			return compatibleCollection();
		}

		writes += 1;

		for (const point of request.body.points) {
			points.set(point.id, point);
		}

		if (writes === 1) {
			return new Response("provider-secret", { status: 503 });
		}

		return ok({ status: "completed" });
	});

	await assert.rejects(store().saveGroups([group]), /Qdrant request failed/);
	const [savedId] = await store().saveGroups([group]);

	assert.equal(points.size, 1);
	assert.equal(points.has(savedId), true);
	assert.equal(writes, 2);
});

test("search with missing indexes stays read-only and reports how to finish setup", async () => {
	const requests = mockNetwork(() => compatibleCollection({}));

	await assert.rejects(store().search("Python"), /indexes are missing/);
	assert.equal(requests.length, 1);
	assert.equal(requests[0].method, "GET");
});
