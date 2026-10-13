<script lang="ts">
	import { SUPPORTED_MODELS } from "../model-catalog";
	import type { ConnectionState } from "../connection.svelte";
	import type { GroupingState } from "../grouping.svelte";

	let {
		connection,
		grouping,
		savedGroupingsConnected,
	}: {
		connection: ConnectionState;
		grouping: GroupingState;
		savedGroupingsConnected: boolean;
	} = $props();

	const label = $derived(
		SUPPORTED_MODELS.find((item) => item.id === connection.saved.model)?.name || connection.saved.model,
	);

	const organizeLabel = $derived.by(() => {
		if (grouping.busy) {
			return "Please wait…";
		}

		if (grouping.tabCount) {
			const tabLabel = grouping.tabCount === 1 ? "tab" : "tabs";

			return `Organize ${grouping.tabCount} ${tabLabel}`;
		}

		return "Organize tabs";
	});
</script>

<section id="ready" hidden={!connection.connected || Boolean(grouping.pending)} aria-label="Organize your tabs">
	<div class="card organize-card">
		<div class="window-label">CURRENT WINDOW</div>
		<div class="tab-total">
			<strong>{grouping.tabCount}</strong><span>open {grouping.tabCount === 1 ? "tab" : "tabs"}</span>
		</div>
		<p class="organize-description">Turn your open tabs into topic groups.</p>
		<button
			id="organize"
			class="primary"
			type="button"
			disabled={grouping.busy || !connection.connected || Boolean(grouping.pending)}
			onclick={() => grouping.organize()}
		>
			<span aria-hidden="true">✦</span><span id="organize-label">{organizeLabel}</span>
		</button>
		<p class="review-note">Review the suggestions before anything changes.</p>
	</div>
	<p id="connection-detail" class="model-summary">Powered by OpenAI · {label}</p>
	<p class="data-note">
		Tab titles and URLs are sent to OpenAI. Page contents stay private.
		{#if savedGroupingsConnected}
			Approved groupings are also saved to guide future suggestions.
		{/if}
	</p>
</section>
