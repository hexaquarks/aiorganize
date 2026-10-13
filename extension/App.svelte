<script lang="ts">
	import { onMount, tick } from "svelte";
	import { ConnectionState } from "./connection.svelte";
	import { GroupingState } from "./grouping.svelte";
	import SettingsForm from "./components/SettingsForm.svelte";
	import ReadyPanel from "./components/ReadyPanel.svelte";
	import GroupPreview from "./components/GroupPreview.svelte";
	import Icon from "./components/Icon.svelte";

	const connection = new ConnectionState();
	const grouping = new GroupingState();
	const heading = $derived.by(() => {
		if (!connection.editing) {
			return "A little order for your tabs.";
		}

		return connection.saved.verifiedAt ? "Settings" : "Connect OpenAI";
	});

	onMount(() => {
		void connection.load();

		const stopWatching = grouping.watch();

		return () => {
			connection.destroy();
			stopWatching();
		};
	});

	function editConnection() {
		connection.edit();
		void tick().then(() => document.getElementById("api-key")?.focus());
	}

	function closeSettings() {
		connection.showSaved();
		const target = grouping.pending ? "preview-heading" : "organize";

		void tick().then(() => document.getElementById(target)?.focus());
	}

	$effect(() => {
		if (connection.editing) {
			return;
		}

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

			if (target === "preview") {
				document.getElementById("preview-heading")?.focus({ preventScroll: true });
			}

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
			hidden={connection.editing}
			type="button"
			disabled={grouping.busy || connection.testing}
			onclick={editConnection}><Icon name="settings" /> Settings</button
		>
		<button
			id="cancel-settings"
			class="text-button"
			type="button"
			hidden={!connection.editing || !connection.saved.verifiedAt}
			disabled={connection.testing}
			onclick={closeSettings}>Back</button
		>
	</header>
	<div class="welcome" hidden={!connection.editing && Boolean(grouping.pending)}>
		<h1 id="heading">{heading}</h1>
		<p id="intro" hidden={connection.editing}>Find the topics. Keep your focus.</p>
	</div>
	<SettingsForm {connection} />
	<ReadyPanel {connection} {grouping} />
	<p id="privacy-note" class="privacy-note" hidden={!connection.editing}>
		<Icon name="privacy" />
		<span>
			Organizing sends tab titles and URLs to OpenAI. AI Organize saves approved groupings for future suggestions.
			Page contents aren’t read.
		</span>
	</p>
	<div id="connection-actions" hidden={!connection.editing || !connection.saved.apiKey} inert={connection.testing}>
		<button
			id="forget-key"
			class="text-button muted"
			type="button"
			disabled={grouping.busy}
			onclick={() => {
				grouping.pending = null;
				grouping.status = "";
				grouping.retrievalStatus = "";
				void connection.forget();
			}}><Icon name="trash" /> Remove key</button
		>
	</div>
	<div class="status-line" hidden={connection.editing}>
		<span id="activity" class:spinning={grouping.busy} aria-hidden="true"></span>
		<p id="status" role="status" aria-live="polite">{grouping.status}</p>
	</div>
	<p
		id="retrieval-status"
		class="note"
		hidden={connection.editing || !grouping.retrievalStatus}
		role="status"
		aria-live="polite"
	>
		{grouping.retrievalStatus}
	</p>
	<div class="mt-2" hidden={connection.editing || !grouping.savedGroupingsStatus}>
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
		pending={connection.connected ? grouping.pending : null}
		busy={grouping.busy}
		onapprove={() => grouping.approve()}
		onreject={() => grouping.reject()}
	/>
</main>
