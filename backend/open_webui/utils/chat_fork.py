import time
from copy import deepcopy
from typing import Optional


def build_fork_history(messages_map: dict, source_message_id: str) -> tuple[dict, list[dict]]:
    if not messages_map:
        raise ValueError('chat has no messages to fork')

    branch: list[tuple[str, dict]] = []
    seen: set[str] = set()
    message_id = source_message_id

    while message_id:
        if message_id in seen:
            raise ValueError('message branch contains a cycle')
        seen.add(message_id)

        message = messages_map.get(message_id)
        if not isinstance(message, dict):
            raise ValueError('message not found')

        branch.append((message_id, message))
        message_id = message.get('parentId')

    fork_messages: dict[str, dict] = {}
    ordered_messages: list[dict] = []
    parent_id = None

    for message_id, message in reversed(branch):
        copied = deepcopy(message)
        copied['id'] = message_id
        copied['parentId'] = parent_id
        copied['childrenIds'] = []

        if parent_id:
            fork_messages[parent_id]['childrenIds'] = [message_id]

        fork_messages[message_id] = copied
        ordered_messages.append(copied)
        parent_id = message_id

    return {'messages': fork_messages, 'currentId': source_message_id}, ordered_messages


def build_transcript_history(
    messages: list[dict],
    *,
    raw_messages_by_id: Optional[dict] = None,
    default_timestamp: Optional[int] = None,
) -> tuple[dict, list[dict]]:
    """Materialize an ordered flat message list into a full Open WebUI history.

    Used to turn a thread's assembled context (inherited ancestor segments +
    own chain, as produced by ``assemble_thread_context``) into a
    self-contained transcript for share snapshots, clones, and forks. Pure:
    no I/O, never mutates its inputs.

    Returns ``(history, ordered_messages)`` where ``history`` is
    ``{'messages': {id: message}, 'currentId': last_id_or_None}`` — a strictly
    linear chain: each message's ``parentId`` is the previous message's id,
    ``childrenIds`` is ``[next_id]`` (``[]`` at the tail), matching the shape
    :func:`build_fork_history` produces for copied chains.

    The assembled input is MESSAGE_REPLAY_KEYS-projected (no timestamps or UI
    fields). ``raw_messages_by_id`` optionally maps message id -> the raw
    source-history message; when a raw message is available it is used as the
    base so display fields (``timestamp``, ``done``, ``models``, ...) survive,
    with the projected message overlaid on top so the projection stays
    authoritative for replay fields. ``contextSummary`` is dropped from the raw
    base first: whether a message keeps its summary is the projection's call
    (inherited messages had it deliberately stripped). For messages with no
    raw source, ``timestamp`` is synthesized as ``default_timestamp`` (now, by
    default) and assistant messages get ``done: True`` so a viewer never
    renders them as still streaming.

    Messages without an ``id``, or repeating an already-seen id, are skipped;
    the chain stays consistent either way.
    """
    if default_timestamp is None:
        default_timestamp = int(time.time())
    raw_messages_by_id = raw_messages_by_id or {}

    transcript_messages: dict[str, dict] = {}
    ordered_messages: list[dict] = []
    parent_id = None

    for message in messages or []:
        if not isinstance(message, dict):
            continue
        message_id = message.get('id')
        if not message_id or message_id in transcript_messages:
            continue

        raw = raw_messages_by_id.get(message_id)
        copied = deepcopy(raw) if isinstance(raw, dict) else {}
        copied.pop('contextSummary', None)  # the projection decides if it's kept
        copied.update(deepcopy(message))

        copied['id'] = message_id
        copied['parentId'] = parent_id
        copied['childrenIds'] = []
        copied.setdefault('timestamp', default_timestamp)
        if copied.get('role') == 'assistant':
            copied.setdefault('done', True)

        if parent_id:
            transcript_messages[parent_id]['childrenIds'] = [message_id]

        transcript_messages[message_id] = copied
        ordered_messages.append(copied)
        parent_id = message_id

    return {'messages': transcript_messages, 'currentId': parent_id}, ordered_messages
