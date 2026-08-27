<script lang="ts">
	import { getContext, createEventDispatcher } from 'svelte';

	const i18n = getContext('i18n');
	const dispatch = createEventDispatcher();

	import Dropdown from '$lib/components/common/Dropdown.svelte';
	import DropdownMenu from '$lib/components/common/DropdownMenu.svelte';
	import Tooltip from '$lib/components/common/Tooltip.svelte';
	import EditPencil from '../icons/EditPencil.svelte';
	import TrashIcon from '../icons/Trash.svelte';

	export let align: 'start' | 'end' = 'start';
	export let onRename = () => {};
	export let onDelete = () => {};
	export let onOpenChange: (state: boolean) => void = () => {};

	let show = false;

	// Track `show` itself: Dropdown only invokes its own onOpenChange from its
	// internal close paths, not when `show` is toggled from out here (trigger
	// or menu-item clicks), so notifying from the bound value covers both.
	let lastNotified = false;
	$: if (show !== lastNotified) {
		lastNotified = show;
		onOpenChange(show);
		if (!show) {
			dispatch('close');
		}
	}
</script>

<Dropdown bind:show {align}>
	<Tooltip content={$i18n.t('More')}>
		<!-- tabindex=-1 keeps the enclosing treeitem as the tree's only focus stop -->
		<button
			tabindex="-1"
			aria-label={$i18n.t('Thread menu')}
			on:click={(e) => {
				e.stopPropagation();
				show = !show;
			}}
		>
			<slot />
		</button>
	</Tooltip>

	<div slot="content">
		<DropdownMenu className="min-w-[10.625rem]">
			<button
				class="flex h-[1.6875rem] w-full items-center gap-2 rounded-xl px-2 text-[0.8125rem] select-none cursor-pointer hover:bg-gray-50/40 dark:hover:bg-gray-800/40"
				on:click={() => {
					show = false;
					onRename();
				}}
			>
				<EditPencil className="size-3.5" />
				<div class="flex items-center">{$i18n.t('Rename')}</div>
			</button>

			<button
				class="flex h-[1.6875rem] w-full items-center gap-2 rounded-xl px-2 text-[0.8125rem] select-none cursor-pointer hover:bg-gray-50/40 dark:hover:bg-gray-800/40"
				on:click={() => {
					show = false;
					onDelete();
				}}
			>
				<TrashIcon className="size-3.5" />
				<div class="flex items-center">{$i18n.t('Delete')}</div>
			</button>
		</DropdownMenu>
	</div>
</Dropdown>
