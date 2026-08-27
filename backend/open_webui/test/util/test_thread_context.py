"""Tests for hierarchical thread context assembly (utils/thread_context.py).

Acceptance base (spec section 27):
    Main:        M1 -> M2 -> M3 -> M4 -> M5 -> M6 (linear)
    Pricing:     branched from Main@M4, own chain A1 -> A2 -> A3
    Competitors: branched from Pricing@A2, own chain B1 -> B2
"""

import asyncio
import copy
import logging
from types import SimpleNamespace

from open_webui.utils.thread_context import (
    MESSAGE_REPLAY_KEYS,
    assemble_thread_context,
    build_thread_context,
)


# ---------------------------------------------------------------------------
# Fixture helpers (hand-built message maps, Open WebUI history.messages shape)
# ---------------------------------------------------------------------------


def msg(message_id, parent_id, **extra):
    base = {
        'id': message_id,
        'parentId': parent_id,
        'childrenIds': [],
        'role': 'user',
        'content': f'content-{message_id}',
        'timestamp': 0,
    }
    base.update(extra)
    return base


def linear_map(ids):
    """Build a strictly linear messages_map from an ordered id list."""
    messages_map = {}
    parent = None
    for message_id in ids:
        messages_map[message_id] = msg(message_id, parent)
        if parent is not None:
            messages_map[parent]['childrenIds'].append(message_id)
        parent = message_id
    return messages_map


def main_map():
    return linear_map(['M1', 'M2', 'M3', 'M4', 'M5', 'M6'])


def pricing_map():
    return linear_map(['A1', 'A2', 'A3'])


def competitors_map():
    return linear_map(['B1', 'B2'])


def ids_of(context):
    return [m['id'] for m in context]


# Segments as build_thread_context expects them.
PRICING_ANCESTORS = lambda: [(main_map(), 'M4')]  # noqa: E731
COMPETITORS_ANCESTORS = lambda: [(main_map(), 'M4'), (pricing_map(), 'A2')]  # noqa: E731


# ---------------------------------------------------------------------------
# 1. AE1 exactness
# ---------------------------------------------------------------------------


def test_ae1_main_context_is_own_chain_only():
    context = build_thread_context([], (main_map(), 'M6'))
    assert ids_of(context) == ['M1', 'M2', 'M3', 'M4', 'M5', 'M6']


def test_ae1_pricing_context_exact():
    context = build_thread_context(PRICING_ANCESTORS(), (pricing_map(), 'A3'))
    assert ids_of(context) == ['M1', 'M2', 'M3', 'M4', 'A1', 'A2', 'A3']
    assert 'M5' not in ids_of(context) and 'M6' not in ids_of(context)


def test_ae1_competitors_context_exact():
    context = build_thread_context(COMPETITORS_ANCESTORS(), (competitors_map(), 'B2'))
    assert ids_of(context) == ['M1', 'M2', 'M3', 'M4', 'A1', 'A2', 'B1', 'B2']


def test_projection_keeps_only_replay_keys():
    context = build_thread_context(PRICING_ANCESTORS(), (pricing_map(), 'A3'))
    for message in context:
        assert set(message) <= set(MESSAGE_REPLAY_KEYS)
        assert 'childrenIds' not in message
        assert 'parentId' not in message
        assert 'timestamp' not in message
    assert context[0]['content'] == 'content-M1'


# ---------------------------------------------------------------------------
# 2. AE2 non-tip branch point (frozen path, never the ancestor's live tip)
# ---------------------------------------------------------------------------


def test_ae2_ancestor_segment_ends_at_branch_point_not_tip():
    # Pricing's tip/currentId would be A3; Competitors branched at A2.
    context = build_thread_context(COMPETITORS_ANCESTORS(), (competitors_map(), 'B2'))
    assert 'A3' not in ids_of(context)
    assert ids_of(context)[4:6] == ['A1', 'A2']


# ---------------------------------------------------------------------------
# 3. Missing branch-point message in an ancestor map -> segment skipped
# ---------------------------------------------------------------------------


def test_missing_branch_point_skips_segment_keeps_rest(caplog):
    segments = [(main_map(), 'M4-DOES-NOT-EXIST'), (pricing_map(), 'A2')]
    with caplog.at_level(logging.WARNING, logger='open_webui.utils.thread_context'):
        context = build_thread_context(segments, (competitors_map(), 'B2'))
    assert ids_of(context) == ['A1', 'A2', 'B1', 'B2']
    assert any('unresolvable ancestor segment' in r.message for r in caplog.records)


def test_empty_ancestor_map_skips_segment(caplog):
    segments = [({}, 'M4'), (pricing_map(), 'A2')]
    with caplog.at_level(logging.WARNING, logger='open_webui.utils.thread_context'):
        context = build_thread_context(segments, (competitors_map(), 'B2'))
    assert ids_of(context) == ['A1', 'A2', 'B1', 'B2']


# ---------------------------------------------------------------------------
# Resolver test helpers (no DB: injected fake fetchers)
# ---------------------------------------------------------------------------


