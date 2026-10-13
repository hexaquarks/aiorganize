<script lang="ts">
	import { untrack } from "svelte";
	import type { QdrantConnectionState } from "../qdrant-connection.svelte";

	let { connection, visible }: { connection: QdrantConnectionState; visible: boolean } = $props();
	let revealed = $state(false);

	$effect(() => {
		if (visible) {
			// Reset on opening settings; draft and testing updates must not erase edits.
			untrack(() => connection.reset());
			revealed = false;
		}
	});
</script>

<section class="mt-4" hidden={!visible} aria-label="Saved groupings settings">
	<details id="saved-groupings-settings" class="card">
		<summary>Saved groupings <span class="optional-label">Optional</span></summary>
		<form
			id="qdrant-settings"
			hidden={!visible}
			aria-busy={connection.testing}
			onsubmit={(event) => {
				event.preventDefault();
				void connection.verify();
			}}
		>
			<fieldset disabled={connection.testing}>
				<div class="flex items-center justify-between">
					<strong>Qdrant Cloud database</strong>
					<a href="https://cloud.qdrant.io" target="_blank" rel="noreferrer">Open dashboard ↗</a>
				</div>
				<p class="note">
					Optional: connect your Qdrant Cloud database to reuse approved groupings in future suggestions.
					Group names, tab titles, and URLs are stored in that database.
				</p>
				<label for="qdrant-url">Cluster URL</label>
				<input
					id="qdrant-url"
					type="url"
					required
					autocomplete="off"
					spellcheck="false"
					placeholder="https://your-cluster.cloud.qdrant.io:6333"
					bind:value={connection.draft.url}
					oninput={() => (connection.feedback = "")}
				/>
				<label class="mt-3" for="qdrant-key">Database API key</label>
				<div class="key-input">
					<input
						id="qdrant-key"
						type={revealed ? "text" : "password"}
						required
						autocomplete="off"
						spellcheck="false"
						bind:value={connection.draft.apiKey}
						oninput={() => (connection.feedback = "")}
					/>
					<button
						class="text-button"
						type="button"
						aria-label={revealed ? "Hide Qdrant key" : "Show Qdrant key"}
						onclick={() => (revealed = !revealed)}>{revealed ? "Hide" : "Show"}</button
					>
				</div>
				<p class="note">
					Use a database key with access to list collections, rather than a Cloud management key.
				</p>
				<label class="remember">
					<input
						id="qdrant-remember"
						type="checkbox"
						bind:checked={connection.draft.remember}
						onchange={() => (connection.feedback = "")}
					/>
					<span
						>Remember key on this device<small
							>Unchecked: kept until Chrome fully quits. Never synced.</small
						></span
					>
				</label>
			</fieldset>
			<button
				id="qdrant-test"
				class="primary"
				type="submit"
				disabled={connection.testing || !connection.draft.url.trim() || !connection.draft.apiKey.trim()}
			>
				{connection.testing ? "Checking database…" : "Verify & save database"}
			</button>
			<p class="footnote">Checks database access. No tab data is sent or stored.</p>
			<p id="qdrant-status" role="status" aria-live="polite" class="note">
				{connection.testing ? "Checking database access…" : connection.feedback}
			</p>
			{#if connection.saved.verifiedAt}
				<p id="qdrant-saved" class="note">
					Saved connection · {connection.saved.remember ? "Remembered on this device" : "Session only"}<br />
					Last tested {new Date(connection.saved.verifiedAt).toLocaleString()}
				</p>
				<button
					id="qdrant-reset"
					class="text-button"
					type="button"
					disabled={connection.testing}
					onclick={() => connection.reset()}>Use saved connection</button
				>
				<button
					id="qdrant-disconnect"
					class="text-button"
					type="button"
					disabled={connection.testing}
					onclick={() => void connection.forget()}>Disconnect database</button
				>
			{/if}
		</form>
	</details>
</section>
