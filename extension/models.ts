import type { ModelOption } from "./types";

import { SUPPORTED_MODELS } from "./model-catalog";

const MODEL_LIST_TIMEOUT_MS = 20_000;

export class ModelListError extends Error {}

export async function fetchModels(apiKey: string, signal?: AbortSignal): Promise<ModelOption[]> {
	const signals: AbortSignal[] = [];

	if (signal) {
		signals.push(signal);
	}

	signals.push(AbortSignal.timeout(MODEL_LIST_TIMEOUT_MS));

	const requestSignal = AbortSignal.any(signals);

	const response = await fetch("https://api.openai.com/v1/models", {
		headers: { Authorization: `Bearer ${apiKey}` },
		signal: requestSignal,
		redirect: "error",
		credentials: "omit",
	});

	// Never expose provider error bodies, which can contain sensitive data.
	if (!response.ok) {
		const messages: Record<number, string> = {
			401: "OpenAI rejected the key (401). Edit your key and refresh.",
			403: "OpenAI denied model-list access (403). Check the key’s Models read permission and project access.",
			429: "OpenAI rate-limited model lookup (429). Try refreshing shortly.",
		};

		throw new ModelListError(
			messages[response.status] || `OpenAI could not list models (HTTP ${response.status}). Try refreshing.`,
		);
	}

	const result = await response.json();

	if (!Array.isArray(result?.data)) {
		throw new Error("Invalid model list.");
	}

	const unique = new Map<string, ModelOption & { created: number }>();

	for (const item of result.data) {
		// Account discovery narrows the shortlist rather than restoring snapshots and older models.
		if (!SUPPORTED_MODELS.some((model) => model.id === item?.id)) {
			continue;
		}

		if (item.shutdown_date && Date.parse(item.shutdown_date) <= Date.now()) {
			continue;
		}

		unique.set(item.id, {
			id: item.id,
			name: item.id,
			created: Number.isFinite(item.created) ? item.created : 0,
			note: "Available to this key. Test the connection to verify compatibility.",
		});
	}

	return [...unique.values()].sort((first, second) => {
		const newestFirst = second.created - first.created;

		if (newestFirst !== 0) {
			return newestFirst;
		}

		return first.id.localeCompare(second.id);
	});
}
