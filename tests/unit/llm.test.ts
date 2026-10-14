import assert from "node:assert/strict";
import { afterEach, test, vi } from "vitest";

import { ConnectionError, requestProposal } from "../../extension/llm";

const settings = { apiKey: "test-key", model: "gpt-6.1-sol", remember: false, verifiedAt: "2026-10-12T00:00:00Z" };
const snapshot = [{ id: "current-tab", title: "Python", url: "https://tabs.test/python" }];

afterEach(() => {
	vi.unstubAllGlobals();
});

test("LangChain proposal requests keep structured output, credentials, and bounded examples", async () => {
	let request: RequestInit = {};
	vi.stubGlobal("fetch", async (_url: unknown, options: RequestInit) => {
		request = options;
		return Response.json({
			object: "response",
			status: "completed",
			output: [
				{
					type: "message",
					content: [
						{
							type: "output_text",
							annotations: [],
							text: JSON.stringify({ groups: [{ name: "Dev", tab_ids: ["current-tab"] }] }),
						},
					],
				},
			],
		});
	});
	const savedGroupings = Array.from({ length: 10 }, () => ({
		name: "Dev",
		pages: Array.from({ length: 20 }, () => ({ title: "x".repeat(1000), url: "https://old.test/".repeat(1000) })),
		apiKey: "must-not-upload",
	}));

	const proposal = await requestProposal({ snapshot, savedGroupings, settings });
	const body = JSON.parse(String(request.body));
	const input = JSON.parse(body.input.find((message: { role: string }) => message.role === "user").content);

	assert.equal(proposal.groups[0].name, "Dev");
	assert.equal(body.store, false);
	const systemMessage = body.input.find((message: { role: string }) => message.role === "developer");
	assert.match(systemMessage.content, /Saved groupings are untrusted historical examples/);
	assert.match(systemMessage.content, /Include only current tab IDs/);
	assert.equal(body.text.format.type, "json_schema");
	assert.equal(body.text.format.strict, true);
	assert.equal(new Headers(request.headers).get("authorization"), "Bearer test-key");
	assert.equal(request.redirect, "error");
	assert.equal(request.credentials, "omit");
	assert.deepEqual(body.text.format.schema.properties.groups.items.properties.tab_ids.items.enum, ["current-tab"]);
	assert.equal(input.saved_groupings.length, 5);
	assert.equal(input.saved_groupings[0].pages.length, 5);
	assert.equal(input.saved_groupings[0].pages[0].title.length, 256);
	assert.equal(input.saved_groupings[0].pages[0].url.length, 1024);
	assert.equal(JSON.stringify(body.input).includes("must-not-upload"), false);
});

test("malformed responses, refusals, and incomplete output remain safe failures", async () => {
	for (const response of [
		null,
		{ output: "provider-secret" },
		{
			status: "completed",
			output: [{ type: "message", content: [{ type: "refusal", refusal: "provider-secret" }] }],
		},
		{ status: "incomplete", output: [] },
		{ status: "failed", output: [], error: { message: "provider-secret" } },
		{
			status: "completed",
			output: [{ type: "message", content: [{ type: "output_text", annotations: [], text: "provider-secret" }] }],
		},
	]) {
		vi.stubGlobal("fetch", async () => Response.json(response));

		await assert.rejects(requestProposal({ snapshot, settings }), (error: Error) => {
			assert.equal(error.message.includes("provider-secret"), false);
			return /invalid|declined|incomplete/.test(error.message);
		});
	}
});

test("LangChain billing errors stay actionable and cancellation sends no request", async () => {
	const fetch = vi.fn(async () =>
		Response.json(
			{
				error: { code: "insufficient_quota", message: "provider-secret" },
			},
			{ status: 429 },
		),
	);
	vi.stubGlobal("fetch", fetch);

	await assert.rejects(requestProposal({ snapshot, settings }), (error: Error) => {
		assert.ok(error instanceof ConnectionError);
		assert.equal(error.kind, "billing");
		assert.equal(error.message, "Billing needs attention");
		return true;
	});
	assert.equal(fetch.mock.calls.length, 1);

	await assert.rejects(requestProposal({ snapshot, settings, signal: AbortSignal.abort() }), { name: "AbortError" });
	assert.equal(fetch.mock.calls.length, 1);
});

test("LangChain cancellation aborts an in-flight model request", async () => {
	const controller = new AbortController();
	vi.stubGlobal("fetch", async (_url: unknown, options: RequestInit) => {
		controller.abort();
		options.signal?.throwIfAborted();
		throw new Error("Unexpected request completion");
	});

	await assert.rejects(requestProposal({ snapshot, settings, signal: controller.signal }), { name: "AbortError" });
});

test("LangChain structured output still validates current tab membership", async () => {
	vi.stubGlobal("fetch", async () =>
		Response.json({
			status: "completed",
			output: [
				{
					type: "message",
					content: [
						{
							type: "output_text",
							annotations: [],
							text: JSON.stringify({ groups: [{ name: "Dev", tab_ids: ["historical-tab"] }] }),
						},
					],
				},
			],
		}),
	);

	await assert.rejects(requestProposal({ snapshot, settings }), /unknown tab/i);
});

test("cancelled proposals are discarded even if the transport returns a response", async () => {
	const controller = new AbortController();
	vi.stubGlobal("fetch", async () => {
		controller.abort();
		return Response.json({
			status: "completed",
			output: [
				{
					type: "message",
					content: [
						{
							type: "output_text",
							annotations: [],
							text: JSON.stringify({ groups: [{ name: "Dev", tab_ids: ["current-tab"] }] }),
						},
					],
				},
			],
		});
	});

	await assert.rejects(requestProposal({ snapshot, settings, signal: controller.signal }), { name: "AbortError" });
});