def fake_chat(chat_id, user_id='u1', parent_chat_id=None, branch_from_message_id=None):
    return SimpleNamespace(
        id=chat_id,
        user_id=user_id,
        parent_chat_id=parent_chat_id,
        branch_from_message_id=branch_from_message_id,
    )


def make_fetchers(chats, maps):
    async def get_chat(chat_id):
        return chats.get(chat_id)

    async def get_messages_map(chat_id):
        return maps.get(chat_id)

    return get_chat, get_messages_map


def thread_family():
    """The acceptance-base family as resolver-level fakes."""
    chats = {
        'main': fake_chat('main'),
        'pricing': fake_chat('pricing', parent_chat_id='main', branch_from_message_id='M4'),
        'competitors': fake_chat('competitors', parent_chat_id='pricing', branch_from_message_id='A2'),
    }
    maps = {'main': main_map(), 'pricing': pricing_map(), 'competitors': competitors_map()}
    return chats, maps


def resolve(chat, target_message_id, chats, maps, **kwargs):
    get_chat, get_messages_map = make_fetchers(chats, maps)
    return asyncio.run(
        assemble_thread_context(
            chat,
            target_message_id,
            user_id='u1',
            get_chat=get_chat,
            get_messages_map=get_messages_map,
            **kwargs,
        )
    )


def test_resolver_matches_pure_function_for_competitors():
    chats, maps = thread_family()
    context = resolve(chats['competitors'], 'B2', chats, maps)
    assert ids_of(context) == ['M1', 'M2', 'M3', 'M4', 'A1', 'A2', 'B1', 'B2']


# ---------------------------------------------------------------------------
# 4. Missing ancestor entirely -> graceful skip (resolver-level, fake fetch)
# ---------------------------------------------------------------------------


def test_missing_root_most_ancestor_keeps_nearer_segments(caplog):
    chats, maps = thread_family()
    del chats['main']  # root ancestor row gone; pricing segment must survive
    with caplog.at_level(logging.WARNING, logger='open_webui.utils.thread_context'):
        context = resolve(chats['competitors'], 'B2', chats, maps)
    assert ids_of(context) == ['A1', 'A2', 'B1', 'B2']
    assert any('not found' in r.message for r in caplog.records)


def test_missing_direct_parent_degrades_to_own_chain(caplog):
    chats, maps = thread_family()
    del chats['pricing']
    with caplog.at_level(logging.WARNING, logger='open_webui.utils.thread_context'):
        context = resolve(chats['competitors'], 'B2', chats, maps)
    assert ids_of(context) == ['B1', 'B2']


# ---------------------------------------------------------------------------
# 5. Cycle in the parent chain terminates (resolver visited set)
# ---------------------------------------------------------------------------


def test_parent_chain_cycle_terminates(caplog):
    chats, maps = thread_family()
    # Corrupt the root to point back at its grandchild: competitors -> pricing
    # -> main -> competitors -> ...
    chats['main'] = fake_chat('main', parent_chat_id='competitors', branch_from_message_id='B1')
    with caplog.at_level(logging.WARNING, logger='open_webui.utils.thread_context'):
        context = resolve(chats['competitors'], 'B2', chats, maps)
    # Terminates; the two real ancestor segments are still assembled.
    assert ids_of(context) == ['M1', 'M2', 'M3', 'M4', 'A1', 'A2', 'B1', 'B2']
    assert any('cycle detected' in r.message for r in caplog.records)


