"""Tests for U4 completion-pipeline scoping helpers (utils/thread_context.py).

Covers the pure pieces of the completion integration:

- ``assemble_thread_context_with_prefix``: the inherited-prefix length the
  pipeline records in ``metadata['thread_inherited_message_count']``.
- ``split_inherited_prefix``: the mechanism context compaction uses so the
  inherited prefix passes through uncompacted and the compaction boundary is
  computed within the thread's OWN messages only.
- ``own_history_is_first_exchange``: the new-chat title fallback gate, which
  must count the thread's OWN history, never the flattened assembled payload.

Same acceptance base as test_thread_context.py:
    Main:        M1 -> M2 -> M3 -> M4 -> M5 -> M6 (linear)
    Pricing:     branched from Main@M4, own chain A1 -> A2 -> A3
    Competitors: branched from Pricing@A2, own chain B1 -> B2
"""

import asyncio
from types import SimpleNamespace

from open_webui.utils.thread_context import (
    assemble_thread_context,
    assemble_thread_context_with_prefix,
    own_history_is_first_exchange,
    split_inherited_prefix,
)


# ---------------------------------------------------------------------------
# Fixture helpers (mirrors test_thread_context.py)
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


def linear_map(ids, roles=None):
    messages_map = {}
    parent = None
    for index, message_id in enumerate(ids):
        role = roles[index] if roles else ('user' if index % 2 == 0 else 'assistant')
        messages_map[message_id] = msg(message_id, parent, role=role)
        if parent is not None:
            messages_map[parent]['childrenIds'].append(message_id)
        parent = message_id
    return messages_map


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
    maps = {
        'main': linear_map(['M1', 'M2', 'M3', 'M4', 'M5', 'M6']),
        'pricing': linear_map(['A1', 'A2', 'A3']),
        'competitors': linear_map(['B1', 'B2']),
    }
    return chats, maps


def resolve_with_prefix(chat, target_message_id, chats, maps):
    async def get_chat(chat_id):
        return chats.get(chat_id)

    async def get_messages_map(chat_id):
        return maps.get(chat_id)

    return asyncio.run(
        assemble_thread_context_with_prefix(
            chat,
            target_message_id,
            user_id='u1',
            get_chat=get_chat,
            get_messages_map=get_messages_map,
        )
    )


def ids_of(context):
    return [m['id'] for m in context]


# ---------------------------------------------------------------------------
# assemble_thread_context_with_prefix: inherited-prefix length
# ---------------------------------------------------------------------------


def test_prefix_variant_reports_inherited_count():
    chats, maps = thread_family()
    context, inherited_count = resolve_with_prefix(chats['competitors'], 'B2', chats, maps)
    assert ids_of(context) == ['M1', 'M2', 'M3', 'M4', 'A1', 'A2', 'B1', 'B2']
    assert inherited_count == 6
    assert ids_of(context[:inherited_count]) == ['M1', 'M2', 'M3', 'M4', 'A1', 'A2']
    assert ids_of(context[inherited_count:]) == ['B1', 'B2']


def test_prefix_variant_root_chat_has_zero_inherited():
    chats, maps = thread_family()
    context, inherited_count = resolve_with_prefix(chats['main'], 'M6', chats, maps)
    assert inherited_count == 0
    assert ids_of(context) == ['M1', 'M2', 'M3', 'M4', 'M5', 'M6']


def test_prefix_variant_matches_plain_wrapper():
    chats, maps = thread_family()

    async def get_chat(chat_id):
        return chats.get(chat_id)

    async def get_messages_map(chat_id):
        return maps.get(chat_id)

    context, _ = resolve_with_prefix(chats['pricing'], 'A3', chats, maps)
    wrapper_context = asyncio.run(
        assemble_thread_context(
            chats['pricing'],
            'A3',
            user_id='u1',
            get_chat=get_chat,
            get_messages_map=get_messages_map,
        )
    )
    assert context == wrapper_context


# ---------------------------------------------------------------------------
# split_inherited_prefix: compaction's scoping mechanism
# ---------------------------------------------------------------------------


