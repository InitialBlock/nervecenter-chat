export type ThreadTreeNode = {
	id: string;
	title: string | null;
	parent_chat_id: string | null;
	branch_from_message_id: string | null;
	created_at: number;
	updated_at: number;
};

export type ThreadTreeBranch = ThreadTreeNode & { children: ThreadTreeBranch[] };

/**
 * Convert the flat thread-tree node list returned by the API into a nested
 * structure of root branches.
 *
 * - Orphan-tolerant: a node whose parent_chat_id is not in the set surfaces
 *   at the root level instead of disappearing.
 * - Cycle-guarded: a parent chain that loops is severed at the point the
 *   cycle closes, so every node still appears exactly once and traversal
 *   terminates.
 * - Children (and roots) are stably sorted by created_at ascending.
 */
export const buildThreadTree = (nodes: ThreadTreeNode[]): ThreadTreeBranch[] => {
	const branchById = new Map<string, ThreadTreeBranch>();

	for (const node of nodes ?? []) {
		if (!node?.id || branchById.has(node.id)) {
			continue;
		}
		branchById.set(node.id, { ...node, children: [] });
	}

	// Resolve each node's effective parent: null (root) when the parent is
	// missing, self-referential, or part of a cycle that never reaches a root.
	const parentById = new Map<string, string | null>();

	const resolveParent = (id: string): string | null => {
		if (parentById.has(id)) {
			return parentById.get(id) ?? null;
		}

		const path = new Set<string>();
		let current = id;

		for (;;) {
			path.add(current);
			const branch = branchById.get(current);
			const parentId = branch?.parent_chat_id ?? null;

			if (parentId === null || parentId === current || !branchById.has(parentId)) {
				// Reached a root (missing or self parent): keep the chain as-is.
				parentById.set(current, null);
				break;
			}

			if (path.has(parentId)) {
				// The chain loops back on itself: sever it here so the current
				// node becomes a root and the walk terminates.
				parentById.set(current, null);
				break;
			}

			if (parentById.has(parentId)) {
				// Parent already resolved to a chain that reaches a root.
				parentById.set(current, parentId);
				break;
			}

			parentById.set(current, parentId);
			current = parentId;
		}

		return parentById.get(id) ?? null;
	};

	const roots: ThreadTreeBranch[] = [];

	for (const branch of branchById.values()) {
		const parentId = resolveParent(branch.id);
		const parent = parentId !== null ? branchById.get(parentId) : undefined;

		if (parent) {
			parent.children.push(branch);
		} else {
			roots.push(branch);
		}
	}

	// Array.prototype.sort is stable, so equal created_at values keep their
	// input order.
	const byCreatedAt = (a: ThreadTreeBranch, b: ThreadTreeBranch) =>
		(a.created_at ?? 0) - (b.created_at ?? 0);

	for (const branch of branchById.values()) {
		branch.children.sort(byCreatedAt);
	}
	roots.sort(byCreatedAt);

	return roots;
};

/** Flatten a nested thread tree back into a depth-first ordered list. */
export const flattenThreadTree = (branches: ThreadTreeBranch[]): ThreadTreeBranch[] => {
	const out: ThreadTreeBranch[] = [];
	const walk = (items: ThreadTreeBranch[]) => {
		for (const item of items) {
			out.push(item);
			walk(item.children);
		}
	};
	walk(branches ?? []);
	return out;
};
