<script lang="ts">
	import type { ConnectionState } from "../connection.svelte";
	import ModelPicker from "./ModelPicker.svelte";

	let { connection }: { connection: ConnectionState } = $props();
	let revealed = $state(false);
	let keyInput: HTMLInputElement;
	let form: HTMLFormElement;

	const discovery = $derived(connection.discovery);
	const modelNote = $derived(discovery.models.find((item) => item.id === connection.draft.model)?.note);

	$effect(() => {
		if (connection.editing) {
			revealed = false;
		}
	});

	function keyChanged() {
		connection.feedback = null;

		discovery.schedule(connection.draft.apiKey, connection.draft.model);
	}

	function refresh(force = false) {
		if (!connection.testing) {
			void discovery.refresh(connection.draft.apiKey, connection.draft.model, force);
		}
	}

	function retry() {
		if (connection.feedback?.kind === "auth") {
			keyInput.focus();
		} else if (connection.feedback?.kind === "model") {
			form.querySelector<HTMLButtonElement>("#api-model")?.focus();
		} else {
			void connection.verify();
		}
	}
</script>

<form
	id="api-settings"
	class="card"
	hidden={!connection.editing}
	aria-busy={connection.testing}
	bind:this={form}
	onsubmit={(event) => {
		event.preventDefault();
		void connection.verify();
	}}
>
	<h2 class="settings-heading">AI model</h2>
	<fieldset id="settings-fields" disabled={connection.testing}>
		<div class="flex items-center justify-between">
			<label id="key-label" for="api-key">OpenAI API key</label>
			<a href="https://platform.openai.com/api-keys" target="_blank" rel="noreferrer">Get a key ↗</a>
		</div>
		<div class="key-input">
			<input
				id="api-key"
				type={revealed ? "text" : "password"}
				autocomplete="off"
				spellcheck="false"
				bind:this={keyInput}
				bind:value={connection.draft.apiKey}
				oninput={keyChanged}
				onblur={() => refresh()}
			/>
			<button
				id="reveal-key"
				class="text-button"
				type="button"
				aria-label={revealed ? "Hide API key" : "Show API key"}
				onclick={() => (revealed = !revealed)}
			>
				<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
					<path d="M2 12s3-7 10-7 10 7 10 7-3 7-10 7S2 12 2 12Z" /><circle cx="12" cy="12" r="3" />
				</svg>
			</button>
		</div>
		<p class="note">Requires OpenAI API billing.</p>
		<div class="flex items-center justify-between">
			<label id="model-label" for="api-model">Model</label>
			<button
				id="refresh-models"
				class="text-button"
				type="button"
				disabled={connection.testing || discovery.loading || !connection.draft.apiKey.trim()}
				onclick={() => refresh(true)}>Refresh models</button
			>
		</div>
		<ModelPicker
			models={discovery.models}
			bind:value={connection.draft.model}
			disabled={connection.testing}
			onopen={() => refresh()}
			onchange={() => (connection.feedback = null)}
		/>
		<p id="model-discovery-status" class="note model-discovery-status" role="status" aria-live="polite">
			{discovery.status}
		</p>
		<p id="model-note" class="note">{modelNote || "Test to verify model compatibility."}</p>
		<p id="key-storage" class="note" hidden={!connection.saved.verifiedAt}>
			Saved key · {connection.saved.remember ? "Remembered on this device" : "Session only"}
		</p>
		<label class="remember">
			<input
				id="remember-key"
				type="checkbox"
				bind:checked={connection.draft.remember}
				onchange={() => (connection.feedback = null)}
			/>
			<span
				>Remember key on this device
				<small
					>Stored locally without encryption; never synced. When unchecked, the key lasts until Chrome quits.</small
				>
			</span>
		</label>
	</fieldset>
	<button
		id="test-connection"
		class="primary"
		class:testing={connection.testing}
		type="submit"
		disabled={connection.testing || !connection.draft.apiKey.trim() || !connection.draft.model}
	>
		<span class="spinner" aria-hidden="true"></span>
		<span id="test-label">{connection.testing ? "Checking model…" : "Verify & save"}</span>
	</button>
	<p class="footnote">Runs a small API test. Charges may apply.</p>
	<div
		id="settings-status"
		class="feedback {connection.testing ? 'checking' : connection.feedback?.kind || ''}"
		hidden={!connection.testing && !connection.feedback}
		role="status"
		aria-live="polite"
	>
		{#if connection.testing}
			<span>Checking model access…</span><small>Your tabs are not sent during this test.</small>
		{:else if connection.feedback}
			<span>{connection.feedback.message}</span>
			<small
				>{connection.saved.verifiedAt
					? "Your previous connection is still saved."
					: "Your connection has not been saved."}</small
			>
			{#if connection.feedback.kind === "billing"}
				<a
					href="https://platform.openai.com/settings/organization/billing/overview"
					target="_blank"
					rel="noreferrer">Open billing</a
				>
			{:else}
				<button class="text-button" type="button" onclick={retry}>{connection.feedback.action}</button>
			{/if}
		{/if}
	</div>
</form>
