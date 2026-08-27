"""Tests for thread transcript materialization (U6/R16).

Share, clone, and fork of a thread must produce a self-contained transcript:
the flattened assembled context (inherited + own) rebuilt as a strictly
linear Open WebUI ``history`` dict with fresh, consistent
``parentId``/``childrenIds`` links and ``currentId`` at the tail.

Acceptance base (spec section 27):
    Main:        M1 -> M2 -> M3 -> M4 (branch point at M4)
    Pricing:     branched from Main@M4, own chain A1 -> A2 (branch at A2)
    Competitors: branched from Pricing@A2, own chain B1 -> B2
"""

import asyncio
import copy
from types import SimpleNamespace

from open_webui.utils.chat_fork import build_fork_history, build_transcript_history
from open_webui.utils.thread_context import assemble_thread_transcript, build_thread_context


# ---------------------------------------------------------------------------
# Fixture helpers (mirroring test_thread_context.py)
# ---------------------------------------------------------------------------


def msg(message_id, parent_id, **extra):
    base = {
        'id': message_id,
        'parentId': parent_id,
        'childrenIds': [],
        'role': 'user',
        'content': f'content-{message_id}',
        'timestamp': 1000,
    }
    base.update(extra)
    return base


def linear_map(ids, roles=None):
    """Build a strictly linear messages_map from an ordered id list."""
    messages_map = {}
    parent = None
    for index, message_id in enumerate(ids):
        role = roles[index] if roles else ('user' if index % 2 == 0 else 'assistant')
        messages_map[message_id] = msg(message_id, parent, role=role)
        if parent is not None:
            messages_map[parent]['childrenIds'].append(message_id)
        parent = message_id
    return messages_map


def main_map():
    return linear_map(['M1', 'M2', 'M3', 'M4'])


def pricing_map():
    return linear_map(['A1', 'A2'])


def competitors_map():
    return linear_map(['B1', 'B2'])


def ids_of(messages):
    return [m['id'] for m in messages]


def assert_linear(history, ordered):
    """The core linearity contract: fresh consistent links, tail currentId."""
    assert ids_of(ordered) == list(history['messages'].keys())
    parent = None
    for index, message in enumerate(ordered):
        stored = history['messages'][message['id']]
        assert stored is message
        assert message['parentId'] == parent
        expected_children = [ordered[index + 1]['id']] if index + 1 < len(ordered) else []
        assert message['childrenIds'] == expected_children
        parent = message['id']
    assert history['currentId'] == (ordered[-1]['id'] if ordered else None)


# ---------------------------------------------------------------------------
# 1. Pure materialization: linear history from an assembled list
# ---------------------------------------------------------------------------


def test_materialized_history_is_linear_chain():
    context = build_thread_context([], (main_map(), 'M4'))
    history, ordered = build_transcript_history(context)

    assert ids_of(ordered) == ['M1', 'M2', 'M3', 'M4']
    assert_linear(history, ordered)


def test_ae1_shaped_input_preserves_order_and_roles():
    # Competitors' assembled context: M1-M4 + A1-A2 + B1-B2.
    context = build_thread_context(
        [(main_map(), 'M4'), (pricing_map(), 'A2')],
        (competitors_map(), 'B2'),
    )
    history, ordered = build_transcript_history(context)

    assert ids_of(ordered) == ['M1', 'M2', 'M3', 'M4', 'A1', 'A2', 'B1', 'B2']
    assert [m['role'] for m in ordered] == ['user', 'assistant'] * 4
    assert [m['content'] for m in ordered] == [f'content-{i}' for i in ids_of(ordered)]
    assert_linear(history, ordered)
    # Cross-segment stitch: A1 now hangs off M4, B1 off A2.
    assert history['messages']['A1']['parentId'] == 'M4'
    assert history['messages']['B1']['parentId'] == 'A2'


def test_empty_own_segment_materializes_inherited_only():
    # A brand-new thread: inherited context, no own messages yet.
    context = build_thread_context([(main_map(), 'M4'), (pricing_map(), 'A2')], ({}, None))
    history, ordered = build_transcript_history(context)

    assert ids_of(ordered) == ['M1', 'M2', 'M3', 'M4', 'A1', 'A2']
    assert_linear(history, ordered)
    assert history['currentId'] == 'A2'


def test_empty_input_yields_empty_history():
    history, ordered = build_transcript_history([])
    assert history == {'messages': {}, 'currentId': None}
    assert ordered == []


def test_single_message():
    context = build_thread_context([], (linear_map(['M1']), 'M1'))
    history, ordered = build_transcript_history(context)

    assert ids_of(ordered) == ['M1']
    assert_linear(history, ordered)
    assert history['messages']['M1']['parentId'] is None
    assert history['messages']['M1']['childrenIds'] == []
    assert history['currentId'] == 'M1'


# ---------------------------------------------------------------------------
# 2. Field reconstruction / synthesis
# ---------------------------------------------------------------------------


