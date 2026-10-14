import { ChatOpenAI } from "@langchain/openai";

import type { Connection, Proposal } from "./types";

export const PROPOSAL_TIMEOUT_MS = 2 * 60 * 1000;

// Provider configuration stays here; grouping uses LangChain messages and structured output.
export function createGroupingModel(connection: Pick<Connection, "apiKey" | "model">, schema: Record<string, unknown>) {
	const model = new ChatOpenAI({
		apiKey: connection.apiKey,
		model: connection.model,
		useResponsesApi: true,
		modelKwargs: { store: false },
		maxRetries: 0,
		timeout: PROPOSAL_TIMEOUT_MS,
		configuration: {
			// The key belongs to the user and is used only in the extension panel.
			dangerouslyAllowBrowser: true,
			fetch: (url, options) => globalThis.fetch(url, { ...options, redirect: "error", credentials: "omit" }),
		},
	});

	return model.withStructuredOutput<Proposal>(schema, {
		name: "tab_groups",
		method: "jsonSchema",
		strict: true,
		includeRaw: true,
	});
}
