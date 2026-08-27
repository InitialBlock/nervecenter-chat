<script lang="ts">
	import { getContext } from 'svelte';

	import type { ThreadTreeBranch } from '$lib/utils/threads';

	import Collapsible from '../common/Collapsible.svelte';
	import ChevronDown from '../icons/ChevronDown.svelte';
	import ChevronRight from '../icons/ChevronRight.svelte';

	const i18n = getContext('i18n');

	export let node: ThreadTreeBranch;
	export let activeChatId: string | null = null;
	export let expandedIds: Record<string, boolean> = {};
	export let focusedId: string | null = null;

	export let onSelect: (id: string) => void = () => {};
	export let onToggle: (id: string, open: boolean) => void = () => {};
	export let onKeydown: (event: KeyboardEvent, node: ThreadTreeBranch) => void = () => {};

	// Extension point for U9: when a menu callback is provided, a per-node
	// menu affordance (rename/delete) can be rendered at the end of the row.
	// Intentionally unused for now.
	export let onNodeMenu: ((node: ThreadTreeBranch, event: MouseEvent) => void) | null = null;

	$: hasChildren = (node?.children ?? []).length > 0;
	$: open = expandedIds[node.id] ?? true;
	$: active = activeChatId === node.id;
</script>

<div
	class="w-full"
	role="treeitem"
	aria-expanded={hasChildren ? open : undefined}
	aria-selected={active}
	tabindex={focusedId === node.id ? 0 : -1}
	data-thread-node-id={node.id}
	on:keydown={(e) => {
		// Only handle keys for the focused treeitem itself; nested treeitem
		// events bubble through ancestor treeitems and must be ignored there.
		if (e.currentTarget === e.target) {
			onKeydown(e, node);
		}
	}}
>
	<Collapsible
		{open}
		className="w-full"
		buttonClassName="w-full"
		onChange={(state) => {
			onToggle(node.id, state);
		}}
	>
		<!-- svelte-ignore a11y-no-static-element-interactions -->
		<!-- svelte-ignore a11y-click-events-have-key-events -->
		<div
			class="relative w-full py-1 px-1.5 rounded-xl flex items-center gap-1.5 cursor-pointer hover:bg-gray-50/40 dark:hover:bg-gray-800/40 transition {active
				? 'bg-gray-100/80 dark:bg-gray-850/50'
				: ''}"
			on:click={(e) => {
				e.stopPropagation();
				onSelect(node.id);
			}}
		>
			{#if hasChildren}
				<button
					class="text-gray-600 dark:text-gray-400 transition-all p-1 hover:bg-gray-50/40 dark:hover:bg-gray-800/40 rounded-lg"
					tabindex="-1"
					aria-hidden="true"
					on:click={(e) => {
						e.stopPropagation();
						onToggle(node.id, !open);
					}}
				>
					{#if open}
						<ChevronDown className="size-3" strokeWidth="1.5" />
					{:else}
						<ChevronRight className="size-3" strokeWidth="1.5" />
					{/if}
				</button>
			{:else}
				<div class="p-1">
					<div class="size-3"></div>
				</div>
			{/if}

			<div
				class="min-w-0 flex-1 truncate text-left text-sm {active
					? 'text-gray-800 dark:text-gray-200'
					: 'text-gray-600 dark:text-gray-400'}"
			>
				{node.title || $i18n.t('New Chat')}
			</div>
		</div>

		<svelte:fragment slot="content">
			{#if hasChildren}
				<div
					role="group"
					class="ml-3 pl-1 mt-[0.0625rem] flex flex-col border-s border-gray-100 dark:border-gray-900"
				>
					{#each node.children as child (child.id)}
						<svelte:self
							node={child}
							{activeChatId}
							{expandedIds}
							{focusedId}
							{onSelect}
							{onToggle}
							{onKeydown}
							{onNodeMenu}
						/>
					{/each}
				</div>
			{/if}
		</svelte:fragment>
	</Collapsible>
</div>