def test_raw_lookup_restores_projected_out_fields():
    raw = main_map()
    raw['M2']['done'] = True
    raw['M2']['models'] = ['gpt-x']
    raw['M2']['timestamp'] = 12345

    context = build_thread_context([], (raw, 'M4'))
    history, _ = build_transcript_history(context, raw_messages_by_id=raw)

    materialized = history['messages']['M2']
    assert materialized['timestamp'] == 12345
    assert materialized['done'] is True
    assert materialized['models'] == ['gpt-x']


def test_missing_fields_are_synthesized():
    # No raw lookup: projected messages carry no timestamp/done.
    context = build_thread_context([], (main_map(), 'M2'))
    history, ordered = build_transcript_history(context, default_timestamp=777)

    for message in ordered:
        assert message['timestamp'] == 777
    assert history['messages']['M2']['done'] is True  # assistant never renders as streaming
    assert 'done' not in history['messages']['M1']  # user messages get no done flag


def test_inherited_context_summary_stays_stripped():
    ancestor = main_map()
    ancestor['M2']['contextSummary'] = 'compacted-in-ancestor'
    own = pricing_map()
    own['A1']['contextSummary'] = 'own-compaction'

    context = build_thread_context([(ancestor, 'M4')], (own, 'A2'))
    history, _ = build_transcript_history(context, raw_messages_by_id={**ancestor, **own})

    # The projection stripped the inherited summary; the raw base must not
    # resurrect it. The thread's own summary survives.
    assert 'contextSummary' not in history['messages']['M2']
    assert history['messages']['A1']['contextSummary'] == 'own-compaction'


def test_inputs_are_not_mutated():
    raw = main_map()
    raw_before = copy.deepcopy(raw)
    context = build_thread_context([], (raw, 'M4'))
    context_before = copy.deepcopy(context)

    build_transcript_history(context, raw_messages_by_id=raw)

    assert raw == raw_before
    assert context == context_before


def test_duplicate_and_idless_messages_are_skipped():
    context = [
        {'id': 'X1', 'role': 'user', 'content': 'one'},
        {'role': 'assistant', 'content': 'no id'},
        {'id': 'X1', 'role': 'user', 'content': 'dup'},
        {'id': 'X2', 'role': 'assistant', 'content': 'two'},
    ]
    history, ordered = build_transcript_history(context)

    assert ids_of(ordered) == ['X1', 'X2']
    assert_linear(history, ordered)
    assert history['messages']['X1']['content'] == 'one'


# ---------------------------------------------------------------------------
# 3. Resolver-level: assemble_thread_transcript with injected fakes (no DB)
# ---------------------------------------------------------------------------


def fake_chat(chat_id, user_id='u1', parent_chat_id=None, branch_from_message_id=None):
    return SimpleNamespace(
        id=chat_id,
        user_id=user_id,
        parent_chat_id=parent_chat_id,
        branch_from_message_id=branch_from_message_id,
    )


def thread_family():
    chats = {
        'main': fake_chat('main'),
        'pricing': fake_chat('pricing', parent_chat_id='main', branch_from_message_id='M4'),
        'competitors': fake_chat('competitors', parent_chat_id='pricing', branch_from_message_id='A2'),
    }
    maps = {'main': main_map(), 'pricing': pricing_map(), 'competitors': competitors_map()}
    return chats, maps


def materialize(chat, target_message_id, chats, maps):
    async def get_chat(chat_id):
        return chats.get(chat_id)

    async def get_messages_map(chat_id):
        return maps.get(chat_id)

    return asyncio.run(
        assemble_thread_transcript(
            chat,
            target_message_id,
            user_id='u1',
            get_chat=get_chat,
            get_messages_map=get_messages_map,
        )
    )


def test_assembled_transcript_for_nested_thread():
    chats, maps = thread_family()
    history, ordered = materialize(chats['competitors'], 'B2', chats, maps)

    assert ids_of(ordered) == ['M1', 'M2', 'M3', 'M4', 'A1', 'A2', 'B1', 'B2']
    assert_linear(history, ordered)
    # Fields the replay projection drops come back from the fetched source maps.
    assert all(message['timestamp'] == 1000 for message in ordered)


# ---------------------------------------------------------------------------
# 4. Fork from a thread: build_fork_history over the materialized transcript
# ---------------------------------------------------------------------------


def test_fork_from_thread_includes_inherited_chain():
    chats, maps = thread_family()
    transcript_history, _ = materialize(chats['competitors'], 'B2', chats, maps)

    fork_history, fork_messages = build_fork_history(transcript_history['messages'], 'B2')

    assert ids_of(fork_messages) == ['M1', 'M2', 'M3', 'M4', 'A1', 'A2', 'B1', 'B2']
    assert fork_history['currentId'] == 'B2'
    assert fork_history['messages']['M1']['parentId'] is None
    assert fork_history['messages']['B1']['parentId'] == 'A2'


def test_fork_from_thread_at_inherited_message_truncates():
    chats, maps = thread_family()
    transcript_history, _ = materialize(chats['competitors'], 'B2', chats, maps)

    fork_history, fork_messages = build_fork_history(transcript_history['messages'], 'A1')

    assert ids_of(fork_messages) == ['M1', 'M2', 'M3', 'M4', 'A1']
    assert fork_history['currentId'] == 'A1'
