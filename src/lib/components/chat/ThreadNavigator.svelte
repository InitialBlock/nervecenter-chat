<script lang="ts">
	import { getContext, tick } from 'svelte';

	import type { ThreadTreeBranch } from '$lib/utils/threads';

	import ThreadNavigatorNode from './ThreadNavigatorNode.svelte';

	const i18n = getContext('i18n');

	export let threadTree: ThreadTreeBranch[] = [];
	export let activeChatId: string | null = null;

	export let onSelect: (id: string) => void = () => {};

	// U9: the per-node menu extension point, materialized as two typed
	// callbacks forwarded to each node. Chat.svelte owns persistence
	// (rename API call, descendant-protected delete) and tree refresh.
	// Leave both unset for a read-only navigator (no menu is rendered).
	export let onRenameThread: ((id: string, title: string) => void | Promise<void>) | null = null;
	export let onDeleteThread: ((id: string) => void | Promise<void>) | null = null;

	let treeElement: HTMLDivElement | null = null;

	// Expansion state per node id; nodes default to expanded.
	let expandedIds: Record<string, boolean> = {};

	const setExpanded = (id: string, open: boolean) => {
		expandedIds = { ...expandedIds, [id]: open };
	};

	const getVisibleNodes = (
		branches: ThreadTreeBranch[],
		expanded: Record<string, boolean>
	): ThreadTreeBranch[] => {
		const out: ThreadTreeBranch[] = [];
		const walk = (items: ThreadTreeBranch[]) => {
			for (const item of items) {
				out.push(item);
				if ((expanded[item.id] ?? true) && item.children.length > 0) {
					walk(item.children);
				}
			}
		};
		walk(branches ?? []);
		return out;
	};

	const getParentIds = (branches: ThreadTreeBranch[]): Record<string, string> => {
		const map: Record<string, string> = {};
		const walk = (items: ThreadTreeBranch[]) => {
			for (const item of items) {
				for (const child of item.children) {
					map[child.id] = item.id;
				}
				walk(item.children);
			}
		};
		walk(branches ?? []);
		return map;
	};

	$: visibleNodes = getVisibleNodes(threadTree, expandedIds);
	$: parentIds = getParentIds(threadTree);

	// Roving tabindex: exactly one visible node is tabbable at a time.
	let focusedId: string | null = null;
	$: if (!focusedId || !visibleNodes.some((node) => node.id === focusedId)) {
		focusedId =
			(visibleNodes.find((node) => node.id === activeChatId) ?? visibleNodes[0])?.id ?? null;
	}

	const handleSelect = (id: string) => {
		// Keep the roving tabindex on the node the user interacted with.
		focusedId = id;
		onSelect(id);
	};

	const focusNode = async (id: string | null | undefined) => {
		if (!id) {
			return;
		}
		focusedId = id;
		await tick();
		const element = treeElement?.querySelector(
			`[data-thread-node-id="${CSS.escape(id)}"]`
		) as HTMLElement | null;
		element?.focus();
	};

	const handleNodeKeydown = (event: KeyboardEvent, node: ThreadTreeBranch) => {
		const index = visibleNodes.findIndex((visible) => visible.id === node.id);
		if (index === -1) {
			return;
		}

		const hasChildren = node.children.length > 0;
		const isOpen = expandedIds[node.id] ?? true;

		switch (event.key) {
			case 'ArrowDown':
				focusNode(visibleNodes[index + 1]?.id);
				break;
			case 'ArrowUp':
				focusNode(visibleNodes[index - 1]?.id);
				break;
			case 'ArrowRight':
				if (hasChildren && !isOpen) {
					setExpanded(node.id, true);
				} else if (hasChildren) {
					focusNode(node.children[0]?.id);
				}
				break;
			case 'ArrowLeft':
				if (hasChildren && isOpen) {
					setExpanded(node.id, false);
				} else {
					focusNode(parentIds[node.id]);
				}
				break;
			case 'Home':
				focusNode(visibleNodes[0]?.id);
				break;
			case 'End':
				focusNode(visibleNodes[visibleNodes.length - 1]?.id);
				break;
			case 'Enter':
			case ' ':
				handleSelect(node.id);
				break;
			default:
				return;
		}

		event.preventDefault();
		event.stopPropagation();
	};
</script>

<div
	bind:this={treeElement}
	class="w-full flex flex-col"
	role="tree"
	aria-label={$i18n.t('Thread tree')}
>
	{#each threadTree as branch (branch.id)}
		<ThreadNavigatorNode
			node={branch}
			{activeChatId}
			{expandedIds}
			{focusedId}
			onSelect={handleSelect}
			{onRenameThread}
			{onDeleteThread}
			onToggle={setExpanded}
			onKeydown={handleNodeKeydown}
		/>
	{/each}
</div>
