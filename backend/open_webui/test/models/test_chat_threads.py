"""Pure tests for the thread-hierarchy helpers in ``models/chats.py`` (U5).

No DB and no app running: the subtree core is a pure function over an
adjacency mapping, the message-deletion set is computed on plain history
dicts, and the default thread title is a pure snippet derivation.
"""

import asyncio
import copy
import os
import tempfile

# models/chats.py transitively imports open_webui.env, which requires these at
# import time. No DB connection is ever opened by these tests.
os.environ.setdefault('WEBUI_SECRET_KEY', 'test-secret-key')
os.environ.setdefault('DATA_DIR', tempfile.mkdtemp(prefix='owui-test-data-'))

from open_webui.models.chats import (  # noqa: E402
    DEFAULT_THREAD_TITLE,
    THREAD_TITLE_MAX_LENGTH,
    ChatTable,
    collect_thread_subtree_ids,
    expand_ids_with_live_children,
    revalidate_thread_anchor,
    thread_title_from_message,
)

# ---------------------------------------------------------------------------
# collect_thread_subtree_ids — pure BFS over a parent -> children adjacency
# ---------------------------------------------------------------------------


def test_subtree_linear_chain():
    adjacency = {'a': ['b'], 'b': ['c'], 'c': ['d']}
    assert collect_thread_subtree_ids('a', adjacency) == ['a', 'b', 'c', 'd']


def test_subtree_from_mid_chain_excludes_ancestors():
    adjacency = {'a': ['b'], 'b': ['c'], 'c': ['d']}
    assert collect_thread_subtree_ids('b', adjacency) == ['b', 'c', 'd']


def test_subtree_wide_tree_count_and_membership():
    # root -> 3 children, each child -> 2 grandchildren: 10 nodes total
    adjacency = {'root': ['c1', 'c2', 'c3']}
    expected = {'root', 'c1', 'c2', 'c3'}
    for child in ['c1', 'c2', 'c3']:
        grandchildren = [f'{child}-g1', f'{child}-g2']
        adjacency[child] = grandchildren
        expected.update(grandchildren)

    subtree = collect_thread_subtree_ids('root', adjacency)
    assert len(subtree) == 10
    assert set(subtree) == expected


def test_subtree_bfs_order_parents_before_children():
    adjacency = {'root': ['c1', 'c2'], 'c1': ['g1'], 'c2': ['g2']}
    subtree = collect_thread_subtree_ids('root', adjacency)
    position = {chat_id: index for index, chat_id in enumerate(subtree)}
    for parent_id, child_ids in adjacency.items():
        for child_id in child_ids:
            assert position[parent_id] < position[child_id]


def test_subtree_cycle_guard_terminates():
    # Corrupted pointers forming a 2-cycle must not loop forever nor duplicate.
    adjacency = {'a': ['b'], 'b': ['a']}
    assert collect_thread_subtree_ids('a', adjacency) == ['a', 'b']


def test_subtree_self_cycle_guard():
    adjacency = {'a': ['a', 'b']}
    assert collect_thread_subtree_ids('a', adjacency) == ['a', 'b']


def test_subtree_leaf_has_no_descendants():
    assert collect_thread_subtree_ids('leaf', {}) == ['leaf']


def test_subtree_ignores_empty_child_ids():
    adjacency = {'a': ['', None, 'b']}
    assert collect_thread_subtree_ids('a', adjacency) == ['a', 'b']


def test_subtree_descendant_count_is_len_minus_one():
    adjacency = {'a': ['b', 'c'], 'c': ['d']}
    subtree = collect_thread_subtree_ids('a', adjacency)
    assert len(subtree) - 1 == 3  # descendants only, addressed chat excluded


# ---------------------------------------------------------------------------
# get_message_deletion_ids — the set delete_message_from_history will remove
# ---------------------------------------------------------------------------


def build_history(edges):
    """Build a history dict from ``{message_id: [child ids]}`` edges."""
    messages = {}
    for message_id, child_ids in edges.items():
        messages.setdefault(message_id, {'id': message_id, 'parentId': None, 'childrenIds': []})
        messages[message_id]['childrenIds'] = list(child_ids)
        for child_id in child_ids:
            messages.setdefault(child_id, {'id': child_id, 'parentId': None, 'childrenIds': []})
            messages[child_id]['parentId'] = message_id
    return {'messages': messages, 'currentId': None}


def test_deletion_ids_leaf_message_is_only_itself():
    history = build_history({'m1': ['m2'], 'm2': []})
    assert ChatTable.get_message_deletion_ids(history, 'm2') == {'m2'}


