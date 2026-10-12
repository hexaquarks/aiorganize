<script lang="ts">
	let { name }: { name: "settings" | "privacy" | "trash" } = $props();

	const paths = {
		settings:
			"m9 3-.6 2.3-2 .9L4 5.6 2 9l1.8 1.6v2.8L2 15l2 3.4 2.4-.6 2 .9L9 21h6l.6-2.3 2-.9 2.4.6 2-3.4-1.8-1.6v-2.8L22 9l-2-3.4-2.4.6-2-.9L15 3Z",
		privacy: "m12 2 9 4v6c0 5-9 10-9 10S3 17 3 12V6Z M8 12l3 3 5-6",
		trash: "M3 6h18M9 6V3h6v3M5 6l1 15h12l1-15M10 10v7m4-7v7",
	};
</script>

<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true">
	<path d={paths[name]} />
	{#if name === "settings"}
		<circle cx="12" cy="12" r="3" />
	{/if}
</svg>
