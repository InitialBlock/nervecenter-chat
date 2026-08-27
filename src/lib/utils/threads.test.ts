import { describe, expect, it } from 'vitest';
import { buildThreadTree, type ThreadTreeNode } from './threads';

const node = (
	id: string,
	parent_chat_id: string | null = null,
	created_at = 0,
	overrides: Partial<ThreadTreeNode> = {}
): ThreadTreeNode => ({
	id,
	title: `Chat ${id}`,
	parent_chat_id,
	branch_from_message_id: null,
	created_at,
	updated_at: created_at,
	...overrides
});

const collectIds = (branches: ReturnType<typeof buildThreadTree>): string[] => {
	const ids: string[] = [];
	const walk = (items: ReturnType<typeof buildThreadTree>) => {
		for (const item of items) {
			ids.push(item.id);
			walk(item.children);
		}
	};
	walk(branches);
	return ids;
};

describe('buildThreadTree', () => {
	it('nests flat nodes and orders children by created_at ascending', () => {
		const tree = buildThreadTree([
			node('c', 'a', 30),
			node('a', null, 10),
			node('b', 'a', 20),
			node('d', 'b', 40)
		]);

		expect(tree.length).toBe(1);
		expect(tree[0].id).toBe('a');
		expect(tree[0].children.map((child) => child.id)).toEqual(['b', 'c']);
		expect(tree[0].children[0].children.map((child) => child.id)).toEqual(['d']);
	});

	it('surfaces orphaned nodes at the root level', () => {
		const tree = buildThreadTree([
			node('a', null, 10),
			node('orphan', 'missing-parent', 20),
			node('b', 'a', 30)
		]);

		expect(tree.map((branch) => branch.id)).toEqual(['a', 'orphan']);
		expect(tree[0].children.map((child) => child.id)).toEqual(['b']);
	});

	it('terminates on cyclic parent chains without losing nodes', () => {
		const tree = buildThreadTree([
			node('a', 'b', 10),
			node('b', 'a', 20),
			node('child', 'a', 30),
			node('self', 'self', 40)
		]);

		const ids = collectIds(tree);
		expect([...ids].sort()).toEqual(['a', 'b', 'child', 'self']);
		// every node appears exactly once
		expect(new Set(ids).size).toBe(ids.length);
	});

	it('keeps input order for children with equal created_at (stable sort)', () => {
		const tree = buildThreadTree([
			node('root', null, 0),
			node('x', 'root', 100),
			node('y', 'root', 100),
			node('z', 'root', 100)
		]);

		expect(tree[0].children.map((child) => child.id)).toEqual(['x', 'y', 'z']);
	});

	it('returns an empty array for empty or missing input', () => {
		expect(buildThreadTree([])).toEqual([]);
	});
});
