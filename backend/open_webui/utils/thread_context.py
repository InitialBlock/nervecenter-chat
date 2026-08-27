"""Context assembly for hierarchical chat threads (Git-like branching).

A thread is a ``Chat`` row whose ``parent_chat_id`` points at its parent chat
and whose ``branch_from_message_id`` names the message in the parent where the
thread branched off. The model context for a thread is:

    each ancestor's messages from its root up to that ancestor's recorded
    branch point (root-most ancestor first), followed by the thread's own
    active message chain.

Key decisions implemented here:

- Frozen path, live content (KTD3): each ancestor segment is linearized by
  walking the branch message's own recorded ``parentId`` chain back to the
  segment root -- never the ancestor's live tip/``currentId``. Message content
  is re-read live on every call.
- Corruption guards (KTD4): the cross-chat parent walk carries a visited-set
  cycle guard and a hard depth cap (default 1000). Broken pointers (missing
  ancestor chat, missing branch message) degrade to a skipped segment with a
  logged warning -- never an exception.
- Ownership: an ancestor chat owned by a different user is treated as
  unresolvable (skipped with a warning), so a corrupted or malicious
  cross-user pointer can never leak another user's chat into the context.

Module-level imports are deliberately stdlib-only so the pure function is
importable and testable without any app config or env vars; DB access is
imported lazily inside the resolver.
"""

import logging
from typing import Any, Optional

log = logging.getLogger(__name__)

# Mirrors MESSAGE_REPLAY_KEYS in open_webui/utils/middleware.py (importing it
# from there would pull in the full app config at import time). Keep in sync.
MESSAGE_REPLAY_KEYS = ('id', 'role', 'content', 'output', 'files', 'contextSummary', 'usage', 'model')

# Hard cap on the cross-chat ancestor walk. This is a pure corruption guard,
# not a product limit on thread nesting depth.
MAX_THREAD_DEPTH = 1000


def _get_message_chain(messages_map: dict, message_id: Optional[str]) -> list[dict]:
    """Linearize a message chain root -> ``message_id`` by walking ``parentId``.

    Mirrors ``get_message_list`` in ``open_webui/utils/misc.py`` (kept local so
    this module stays free of heavy imports), including its visited-set guard
    against cycles in a corrupted ``parentId`` chain.
    """
    if not messages_map or not message_id:
        return []

    current_message = messages_map.get(message_id)
    if not current_message:
        return []

    message_list = []
    visited_message_ids = set()

    # Track the map keys, not the messages' own 'id' field: a message may omit it
    while current_message and message_id not in visited_message_ids:
        visited_message_ids.add(message_id)
        message_list.append(current_message)

        message_id = current_message.get('parentId')
        current_message = messages_map.get(message_id) if message_id else None

    message_list.reverse()
    return message_list


def _project_message(message: dict, *, strip_context_summary: bool) -> dict:
    """Project a raw history message to the replay shape used for LLM payloads.

    Same projection as ``load_messages_from_db`` in
    ``open_webui/utils/middleware.py``. Inherited ancestor-segment messages
    additionally drop ``contextSummary``: an already-compacted ancestor must
    not truncate the inherited prefix. The thread's own messages keep theirs.
    """
    return {
        k: v
        for k, v in message.items()
        if k in MESSAGE_REPLAY_KEYS and not (strip_context_summary and k == 'contextSummary')
    }


def build_thread_context(
    ancestor_segments: list[tuple[Optional[dict], Optional[str]]],
    own_segment: tuple[Optional[dict], Optional[str]],
) -> list[dict]:
    """Flatten a thread's inherited + own message chains into one context list.

    Pure and deterministic: no I/O, no DB.

    :param ancestor_segments: ordered root-most first; each item is
        ``(messages_map, branch_from_message_id)`` -- the ancestor chat's
        message map and the id of the message where the *child* branched off.
        A segment whose branch message cannot be resolved in its map is
        skipped with a warning (KTD4/R8); the remaining segments still apply.
    :param own_segment: ``(messages_map, target_message_id)`` for the thread
        itself. ``target_message_id=None`` yields inherited context only.
    :return: flattened list of projected messages, root-most first.
    """
    context: list[dict] = []

    for index, (messages_map, branch_from_message_id) in enumerate(ancestor_segments):
        chain = _get_message_chain(messages_map or {}, branch_from_message_id)
        if not chain:
            log.warning(
                'Thread context: skipping unresolvable ancestor segment %d '
                '(branch message %r missing from ancestor history)',
                index,
                branch_from_message_id,
            )
            continue
        context.extend(_project_message(message, strip_context_summary=True) for message in chain)

    own_messages_map, target_message_id = own_segment
    if target_message_id is not None:
        own_chain = _get_message_chain(own_messages_map or {}, target_message_id)
        if not own_chain:
            log.warning(
                "Thread context: target message %r not found in the thread's own history",
                target_message_id,
            )
        context.extend(_project_message(message, strip_context_summary=False) for message in own_chain)

    return context


