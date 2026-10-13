import { SUPPORTED_MODELS } from "./model-catalog";
import { fetchModels, ModelListError } from "./models";
import { DEFAULT_MODEL } from "./settings";
import type { ModelOption } from "./types";

const MAX_MODEL_OPTIONS = 15;
const LOOKUP_DELAY_MS = 600;
const CACHE_DURATION_MS = 5 * 60 * 1000;

export class ModelDiscovery {
	models = $state<ModelOption[]>([...SUPPORTED_MODELS]);
	status = $state("");
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
		this.status = "";
	}

	preserve(model: string) {
		if (this.models.some((item) => item.id === model)) {
			return;
		}

		this.models = [
			...this.models.slice(0, MAX_MODEL_OPTIONS - 1),
			{
				id: model,
				name: SUPPORTED_MODELS.find((item) => item.id === model)?.name || model,
				note: "Not listed for this key.",
			},
		];
	}

	schedule(apiKey: string, model: string) {
		this.reset();
		this.preserve(model);

		if (apiKey.trim()) {
			this.timer = setTimeout(() => void this.refresh(apiKey, model), LOOKUP_DELAY_MS);
		}
	}

	async refresh(apiKey: string, model: string, force = false) {
		clearTimeout(this.timer);

		apiKey = apiKey.trim();

		const cached = this.loadedKey === apiKey && Date.now() - this.loadedAt < CACHE_DURATION_MS;

		if (!apiKey || this.loading || (!force && cached)) {
			return;
		}

		const controller = new AbortController();
		this.controller = controller;
		this.loading = true;
		this.status = "";

		try {
			const items = await fetchModels(apiKey, controller.signal);

			if (controller.signal.aborted) {
				return;
			}

			this.models = items.map((item) => ({
				...item,
				name: SUPPORTED_MODELS.find((fallback) => fallback.id === item.id)?.name || item.name,
			}));
			this.models.sort((first, second) => {
				if (first.id === second.id) {
					return 0;
				}

				if (first.id === DEFAULT_MODEL) {
					return -1;
				}

				return second.id === DEFAULT_MODEL ? 1 : 0;
			});
			this.preserve(model);

			this.loadedKey = apiKey;
			this.loadedAt = Date.now();
			this.status = "";

			if (!items.length) {
				this.status = "No supported models found for this key. Check project access or refresh.";
			}
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
