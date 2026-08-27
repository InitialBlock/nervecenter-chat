"""Pure tests for the thread-hierarchy helpers in ``models/chats.py`` (U5).

No DB and no app running: the subtree core is a pure function over an
adjacency mapping, the message-deletion set is computed on plain history
dicts, and the default thread title is a pure snippet derivation.
"""

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
