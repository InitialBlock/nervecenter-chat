<script lang="ts">
	import { getContext, tick } from 'svelte';

	import type { ThreadTreeBranch } from '$lib/utils/threads';

	import Collapsible from '../common/Collapsible.svelte';
	import ChevronDown from '../icons/ChevronDown.svelte';
	import ChevronRight from '../icons/ChevronRight.svelte';
	import EllipsisHorizontal from '../icons/EllipsisHorizontal.svelte';
	import ThreadMenu from './ThreadMenu.svelte';

	const i18n = getContext('i18n');

	export let node: ThreadTreeBranch;
	export let activeChatId: string | null = null;
	export let expandedIds: Record<string, boolean> = {};
	export let focusedId: string | null = null;

	export let onSelect: (id: string) => void = () => {};
	export let onToggle: (id: string, open: boolean) => void = () => {};
	export let onKeydown: (event: KeyboardEvent, node: ThreadTreeBranch) => void = () => {};

	// U9: per-node menu callbacks (the materialized `onNodeMenu` extension
	// point). Persistence and tree refresh live in Chat.svelte; the node only
	// reports the user's intent. Both are omitted for read-only navigators.
	export let onRenameThread: ((id: string, title: string) => void | Promise<void>) | null = null;
	export let onDeleteThread: ((id: string) => void | Promise<void>) | null = null;

	$: hasChildren = (node?.children ?? []).length > 0;
	$: open = expandedIds[node.id] ?? true;
	$: active = activeChatId === node.id;

	// The workspace root intentionally has no menu: renaming/deleting the root
	// chat is already available through the sidebar ChatItem, which also owns
	// the sidebar-refresh side effects of a root deletion.
	$: showMenu = !!node.parent_chat_id && !!(onRenameThread || onDeleteThread);

	// Inline rename (mirrors RecursiveFolder.svelte): the title swaps for an
	// input; commit on blur/Enter, Escape cancels without committing.
	let edit = false;
	let editedTitle = '';
	let menuOpen = false;

	const startRename = async () => {
		editedTitle = node.title ?? '';
		edit = true;

		await tick();
		const input = document.getElementById(`thread-title-input-${node.id}`);
		if (input instanceof HTMLInputElement) {
			input.focus();
			input.select();
		}
	};

	const commitRename = () => {
		if (!edit) {
			return;
		}
		edit = false;

		const title = editedTitle.trim();
		if (title !== (node.title ?? '')) {
			onRenameThread?.(node.id, title);
		}
	};

	const cancelRename = () => {
		edit = false;
	};
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
			class="group relative w-full py-1 px-1.5 rounded-xl flex items-center gap-1.5 cursor-pointer hover:bg-gray-50/40 dark:hover:bg-gray-800/40 transition {active
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

			{#if edit}
				<input
					id="thread-title-input-{node.id}"
					type="text"
					bind:value={editedTitle}
					class="min-w-0 flex-1 bg-transparent text-left text-sm text-gray-800 dark:text-gray-200 outline-hidden"
					on:click={(e) => {
						e.stopPropagation();
					}}
					on:mousedown={(e) => {
						e.stopPropagation();
					}}
					on:blur={() => {
						commitRename();
					}}
					on:keydown={(e) => {
						if (e.key === 'Enter') {
							e.preventDefault();
							commitRename();
						} else if (e.key === 'Escape') {
							e.preventDefault();
							cancelRename();
						}
					}}
				/>
			{:else}
				<div
					class="min-w-0 flex-1 truncate text-left text-sm {active
						? 'text-gray-800 dark:text-gray-200'
						: 'text-gray-600 dark:text-gray-400'}"
				>
					{node.title || $i18n.t('New Chat')}
				</div>

				{#if showMenu}
					<div
						class="shrink-0 flex items-center text-gray-500 dark:text-gray-400 {menuOpen
							? ''
							: 'hover-reveal'}"
					>
						<ThreadMenu
							align="end"
							onOpenChange={(state) => {
								menuOpen = state;
							}}
							onRename={() => {
								startRename();
							}}
							onDelete={() => {
								onDeleteThread?.(node.id);
							}}
						>
							<div
								class="flex size-5 items-center justify-center self-center hover:text-gray-800 dark:hover:text-white transition"
							>
								<EllipsisHorizontal className="size-3.5" strokeWidth="2" />
							</div>
						</ThreadMenu>
					</div>
				{/if}
			{/if}
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
							{onRenameThread}
							{onDeleteThread}
						/>
					{/each}
				</div>
			{/if}
		</svelte:fragment>
	</Collapsible>
</div>
