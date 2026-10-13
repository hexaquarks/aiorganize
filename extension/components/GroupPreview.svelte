<script lang="ts">
	import { groupColor } from "../tabs";
	import type { PendingProposal } from "../types";

	let {
		pending,
		busy,
		onapprove,
		onreject,
	}: {
		pending: PendingProposal | null;
		busy: boolean;
		onapprove: () => void;
		onreject: () => void;
	} = $props();

	const tabs = $derived(new Map(pending?.snapshot.map((tab) => [tab.id, tab]) || []));

	function siteLabel(url: string) {
		try {
			return new URL(url).hostname.replace(/^www\./, "") || "Blank page";
		} catch {
			return "Local page";
		}
	}
</script>

<section id="preview" aria-labelledby="preview-heading" hidden={!pending}>
	<div class="flex items-center justify-between gap-2">
		<h2 id="preview-heading" tabindex="-1">Review your groups</h2>
		<span class="preview-badge">Preview</span>
	</div>
	<p id="summary">{pending?.snapshot.length} tabs in {pending?.groups.length} groups.</p>
	<p class="preview-note">Only this window changes. Apply when you’re happy with the groups.</p>
	<div id="groups">
		{#each pending?.groups || [] as group, index}
			{@const color = groupColor(group.name, index)}
			<article class="group" data-color={color.name} style:--group-color={color.hex}>
				<header class="group-header">
					<h3>{group.name}</h3>
					<span class="group-count">{group.tab_ids.length} {group.tab_ids.length === 1 ? "tab" : "tabs"}</span
					>
				</header>
				<ul>
					{#each group.tab_ids as id}
						{@const tab = tabs.get(id)!}
						{@const site = siteLabel(tab.url)}
						<li>
							<span class="tab-icon" aria-hidden="true">{site.charAt(0).toUpperCase()}</span>
							<div class="min-w-0">
								<span class="tab-title" title={tab.title || "Untitled tab"}
									>{tab.title || "Untitled tab"}</span
								>
								<span class="tab-url">{site}</span>
							</div>
						</li>
					{/each}
				</ul>
			</article>
		{/each}
	</div>
	<div class="actions">
		<button id="reject" class="secondary" type="button" disabled={busy} onclick={onreject}>Discard</button>
		<button id="approve" class="flex-1" type="button" disabled={busy || !pending} onclick={onapprove}>
			Approve &amp; apply <span aria-hidden="true">→</span>
		</button>
	</div>
</section>