def test_deletion_ids_include_direct_children_not_grandchildren():
    history = build_history({'m1': ['a1', 'a2'], 'a1': ['g1'], 'a2': []})
    assert ChatTable.get_message_deletion_ids(history, 'm1') == {'m1', 'a1', 'a2'}


def test_deletion_ids_missing_message_is_empty():
    history = build_history({'m1': []})
    assert ChatTable.get_message_deletion_ids(history, 'nope') == set()
    assert ChatTable.get_message_deletion_ids({}, 'm1') == set()


def test_deletion_ids_skip_children_absent_from_map():
    history = build_history({'m1': ['a1']})
    history['messages']['m1']['childrenIds'].append('ghost')  # dangling child id
    assert ChatTable.get_message_deletion_ids(history, 'm1') == {'m1', 'a1'}


def test_deletion_ids_match_delete_message_from_history():
    """The guard's precomputed set must equal what the destructive call removes."""
    history = build_history({'m1': ['a1', 'a2'], 'a1': ['g1', 'g2'], 'a2': ['g3']})
    for message_id in list(history['messages']):
        predicted = ChatTable.get_message_deletion_ids(copy.deepcopy(history), message_id)
        actually_deleted = ChatTable.delete_message_from_history(copy.deepcopy(history), message_id)
        assert predicted == actually_deleted, message_id


def test_branch_point_check_blocks_message_that_anchors_a_thread():
    history = build_history({'m1': ['a1']})
    deletion_ids = ChatTable.get_message_deletion_ids(history, 'm1')
    child_branch_points = {'m1'}  # an existing child thread branches from m1
    assert deletion_ids & child_branch_points


def test_branch_point_check_blocks_parent_of_branched_from_child():
    # Deleting m1 also deletes its child a1; a thread branches from a1.
    history = build_history({'m1': ['a1'], 'a1': ['g1']})
    deletion_ids = ChatTable.get_message_deletion_ids(history, 'm1')
    child_branch_points = {'a1'}
    assert deletion_ids & child_branch_points


def test_branch_point_check_allows_unrelated_message():
    # g1 is a grandchild: deleting it touches neither m1 nor a1.
    history = build_history({'m1': ['a1'], 'a1': ['g1']})
    deletion_ids = ChatTable.get_message_deletion_ids(history, 'g1')
    child_branch_points = {'m1', 'a1'}
    assert not (deletion_ids & child_branch_points)


# ---------------------------------------------------------------------------
# thread_title_from_message — default-title snippet derivation
# ---------------------------------------------------------------------------


def test_title_short_content_used_verbatim():
    assert thread_title_from_message({'content': 'Pricing deep-dive'}) == 'Pricing deep-dive'


def test_title_collapses_whitespace_and_newlines():
    message = {'content': '  What about\n\n   enterprise\tpricing?  '}
    assert thread_title_from_message(message) == 'What about enterprise pricing?'


def test_title_truncates_long_content_with_ellipsis():
    content = 'x' * 200
    title = thread_title_from_message({'content': content})
    assert title == 'x' * THREAD_TITLE_MAX_LENGTH + '…'
    assert len(title) == THREAD_TITLE_MAX_LENGTH + 1


def test_title_truncation_strips_trailing_whitespace():
    content = 'word ' * 20  # forces a cut right after a space
    title = thread_title_from_message({'content': content})
    assert not title[:-1].endswith(' ')
    assert title.endswith('…')
    assert len(title) <= THREAD_TITLE_MAX_LENGTH + 1


def test_title_fallback_on_empty_or_whitespace_content():
    assert thread_title_from_message({'content': ''}) == DEFAULT_THREAD_TITLE
    assert thread_title_from_message({'content': '   \n '}) == DEFAULT_THREAD_TITLE


def test_title_fallback_on_missing_or_non_string_content():
    assert thread_title_from_message(None) == DEFAULT_THREAD_TITLE
    assert thread_title_from_message({}) == DEFAULT_THREAD_TITLE
    assert thread_title_from_message({'content': ['not', 'a', 'string']}) == DEFAULT_THREAD_TITLE


# ---------------------------------------------------------------------------
# expand_ids_with_live_children — fixed-point expansion closing the cascade
# delete's TOCTOU window (children created after the subtree snapshot)
# ---------------------------------------------------------------------------


def make_adjacency_fetcher(children_by_parent, call_log=None):
    """Fetcher backed by a static parent -> children mapping (fake DB query)."""

    async def fetch_new_child_ids(current_ids):
        if call_log is not None:
            call_log.append(set(current_ids))
        return [
            child_id
            for parent_id in current_ids
            for child_id in children_by_parent.get(parent_id, [])
            if child_id not in current_ids
        ]

    return fetch_new_child_ids


