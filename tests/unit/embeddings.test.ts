import assert from "node:assert/strict";
import { afterEach, test } from "vitest";

import { embedTexts, EMBEDDING_DIMENSIONS, EMBEDDING_MODEL } from "../../extension/embeddings";

const originalFetch = globalThis.fetch;
const originalTimeout = AbortSignal.timeout;
const vector = (): number[] => Array.from({ length: EMBEDDING_DIMENSIONS }, (_, index) => (index === 0 ? 1 : 0));

afterEach(() => {
	globalThis.fetch = originalFetch;
	AbortSignal.timeout = originalTimeout;
});

test("embeddings use explicit float dimensions and map response indices to inputs", async () => {
	let requestUrl;
	let requestOptions: RequestInit = {};
	globalThis.fetch = async (url, options = {}) => {
		requestUrl = String(url);
		requestOptions = options;
		return Response.json({
			model: EMBEDDING_MODEL,
			data: [
				{ index: 1, embedding: vector().fill(0.5) },
				{ index: 0, embedding: vector() },
			],
		});
	};

	const result = await embedTexts(["Python", "Recipes"], "openai-test-key");

	assert.equal(result[0][0], 1);
	assert.equal(result[1][0], 0.5);
	assert.equal(requestUrl, "https://api.openai.com/v1/embeddings");
	assert.equal(requestOptions.method, "POST");
	assert.equal(new Headers(requestOptions.headers).get("authorization"), "Bearer openai-test-key");
	assert.deepEqual(JSON.parse(String(requestOptions.body)), {
		model: "text-embedding-3-small",
		dimensions: 1536,
		encoding_format: "float",
		input: ["Python", "Recipes"],
	});
	assert.equal(requestOptions.redirect, "error");
	assert.equal(requestOptions.credentials, "omit");
});

test("invalid embedding batches are rejected instead of returning usable vectors", async () => {
	for (const data of [
		[],
		[{ index: 0, embedding: [1] }],
		[{ index: 0, embedding: vector().fill(0) }],
		[{ index: 0, embedding: Array(1536).fill(null) }],
		[{ index: 2, embedding: vector() }],
	]) {
		globalThis.fetch = async () => Response.json({ model: EMBEDDING_MODEL, data });

		await assert.rejects(embedTexts(["Python"], "key"), /invalid embedding/i);
	}
});

test("empty inputs and invalid keys make no requests", async () => {
	globalThis.fetch = async () => {
		throw new Error("Unexpected network access");
	};

	await assert.rejects(embedTexts([], "key"), /input/i);
	await assert.rejects(embedTexts([" "], "key"), /input/i);
	for (const key of ["", "bad\nkey", "bad key", "badékey"]) {
		await assert.rejects(embedTexts(["Python"], key), /key/i);
	}
});

test("HTTP failures, invalid JSON, and wrong models use safe error messages", async () => {
	for (const status of [401, 403, 429, 500]) {
		globalThis.fetch = async () => Response.json({ error: { message: "provider-secret" } }, { status });

		await assert.rejects(embedTexts(["Python"], "key"), (error: Error) => {
			assert.equal(error.message.includes("provider-secret"), false);
			return /OpenAI/.test(error.message);
		});
	}

	globalThis.fetch = async () =>
		new Response("not-json-provider-secret", { headers: { "Content-Type": "application/json" } });
	await assert.rejects(embedTexts(["Python"], "key"), /invalid response/i);

	globalThis.fetch = async () => Response.json({ model: "wrong-model", data: [{ index: 0, embedding: vector() }] });
	await assert.rejects(embedTexts(["Python"], "key"), /invalid embedding/i);
});

test("timeouts, cancellation, and network failures remain distinguishable", async () => {
	globalThis.fetch = async () => {
		throw new TypeError("secret network details");
	};
	await assert.rejects(embedTexts(["Python"], "key"), /Could not connect to OpenAI/);

	await assert.rejects(embedTexts(["Python"], "key", AbortSignal.abort()), { name: "AbortError" });

	AbortSignal.timeout = () => AbortSignal.abort(new DOMException("provider-secret", "TimeoutError"));
	await assert.rejects(embedTexts(["Python"], "key"), /OpenAI timed out/);
});

test("LangChain preserves embedding text and aborts an in-flight request", async () => {
	const text = "Python\nTutorial";
	globalThis.fetch = async (_url, options = {}) => {
		assert.deepEqual(JSON.parse(String(options.body)).input, [text]);
		return Response.json({ model: EMBEDDING_MODEL, data: [{ index: 0, embedding: vector() }] });
	};

	await embedTexts([text], "key");

	const controller = new AbortController();
	globalThis.fetch = async (_url, options = {}) => {
		controller.abort();
		options.signal?.throwIfAborted();
		throw new Error("Unexpected request completion");
	};

	await assert.rejects(embedTexts([text], "key", controller.signal), { name: "AbortError" });
});

test("embedding indices must be unique and cover a complete batch", async () => {
	for (const indices of [
		[0, 0],
		[1, 1],
		[0, 2],
		[-1, 1],
		[0, 0.5],
	]) {
		globalThis.fetch = async () =>
			Response.json({
				model: EMBEDDING_MODEL,
				data: indices.map((index) => ({ index, embedding: vector() })),
			});

		await assert.rejects(embedTexts(["Python", "Recipes"], "key"), /invalid embeddings/i);
	}
});

test("cancelled embeddings are discarded even if the transport returns a response", async () => {
	const controller = new AbortController();
	globalThis.fetch = async () => {
		controller.abort();
		return Response.json({ model: EMBEDDING_MODEL, data: [{ index: 0, embedding: vector() }] });
	};

	await assert.rejects(embedTexts(["Python"], "key", controller.signal), { name: "AbortError" });
});