def split_inherited_prefix(messages: list, inherited_count: Any) -> tuple[list, list]:
    """Split a flattened thread payload into (inherited_prefix, own_messages).

    ``inherited_count`` is the value recorded by the completion pipeline
    (``metadata['thread_inherited_message_count']``); it is untrusted here and
    clamped to ``[0, len(messages)]``, with any non-numeric value treated as 0
    so a normal chat (no thread metadata) always yields an empty prefix.
    """
    messages = messages or []
    try:
        count = int(inherited_count or 0)
    except (TypeError, ValueError):
        count = 0
    count = max(0, min(count, len(messages)))
    return messages[:count], messages[count:]


def own_history_is_first_exchange(own_messages: list, own_messages_map: Optional[dict]) -> bool:
    """True when a chat's OWN history is exactly its first user/assistant pair.

    Used by the new-chat title fallback in
    ``open_webui/utils/middleware.py``. Both arguments must come from the
    chat's own row (its own message chain and message map) — never from the
    flattened post-inheritance payload — so a young thread with a long
    inherited prefix still gets an auto-generated title.
    """
    return len(own_messages or []) == 2 and (not own_messages_map or len(own_messages_map) <= 2)


async def assemble_thread_context(
    chat: Any,
    target_message_id: Optional[str],
    user_id: Optional[str] = None,
    *,
    max_depth: int = MAX_THREAD_DEPTH,
    get_chat=None,
    get_messages_map=None,
) -> list[dict]:
    """Resolve a thread's full model context, inherited segments included.

    Thin wrapper over :func:`assemble_thread_context_with_prefix` that drops
    the inherited-prefix length.
    """
    context, _ = await assemble_thread_context_with_prefix(
        chat,
        target_message_id,
        user_id,
        max_depth=max_depth,
        get_chat=get_chat,
        get_messages_map=get_messages_map,
    )
    return context


