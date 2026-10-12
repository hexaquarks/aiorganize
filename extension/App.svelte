<script lang="ts">
	import { onMount, tick } from "svelte";
	import { ConnectionState } from "./connection.svelte";
	import { QdrantConnectionState } from "./qdrant-connection.svelte";
	import QdrantSettings from "./components/QdrantSettings.svelte";
	import { GroupingState } from "./grouping.svelte";
	import SettingsForm from "./components/SettingsForm.svelte";
	import ReadyPanel from "./components/ReadyPanel.svelte";
	import GroupPreview from "./components/GroupPreview.svelte";
	import Icon from "./components/Icon.svelte";

	const connection = new ConnectionState();
	const grouping = new GroupingState();
	const qdrant = new QdrantConnectionState();

	onMount(() => {
		void connection.load();
		void qdrant.load();

		const stopWatching = grouping.watch();

		return () => {
			connection.destroy();
			qdrant.destroy();
			stopWatching();
		};
	});

	function editConnection() {
		grouping.pending = null;
		grouping.status = "";

		connection.edit();
	}

	$effect(() => {
		let target: string | null = null;

		if (grouping.pending) {
			target = "preview";
		} else if (grouping.status) {
			target = "status";
		}

		if (!target) {
			return;
		}

		void tick().then(() => {
			const section = document.getElementById(target);

			if (!section) {
				return;
			}

			const reducedMotion = matchMedia("(prefers-reduced-motion: reduce)").matches;

			section.scrollIntoView({
				block: "start",
				behavior: reducedMotion ? "instant" : "smooth",
			});
		});
	});
</script>

<main data-connected={String(connection.connected)} aria-busy={grouping.busy}>
	<header class="topbar">
		<div class="brand"><img src="icons/brand.png" alt="" /><span>AI Organize</span></div>
		<button
			id="settings-toggle"
			class="text-button muted"
			type="button"
			disabled={grouping.busy || connection.testing || qdrant.testing}
			onclick={editConnection}><Icon name="settings" /> Settings</button
		>
	</header>
	<div class="welcome">
		<span id="badge" class="badge" class:verified={connection.connected}>
			{connection.connected ? "✓ Connection verified" : "One-time setup"}
		</span>
		<h1 id="heading">{connection.connected ? "Less clutter. More focus." : "Connect your AI"}</h1>
		<p id="intro">{connection.connected ? "Group your tabs by topic." : "Add an OpenAI API key to get started."}</p>
	</div>
	<SettingsForm {connection} />
	<ReadyPanel {connection} {grouping} onedit={editConnection} />
	<QdrantSettings connection={qdrant} visible={connection.editing} />
	<p id="privacy-note" class="privacy-note">
		<Icon name="privacy" />
		<span>
			Organizing sends tab titles and URLs to OpenAI.<br />
			With Qdrant connected, approved groupings are saved for future suggestions.
		</span>
	</p>
	<div id="connection-actions" hidden={!connection.saved.apiKey} inert={connection.testing}>
		<button
			id="forget-key"
			class="text-button muted"
			type="button"
			disabled={grouping.busy}
			onclick={() => {
				grouping.pending = null;
				grouping.status = "";
				void connection.forget();
			}}><Icon name="trash" /> Remove key</button
		>
	</div>
	<div class="flex items-center gap-2">
		<span id="activity" class:spinning={grouping.busy} aria-hidden="true"></span>
		<p id="status" role="status" aria-live="polite">{grouping.status}</p>
	</div>
	<div class="mt-2" hidden={!grouping.savedGroupingsStatus}>
		<p id="saved-groupings-status" class="note" role="status" aria-live="polite">{grouping.savedGroupingsStatus}</p>
		{#if grouping.canRetrySave}
			<button
				id="retry-save-groupings"
				class="text-button"
				type="button"
				disabled={grouping.busy || !connection.connected}
				onclick={() => grouping.retrySave()}>Retry save</button
			>
		{/if}
	</div>
	<GroupPreview
		pending={grouping.pending}
		busy={grouping.busy}
		onapprove={() => grouping.approve()}
		onreject={() => grouping.reject()}
	/>
</main>
