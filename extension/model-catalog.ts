import type { ModelOption } from "./types";

// OpenAI catalog checked 2026-10-11: Responses + structured outputs; retired IDs excluded.
// Update from https://developers.openai.com/api/docs/models and /api/docs/deprecations.
// Keep current aliases and one economical older option.
export const SUPPORTED_MODELS: ModelOption[] = [
	{ id: "gpt-6.1-sol", name: "GPT-6.1 Sol" },
	{ id: "gpt-4.1-mini", name: "GPT-4.1 mini" },
	{ id: "gpt-6-astra", name: "GPT-6 Astra" },
	{ id: "gpt-6-luna", name: "GPT-6 Luna" },
	{ id: "gpt-6-sol", name: "GPT-6 Sol" },
	{ id: "gpt-5.6-luna", name: "GPT-5.6 Luna" },
	{ id: "gpt-5.6-sol", name: "GPT-5.6 Sol" },
	{ id: "gpt-5.6-terra", name: "GPT-5.6 Terra" },
	{ id: "gpt-5.5", name: "GPT-5.5" },
	{ id: "gpt-5.5-pro", name: "GPT-5.5 Pro" },
	{ id: "gpt-5.4", name: "GPT-5.4" },
	{ id: "gpt-5.4-mini", name: "GPT-5.4 Mini" },
	{ id: "gpt-5.4-nano", name: "GPT-5.4 nano" },
	{ id: "gpt-5.2", name: "GPT-5.2" },
	{ id: "gpt-5-mini", name: "GPT-5 Mini" },
].map((model) => ({
	...model,
	note:
		model.id === "gpt-4.1-mini"
			? "Fast and affordable for grouping tabs."
			: "Supports tab grouping. Test the connection to verify access with your key.",
}));