async def assemble_thread_context_with_prefix(
    chat: Any,
    target_message_id: Optional[str],
    user_id: Optional[str] = None,
    *,
    max_depth: int = MAX_THREAD_DEPTH,
    get_chat=None,
    get_messages_map=None,
) -> tuple[list[dict], int]:
    """Resolve a thread's full model context, inherited segments included.

    Walks ``parent_chat_id`` from ``chat`` up toward the root (visited-set
    cycle guard + ``max_depth`` cap), fetches each ancestor row and message
    map, applies the ownership check, then delegates to
    :func:`build_thread_context`.

    Any broken link (missing ancestor, cross-user ancestor, cycle, depth cap)
    degrades to skipping that segment and every root-most segment above it,
    with a logged warning -- never an exception (R8).

    :param chat: the thread's chat row (needs ``id``, ``parent_chat_id``,
        ``branch_from_message_id``; ``user_id`` checked against ancestors).
    :param target_message_id: tip of the thread's own active chain, or ``None``
        for inherited context only.
    :param user_id: the requesting thread's owner; ancestors owned by a
        different user are treated as unresolvable.
    :param max_depth: injectable corruption-guard cap on ancestor count.
    :param get_chat: ``async (chat_id) -> chat | None`` override (tests);
        defaults to ``Chats.get_chat_by_id``.
    :param get_messages_map: ``async (chat_id) -> dict | None`` override
        (tests); defaults to ``Chats.get_messages_map_by_chat_id``.
    :return: ``(context, inherited_count)`` where ``context[:inherited_count]``
        is the inherited ancestor prefix and the remainder is the thread's own
        chain. The completion pipeline records ``inherited_count`` so
        compaction can scope its boundary to the thread's own messages.
    """
    if get_chat is None or get_messages_map is None:
        # Imported lazily: pulling in the models layer at module import time
        # would drag the full app config along with it.
        from open_webui.models.chats import Chats

        get_chat = get_chat or Chats.get_chat_by_id
        get_messages_map = get_messages_map or Chats.get_messages_map_by_chat_id

    # Walk leaf-most -> root-most, collecting (messages_map, branch_message_id)
    # pairs; each child's branch_from_message_id lives in its *parent's* map.
    ancestor_segments: list[tuple[Optional[dict], Optional[str]]] = []
    visited_chat_ids = {getattr(chat, 'id', None)}
    parent_chat_id = getattr(chat, 'parent_chat_id', None)
    branch_from_message_id = getattr(chat, 'branch_from_message_id', None)
    depth = 0

    while parent_chat_id:
        if parent_chat_id in visited_chat_ids:
            log.warning(
                'Thread context: cycle detected in parent chain at chat %s; skipping root-most segments',
                parent_chat_id,
            )
            break
        if depth >= max_depth:
            log.warning(
                'Thread context: parent chain exceeds depth cap (%d); skipping root-most segments',
                max_depth,
            )
            break
        visited_chat_ids.add(parent_chat_id)
        depth += 1

        ancestor = await get_chat(parent_chat_id)
        if ancestor is None:
            log.warning(
                'Thread context: ancestor chat %s not found; skipping root-most segments',
                parent_chat_id,
            )
            break
        if user_id is not None and getattr(ancestor, 'user_id', None) != user_id:
            log.warning(
                'Thread context: ancestor chat %s is owned by a different user; skipping root-most segments',
                parent_chat_id,
            )
            break
        if not branch_from_message_id:
            log.warning(
                'Thread context: missing branch_from_message_id for ancestor chat %s; skipping root-most segments',
                parent_chat_id,
            )
            break

        messages_map = await get_messages_map(parent_chat_id)
        ancestor_segments.append((messages_map or {}, branch_from_message_id))

        branch_from_message_id = getattr(ancestor, 'branch_from_message_id', None)
        parent_chat_id = getattr(ancestor, 'parent_chat_id', None)

    ancestor_segments.reverse()

    own_messages_map: Optional[dict] = None
    if target_message_id is not None:
        own_messages_map = await get_messages_map(getattr(chat, 'id', None))

    # Built in two passes (equivalent to one build_thread_context call over
    # both segments) so the inherited-prefix length is known exactly.
    inherited_context = build_thread_context(ancestor_segments, ({}, None))
    own_context = build_thread_context([], (own_messages_map or {}, target_message_id))
    return [*inherited_context, *own_context], len(inherited_context)


async def assemble_thread_transcript(
    chat: Any,
    target_message_id: Optional[str],
    user_id: Optional[str] = None,
    *,
    max_depth: int = MAX_THREAD_DEPTH,
    get_chat=None,
    get_messages_map=None,
) -> tuple[dict, list[dict]]:
    """Materialize a thread's full inherited + own transcript as a history dict.

    Resolves the thread's flattened context via
    :func:`assemble_thread_context` and rebuilds it as a self-contained,
    strictly linear Open WebUI ``history`` (fresh ``parentId``/``childrenIds``
    links, ``currentId`` at the tail) — the shape share snapshots, clones, and
    forks need so a thread copy is a full transcript rather than a
    mid-conversation fragment (R16).

    Every messages map fetched during assembly is recorded so per-message
    fields the replay projection drops (``timestamp``, ``done``, ``models``,
    ...) are restored from the real source messages; only messages with no
    resolvable source get synthesized values. Same degradation semantics as
    :func:`assemble_thread_context` — never raises for broken links.

    :return: ``(history, ordered_messages)`` as produced by
        ``build_transcript_history``.
    """
    if get_chat is None or get_messages_map is None:
        # Imported lazily: see assemble_thread_context_with_prefix.
        from open_webui.models.chats import Chats

        get_chat = get_chat or Chats.get_chat_by_id
        get_messages_map = get_messages_map or Chats.get_messages_map_by_chat_id

    raw_messages_by_id: dict = {}

    async def recording_get_messages_map(chat_id):
        messages_map = await get_messages_map(chat_id)
        for message_id, message in (messages_map or {}).items():
            if isinstance(message, dict):
                raw_messages_by_id.setdefault(message_id, message)
        return messages_map

    context = await assemble_thread_context(
        chat,
        target_message_id,
        user_id,
        max_depth=max_depth,
        get_chat=get_chat,
        get_messages_map=recording_get_messages_map,
    )

    # Lazy so this module stays importable with stdlib only (chat_fork is
    # stdlib-only too, but keep the letter of the module contract).
    from open_webui.utils.chat_fork import build_transcript_history

    return build_transcript_history(context, raw_messages_by_id=raw_messages_by_id)