def test_self_parent_cycle_terminates(caplog):
    chat = fake_chat('c1', parent_chat_id='c1', branch_from_message_id='X')
    with caplog.at_level(logging.WARNING, logger='open_webui.utils.thread_context'):
        context = resolve(chat, None, {'c1': chat}, {'c1': {}})
    assert context == []
    assert any('cycle detected' in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# 6. Depth: deep chains, at-cap, over-cap
# ---------------------------------------------------------------------------


def deep_family(levels):
    """chat_0 is the root; chat_{levels-1} is the leaf we resolve for.

    Each chat_i has a single message P{i}, and chat_{i+1} branches from it.
    """
    chats, maps = {}, {}
    for i in range(levels):
        parent = f'chat_{i - 1}' if i > 0 else None
        branch = f'P{i - 1}' if i > 0 else None
        chats[f'chat_{i}'] = fake_chat(f'chat_{i}', parent_chat_id=parent, branch_from_message_id=branch)
        maps[f'chat_{i}'] = {f'P{i}': msg(f'P{i}', None)}
    return chats, maps


def test_ten_level_chain_assembles_in_order():
    chats, maps = deep_family(10)
    context = resolve(chats['chat_9'], 'P9', chats, maps)
    assert ids_of(context) == [f'P{i}' for i in range(10)]


def test_chain_exactly_at_cap_fully_included(caplog):
    # 4 chats -> 3 ancestors for the leaf; cap of 3 fits exactly.
    chats, maps = deep_family(4)
    with caplog.at_level(logging.WARNING, logger='open_webui.utils.thread_context'):
        context = resolve(chats['chat_3'], 'P3', chats, maps, max_depth=3)
    assert ids_of(context) == ['P0', 'P1', 'P2', 'P3']
    assert not any('depth cap' in r.message for r in caplog.records)


def test_chain_over_cap_skips_root_most_segments(caplog):
    # 5 chats -> 4 ancestors for the leaf; cap of 3 drops the root-most (P0).
    chats, maps = deep_family(5)
    with caplog.at_level(logging.WARNING, logger='open_webui.utils.thread_context'):
        context = resolve(chats['chat_4'], 'P4', chats, maps, max_depth=3)
    assert ids_of(context) == ['P1', 'P2', 'P3', 'P4']
    assert any('depth cap' in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# 7. Empty thread (no own messages, target None) -> inherited only
# ---------------------------------------------------------------------------


def test_empty_thread_yields_inherited_context_only():
    context = build_thread_context(COMPETITORS_ANCESTORS(), ({}, None))
    assert ids_of(context) == ['M1', 'M2', 'M3', 'M4', 'A1', 'A2']


def test_empty_thread_via_resolver():
    chats, maps = thread_family()
    maps['competitors'] = {}
    context = resolve(chats['competitors'], None, chats, maps)
    assert ids_of(context) == ['M1', 'M2', 'M3', 'M4', 'A1', 'A2']


# ---------------------------------------------------------------------------
# 8. Message branching inside an ancestor: siblings off the path excluded
# ---------------------------------------------------------------------------


def test_sibling_branches_in_ancestor_never_included():
    messages_map = main_map()
    # Alternative regeneration M3b under M2, with its own child M4b.
    messages_map['M3b'] = msg('M3b', 'M2')
    messages_map['M2']['childrenIds'].append('M3b')
    messages_map['M4b'] = msg('M4b', 'M3b')
    messages_map['M3b']['childrenIds'].append('M4b')

    context = build_thread_context([(messages_map, 'M4')], (pricing_map(), 'A3'))
    assert ids_of(context) == ['M1', 'M2', 'M3', 'M4', 'A1', 'A2', 'A3']


# ---------------------------------------------------------------------------
# 9. Cross-owner ancestor pointer -> segment skipped (resolver)
# ---------------------------------------------------------------------------


def test_cross_owner_ancestor_skipped(caplog):
    chats, maps = thread_family()
    chats['main'] = fake_chat('main', user_id='someone-else')
    with caplog.at_level(logging.WARNING, logger='open_webui.utils.thread_context'):
        context = resolve(chats['competitors'], 'B2', chats, maps)
    assert ids_of(context) == ['A1', 'A2', 'B1', 'B2']
    assert not any('content-M' in str(m.get('content')) for m in context)
    assert any('different user' in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# 10. contextSummary stripped from inherited messages, kept on own messages
# ---------------------------------------------------------------------------


def test_context_summary_stripped_only_for_inherited_segments():
    ancestor = main_map()
    ancestor['M2']['contextSummary'] = 'compacted-in-ancestor'
    own = pricing_map()
    own['A1']['contextSummary'] = 'own-compaction'

    context = build_thread_context([(ancestor, 'M4')], (own, 'A3'))

    by_id = {m['id']: m for m in context}
    # Inherited: full prefix assembled, summary field gone.
    assert ids_of(context) == ['M1', 'M2', 'M3', 'M4', 'A1', 'A2', 'A3']
    assert 'contextSummary' not in by_id['M2']
    # Own messages keep theirs.
    assert by_id['A1']['contextSummary'] == 'own-compaction'


# ---------------------------------------------------------------------------
# 11. Live-content semantics (frozen path, live content)
# ---------------------------------------------------------------------------


def test_edited_ancestor_content_is_read_live():
    messages_map = main_map()
    before = build_thread_context([(messages_map, 'M4')], ({}, None))
    assert before[2]['content'] == 'content-M3'

    edited = copy.deepcopy(messages_map)
    edited['M3']['content'] = 'edited-later'
    after = build_thread_context([(edited, 'M4')], ({}, None))
    assert after[2]['content'] == 'edited-later'


def test_deleted_ancestor_message_follows_rewired_chain():
    messages_map = main_map()
    # Delete M3 (not the branch point) and rewire M4 to M2.
    del messages_map['M3']
    messages_map['M4']['parentId'] = 'M2'
    messages_map['M2']['childrenIds'] = ['M4']

    context = build_thread_context([(messages_map, 'M4')], ({}, None))
    assert ids_of(context) == ['M1', 'M2', 'M4']


# ---------------------------------------------------------------------------
# 12. Cycle inside a single segment's parentId chain terminates
# ---------------------------------------------------------------------------


def test_cycle_within_segment_parent_chain_terminates():
    messages_map = linear_map(['M1', 'M2', 'M3'])
    messages_map['M1']['parentId'] = 'M3'  # corrupt: M3 -> M2 -> M1 -> M3 -> ...

    context = build_thread_context([(messages_map, 'M3')], ({}, None))
    assert ids_of(context) == ['M1', 'M2', 'M3']  # each message once, then stop