def flattened_thread_payload():
    """Flattened payload as compact_messages_for_request sees it (post system-strip)."""
    inherited = [
        {'id': 'M1', 'role': 'user', 'content': 'q1'},
        {'id': 'M2', 'role': 'assistant', 'content': 'a1'},
        {'id': 'M3', 'role': 'user', 'content': 'q2'},
        {'id': 'M4', 'role': 'assistant', 'content': 'a2'},
    ]
    own = [
        {'id': 'B1', 'role': 'user', 'content': 'tq1'},
        {'id': 'B2', 'role': 'assistant', 'content': 'ta1'},
        {'id': 'B3', 'role': 'user', 'content': 'tq2'},
        {'id': 'B4', 'role': 'assistant', 'content': 'ta2'},
        {'id': 'B5', 'role': 'user', 'content': 'tq3'},
        {'id': 'B6', 'role': 'assistant', 'content': 'ta3'},
    ]
    return inherited, own


def test_split_inherited_prefix_basic():
    inherited, own = flattened_thread_payload()
    prefix, own_messages = split_inherited_prefix([*inherited, *own], len(inherited))
    assert prefix == inherited
    assert own_messages == own


def test_split_inherited_prefix_zero_and_none_yield_empty_prefix():
    _, own = flattened_thread_payload()
    assert split_inherited_prefix(own, 0) == ([], own)
    assert split_inherited_prefix(own, None) == ([], own)


def test_split_inherited_prefix_clamps_bad_counts():
    inherited, own = flattened_thread_payload()
    flattened = [*inherited, *own]
    # negative -> no prefix
    assert split_inherited_prefix(flattened, -3) == ([], flattened)
    # larger than the payload -> everything is prefix, nothing compactable
    assert split_inherited_prefix(flattened, 999) == (flattened, [])
    # non-numeric garbage -> no prefix
    assert split_inherited_prefix(flattened, 'garbage') == ([], flattened)
    # empty payload
    assert split_inherited_prefix([], 4) == ([], [])
    assert split_inherited_prefix(None, 2) == ([], [])


def test_compaction_boundary_never_lands_in_inherited_prefix():
    """The boundary is computed over the own-message list only, so every
    boundary it can possibly produce indexes an own-thread message: the
    checkpoint id is thread-local and the inherited prefix survives intact in
    the recomposed payload."""
    inherited, own = flattened_thread_payload()
    prefix, own_messages = split_inherited_prefix([*inherited, *own], len(inherited))

    prefix_ids = {m['id'] for m in prefix}
    own_ids = {m['id'] for m in own_messages}

    for boundary in range(len(own_messages)):
        compacted = own_messages[:boundary]
        recent = own_messages[boundary:]
        # checkpoint id (recent[0]) is always an own-thread message id
        assert recent[0]['id'] in own_ids
        assert recent[0]['id'] not in prefix_ids
        # nothing from the inherited prefix is ever in the compacted slice
        assert all(m['id'] not in prefix_ids for m in compacted)
        # recomposed payload keeps the full inherited prefix, in order
        recomposed = [*prefix, *recent]
        assert [m['id'] for m in recomposed[: len(prefix)]] == [m['id'] for m in prefix]


# ---------------------------------------------------------------------------
# own_history_is_first_exchange: title-fallback gating
# ---------------------------------------------------------------------------


def test_title_gate_true_for_first_own_exchange():
    own_messages = [
        {'id': 'B1', 'role': 'user', 'content': 'q'},
        {'id': 'B2', 'role': 'assistant', 'content': 'a'},
    ]
    own_map = {'B1': own_messages[0], 'B2': own_messages[1]}
    assert own_history_is_first_exchange(own_messages, own_map) is True
    # legacy tolerance retained: missing/empty map still allows the fallback
    assert own_history_is_first_exchange(own_messages, None) is True
    assert own_history_is_first_exchange(own_messages, {}) is True


def test_title_gate_false_for_longer_own_history():
    own_map = linear_map(['B1', 'B2', 'B3', 'B4'])
    own_messages = [own_map['B1'], own_map['B2'], own_map['B3'], own_map['B4']]
    assert own_history_is_first_exchange(own_messages, own_map) is False
    # sibling branches in the map also block the fallback (map larger than chain)
    assert own_history_is_first_exchange(own_messages[:2], own_map) is False


def test_title_gate_uses_own_thread_count_not_flattened_count():
    """A young thread with a long inherited prefix must still gate True on its
    OWN history -- and would wrongly gate False if the flattened payload were
    used instead."""
    chats, maps = thread_family()
    context, inherited_count = resolve_with_prefix(chats['competitors'], 'B2', chats, maps)

    own_messages = context[inherited_count:]
    own_map = maps['competitors']
    assert len(context) > 2  # flattened count would fail a len == 2 gate
    assert own_history_is_first_exchange(own_messages, own_map) is True
    # the flattened payload must never be fed to the gate
    assert own_history_is_first_exchange(context, own_map) is False
