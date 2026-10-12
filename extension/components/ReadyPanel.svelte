<script lang="ts">
	import { SUPPORTED_MODELS } from "../model-catalog";
	import type { ConnectionState } from "../connection.svelte";
	import type { GroupingState } from "../grouping.svelte";

	let {
		connection,
		grouping,
		onedit,
	}: {
		connection: ConnectionState;
		grouping: GroupingState;
		onedit: () => void;
	} = $props();
	const label = $derived(
		SUPPORTED_MODELS.find((item) => item.id === connection.saved.model)?.name || connection.saved.model,
	);
	const verified = $derived(new Date(connection.saved.verifiedAt || Date.now()));
</script>

<section id="ready" hidden={!connection.connected}>
	<div class="connection">
		<span class="connection-check" aria-hidden="true">✓</span>
		<div>
			<strong>OpenAI connected</strong>
			<p id="connection-detail">
				{label} · {connection.saved.remember ? "Remembered on this device" : "Session only"}
			</p>
		</div>
		<button id="edit-connection" class="text-button" type="button" disabled={grouping.busy} onclick={onedit}
			>Edit</button
		>
	</div>
	<time id="verified-time" datetime={verified.toISOString()} title={verified.toLocaleString()}>
		{Date.now() - verified.getTime() > 60000 ? `Last tested ${verified.toLocaleString()}` : "Last tested just now"}
	</time>
	<div class="card organize-card">
		<div class="illustration" aria-hidden="true">
			{#each ["Work", "Research", "Shopping"] as category}
				<div class="sample {category.toLowerCase()}"><span>{category}</span><i></i><i></i></div>
			{/each}
		</div>
		<button
			id="organize"
			class="primary"
			type="button"
			disabled={grouping.busy || !connection.connected}
			onclick={() => grouping.organize()}
		>
			<span aria-hidden="true">✦</span><span id="organize-label">
				{grouping.busy
					? "Working…"
					: grouping.tabCount
						? `Organize ${grouping.tabCount} ${grouping.tabCount === 1 ? "tab" : "tabs"}`
						: "Organize tabs"}
			</span>
		</button>
		<p class="footnote">Tab titles and URLs are sent to OpenAI.</p>
	</div>
</section>
