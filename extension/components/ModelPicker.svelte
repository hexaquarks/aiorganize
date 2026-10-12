<script lang="ts">
	import { tick } from "svelte";
	import type { ModelOption } from "../types";

	let {
		models,
		value = $bindable(),
		disabled = false,
		onopen,
		onchange,
	}: {
		models: ModelOption[];
		value: string;
		disabled?: boolean;
		onopen: () => void;
		onchange: () => void;
	} = $props();

	let expanded = $state(false);
	let picker: HTMLDivElement;
	let trigger: HTMLButtonElement;
	let list: HTMLDivElement;

	const label = $derived(models.find((model) => model.id === value)?.name || value);

	function options() {
		return Array.from(list.querySelectorAll<HTMLButtonElement>('[role="option"]'));
	}

	async function open(index = models.findIndex((model) => model.id === value)) {
		if (disabled) {
			return;
		}

		expanded = true;
		await tick();

		const option = options()[Math.max(0, index)];
		option?.focus();
		option?.scrollIntoView({ block: "nearest" });

		onopen();
	}

	function select(model: ModelOption) {
		value = model.id;
		expanded = false;

		trigger.focus();
		onchange();
	}

	function triggerKey(event: KeyboardEvent) {
		if (!["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) {
			return;
		}

		event.preventDefault();

		let index: number | undefined;

		if (event.key === "Home") {
			index = 0;
		} else if (event.key === "End") {
			index = models.length - 1;
		}

		void open(index);
	}

	function optionKey(event: KeyboardEvent) {
		const items = options();
		const index = items.indexOf(document.activeElement as HTMLButtonElement);
		let next: number | undefined;

		if (event.key === "ArrowDown") {
			next = (index + 1) % items.length;
		}

		if (event.key === "ArrowUp") {
			next = (index + items.length - 1) % items.length;
		}

		if (event.key === "Home") {
			next = 0;
		}

		if (event.key === "End") {
			next = items.length - 1;
		}

		if (next !== undefined) {
			event.preventDefault();
			items[next]?.focus();
			items[next]?.scrollIntoView({ block: "nearest" });
		} else if (event.key === "Escape" || event.key === "Tab") {
			if (event.key === "Escape") {
				event.preventDefault();
			}

			expanded = false;
			trigger.focus();
		}
	}

	$effect(() => {
		if (disabled) {
			expanded = false;
		}
	});
</script>

<svelte:document
	onclick={(event) => {
		if (picker && !picker.contains(event.target as Node)) {
			expanded = false;
		}
	}}
/>

<div
	id="model-picker"
	class="relative mt-2"
	bind:this={picker}
	onfocusout={(event) => {
		if (event.relatedTarget && !picker.contains(event.relatedTarget as Node)) {
			expanded = false;
		}
	}}
>
	<button
		id="api-model"
		class="model-trigger"
		type="button"
		{value}
		{disabled}
		bind:this={trigger}
		aria-haspopup="listbox"
		aria-expanded={expanded}
		aria-controls="model-options"
		aria-labelledby="model-label selected-model"
		onkeydown={triggerKey}
		onclick={() => {
			if (expanded) {
				expanded = false;
			} else {
				void open();
			}
		}}
	>
		<span id="selected-model">{label}</span>
		<span aria-hidden="true">⌄</span>
	</button>
	<div
		id="model-options"
		class="model-options"
		role="listbox"
		aria-labelledby="model-label"
		hidden={!expanded}
		bind:this={list}
		onkeydown={optionKey}
		tabindex="-1"
	>
		{#each models as model (model.id)}
			<button
				class="model-option"
				type="button"
				role="option"
				tabindex="-1"
				aria-label={model.name}
				aria-selected={model.id === value}
				data-value={model.id}
				onclick={() => select(model)}>{model.name}</button
			>
		{/each}
	</div>
</div>
