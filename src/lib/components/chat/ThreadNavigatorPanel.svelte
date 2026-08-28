<script lang="ts">
	import { getContext } from 'svelte';

	import type { ThreadTreeBranch } from '$lib/utils/threads';

	import ThreadNavigator from './ThreadNavigator.svelte';
	import Spinner from '../common/Spinner.svelte';
	import XMark from '../icons/XMark.svelte';

	const i18n = getContext('i18n');

	export let threadTree: ThreadTreeBranch[] = [];
	export let activeChatId: string | null = null;
	export let loading = false;
	export let error = false;

	export let onClose: () => void = () => {};
	export let onSelect: (id: string) => void = () => {};
	export let onRenameThread: ((id: string, title: string) => void | Promise<void>) | null = null;
	export let onDeleteThread: ((id: string) => void | Promise<void>) | null = null;
</script>

<div class="flex items-center justify-between px-3 pt-2 pb-2 shrink-0">
	<div class="flex min-w-0 items-center gap-2">
		<div class="truncate text-sm font-medium text-gray-700 dark:text-gray-200">
			{$i18n.t('Thread tree')}
		</div>
		{#if loading}
			<Spinner className="size-3" />
		{/if}
	</div>
	<button
		class="p-1 rounded-lg text-gray-500 dark:text-gray-400"
		on:click={() => {
			onClose();
		}}
		aria-label={$i18n.t('Close')}
	>
		<XMark className="size-4" strokeWidth="2" />
	</button>
</div>
{#if error}
	<div class="px-3 pb-1 text-xs text-red-500 dark:text-red-400 shrink-0">
		{$i18n.t('Failed to load thread tree')}
	</div>
{/if}
<div class="flex-1 min-h-0 overflow-y-auto px-2 pb-2">
	<ThreadNavigator {threadTree} {activeChatId} {onSelect} {onRenameThread} {onDeleteThread} />
</div>
