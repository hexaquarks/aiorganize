import { SUPPORTED_MODELS } from "./model-catalog";
import { fetchModels, ModelListError } from "./models";
import { DEFAULT_MODEL } from "./settings";
import type { ModelOption } from "./types";

export class ModelDiscovery {
	models = $state<ModelOption[]>([...SUPPORTED_MODELS]);
	status = $state("Supported models · enter your key to check account availability.");
	loading = $state(false);
	private controller: AbortController | null = null;
	private timer: ReturnType<typeof setTimeout> | undefined;
	private loadedKey = "";
	private loadedAt = 0;

	cancel() {
		clearTimeout(this.timer);
		this.controller?.abort();
		this.controller = null;
		this.loading = false;
	}

	reset() {
		this.cancel();
		this.models = [...SUPPORTED_MODELS];
		this.loadedKey = "";
		this.status = "Supported models · enter your key to check account availability.";
	}

	preserve(model: string) {
		if (this.models.some((item) => item.id === model)) return;
		this.models = [
			...this.models.slice(0, 14),
			{
				id: model,
				name: SUPPORTED_MODELS.find((item) => item.id === model)?.name || model,
				note: "Not listed for this key. Test the connection to check access.",
			},
		];
	}

	schedule(apiKey: string, model: string) {
		this.reset();
		this.preserve(model);
		if (apiKey.trim()) this.timer = setTimeout(() => void this.refresh(apiKey, model), 600);
	}

	async refresh(apiKey: string, model: string, force = false) {
		clearTimeout(this.timer);
		apiKey = apiKey.trim();
		const cached = this.loadedKey === apiKey && Date.now() - this.loadedAt < 300000;
		if (!apiKey || this.loading || (!force && cached)) return;

		const controller = new AbortController();
		this.controller = controller;
		this.loading = true;
		this.status = "Loading available models…";
		try {
			const items = await fetchModels(apiKey, controller.signal);
			if (controller.signal.aborted) return;
			this.models = items.map((item) => ({
				...item,
				name: SUPPORTED_MODELS.find((fallback) => fallback.id === item.id)?.name || item.name,
			}));
			this.models.sort((a, b) => Number(b.id === DEFAULT_MODEL) - Number(a.id === DEFAULT_MODEL));
			this.preserve(model);
			this.loadedKey = apiKey;
			this.loadedAt = Date.now();
			this.status = items.length
				? `${items.length} account models loaded · default first, then newest.`
				: "No supported models found for this key. Check project access or refresh.";
		} catch (error) {
			if (!controller.signal.aborted) {
				this.status =
					error instanceof ModelListError
						? error.message
						: "Could not reach the model list. Check your connection and refresh.";
			}
		} finally {
			if (this.controller === controller) {
				this.controller = null;
				this.loading = false;
			}
		}
	}
}