def test_expand_no_live_children_is_identity():
    fetcher = make_adjacency_fetcher({})
    assert asyncio.run(expand_ids_with_live_children({'a', 'b'}, fetcher)) == {'a', 'b'}


def test_expand_picks_up_child_created_after_snapshot():
    # Snapshot was {a}; a thread 'late' was created under 'a' mid-window.
    fetcher = make_adjacency_fetcher({'a': ['late']})
    assert asyncio.run(expand_ids_with_live_children({'a'}, fetcher)) == {'a', 'late'}


def test_expand_reaches_grandchildren_across_iterations():
    # Each generation only becomes visible once its parent joins the set.
    fetcher = make_adjacency_fetcher({'a': ['b'], 'b': ['c'], 'c': ['d']})
    assert asyncio.run(expand_ids_with_live_children({'a'}, fetcher)) == {'a', 'b', 'c', 'd'}


def test_expand_stops_at_fixed_point():
    call_log = []
    fetcher = make_adjacency_fetcher({'a': ['b']}, call_log)
    asyncio.run(expand_ids_with_live_children({'a'}, fetcher))
    # One round finds 'b', the next confirms the fixed point — then it stops.
    assert len(call_log) == 2


def test_expand_cycle_terminates():
    # Corrupted pointers forming a cycle: members are excluded per round, so
    # the set converges instead of looping.
    fetcher = make_adjacency_fetcher({'a': ['b'], 'b': ['a']})
    assert asyncio.run(expand_ids_with_live_children({'a'}, fetcher)) == {'a', 'b'}


def test_expand_bounded_by_max_iterations():
    chain = {f'n{i}': [f'n{i + 1}'] for i in range(100)}
    fetcher = make_adjacency_fetcher(chain)
    expanded = asyncio.run(expand_ids_with_live_children({'n0'}, fetcher, max_iterations=3))
    # One generation per iteration: n0 plus three discovered descendants.
    assert expanded == {'n0', 'n1', 'n2', 'n3'}


def test_expand_does_not_mutate_input():
    ids = {'a'}
    fetcher = make_adjacency_fetcher({'a': ['b']})
    asyncio.run(expand_ids_with_live_children(ids, fetcher))
    assert ids == {'a'}


# ---------------------------------------------------------------------------
# revalidate_thread_anchor — post-insert revalidation closing the other side
# of the create/delete race (a delete committing between the create endpoint's
# validations and its insert)
# ---------------------------------------------------------------------------


def make_anchor_env(parent, message, deleted=None):
    """Injectable fetchers over a static parent/message pair (fake DB reads)."""
    deleted = deleted if deleted is not None else []

    async def fetch_parent():
        return parent

    async def fetch_branch_message(fetched_parent):
        assert fetched_parent is parent  # helper must check against the re-fetch
        return message

    async def delete_thread(thread_id):
        deleted.append(thread_id)

    return fetch_parent, fetch_branch_message, delete_thread, deleted


def test_revalidate_anchor_holds_keeps_row():
    fetchers = make_anchor_env(parent={'id': 'p'}, message={'id': 'm'})
    fetch_parent, fetch_branch_message, delete_thread, deleted = fetchers
    result = asyncio.run(revalidate_thread_anchor('t1', fetch_parent, fetch_branch_message, delete_thread))
    assert result is None
    assert deleted == []


def test_revalidate_parent_vanished_removes_row():
    fetch_parent, fetch_branch_message, delete_thread, deleted = make_anchor_env(parent=None, message={'id': 'm'})
    result = asyncio.run(revalidate_thread_anchor('t1', fetch_parent, fetch_branch_message, delete_thread))
    assert result == 'chat'
    assert deleted == ['t1']


def test_revalidate_message_vanished_removes_row():
    fetch_parent, fetch_branch_message, delete_thread, deleted = make_anchor_env(parent={'id': 'p'}, message=None)
    result = asyncio.run(revalidate_thread_anchor('t1', fetch_parent, fetch_branch_message, delete_thread))
    assert result == 'message'
    assert deleted == ['t1']


def test_revalidate_parent_vanished_skips_message_lookup():
    # With the parent gone there is no history to consult; the helper must not
    # call the message fetcher on a missing parent.
    async def fetch_parent():
        return None

    async def fetch_branch_message(fetched_parent):
        raise AssertionError('message fetcher must not run when the parent is gone')

    deleted = []

    async def delete_thread(thread_id):
        deleted.append(thread_id)

    result = asyncio.run(revalidate_thread_anchor('t1', fetch_parent, fetch_branch_message, delete_thread))
    assert result == 'chat'
    assert deleted == ['t1']
