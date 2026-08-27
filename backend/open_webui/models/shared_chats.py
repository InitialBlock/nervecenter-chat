import logging
import time
import uuid
from typing import Optional

from open_webui.internal.db import Base, JSONField, get_async_db_context
from pydantic import BaseModel, ConfigDict
from sqlalchemy import JSON, BigInteger, Column, ForeignKey, Text, delete, select
from sqlalchemy.ext.asyncio import AsyncSession

log = logging.getLogger(__name__)

####################
# SharedChat DB Schema
####################


class SharedChat(Base):
    __tablename__ = 'shared_chat'

    id = Column(Text, primary_key=True)  # The share token (UUID) — used in /s/{id} URL
    chat_id = Column(Text, ForeignKey('chat.id', ondelete='CASCADE'), nullable=False)
    user_id = Column(Text, nullable=False)  # Who created this share

    title = Column(Text)
    chat = Column(JSON)  # Snapshot of chat JSON at share time

    created_at = Column(BigInteger)
    updated_at = Column(BigInteger)


class SharedChatModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    chat_id: str
    user_id: str

    title: str
    chat: dict

    created_at: int
    updated_at: int


class SharedChatResponse(BaseModel):
    id: str
    chat_id: str
    title: str
    share_id: Optional[str] = None  # Alias for id, for backward compat
    updated_at: int
    created_at: int


async def _snapshot_chat_payload(chat) -> dict:
    """Chat JSON to store in a share snapshot.

    Normal chats: the chat JSON as-is (unchanged behavior). Thread chats
    (``parent_chat_id`` set) would otherwise snapshot a mid-conversation
    fragment, so their snapshot's ``history`` (and legacy ``messages`` list)
    is replaced with the materialized full inherited + own transcript (R16).
    The source chat row is never modified — only the snapshot copy differs.

    Any unexpected failure degrades to the plain (fragment) snapshot with a
    logged error rather than blocking the share.
    """
    if not getattr(chat, 'parent_chat_id', None):
        return chat.chat  # normal chats: snapshot exactly what was stored before

    chat_payload = chat.chat if isinstance(chat.chat, dict) else {}
    try:
        from open_webui.utils.thread_context import materialize_transcript_payload

        snapshot = await materialize_transcript_payload(chat, chat_payload)
        return chat_payload if snapshot is None else snapshot
    except Exception:
        log.exception('Failed to materialize thread transcript for share snapshot of chat %s', chat.id)
        return chat_payload


####################
# Table Operations
####################


class SharedChatsTable:
    async def create(self, chat_id: str, user_id: str, db: Optional[AsyncSession] = None) -> Optional[SharedChatModel]:
        """
        Create a snapshot of the chat for link sharing.
        Returns the SharedChatModel with the share token as its id.
        """
        async with get_async_db_context(db) as db:
            from open_webui.models.chats import Chat

            chat = await db.get(Chat, chat_id)
            if not chat:
                return None

            share_id = str(uuid.uuid4())
            now = int(time.time())

            shared_chat = SharedChat(
                id=share_id,
                chat_id=chat_id,
                user_id=user_id,
                title=chat.title,
                chat=await _snapshot_chat_payload(chat),
                created_at=now,
                updated_at=now,
            )
            db.add(shared_chat)
            await db.commit()
            await db.refresh(shared_chat)

            return SharedChatModel.model_validate(shared_chat)

    async def update(self, share_id: str, db: Optional[AsyncSession] = None) -> Optional[SharedChatModel]:
        """
        Re-snapshot: update the shared chat with the current state of the original chat.
        """
        async with get_async_db_context(db) as db:
            from open_webui.models.chats import Chat

            shared_chat = await db.get(SharedChat, share_id)
            if not shared_chat:
                return None

            chat = await db.get(Chat, shared_chat.chat_id)
            if not chat:
                return None

            shared_chat.title = chat.title
            shared_chat.chat = await _snapshot_chat_payload(chat)
            shared_chat.updated_at = int(time.time())

            await db.commit()
            await db.refresh(shared_chat)
            return SharedChatModel.model_validate(shared_chat)

    async def get_by_id(self, share_id: str, db: Optional[AsyncSession] = None) -> Optional[SharedChatModel]:
        """Get a shared chat by its share token."""
        async with get_async_db_context(db) as db:
            shared_chat = await db.get(SharedChat, share_id)
            if shared_chat:
                return SharedChatModel.model_validate(shared_chat)
            return None

    async def get_by_chat_id(self, chat_id: str, db: Optional[AsyncSession] = None) -> Optional[SharedChatModel]:
        """Get the shared chat for a given original chat. Returns the most recent one."""
        async with get_async_db_context(db) as db:
            result = await db.execute(
                select(SharedChat).filter_by(chat_id=chat_id).order_by(SharedChat.updated_at.desc()).limit(1)
            )
            shared_chat = result.scalars().first()
            if shared_chat:
                return SharedChatModel.model_validate(shared_chat)
            return None

    async def get_by_user_id(
        self,
        user_id: str,
        filter: Optional[dict] = None,
        skip: int = 0,
        limit: int = 50,
        db: Optional[AsyncSession] = None,
    ) -> list[SharedChatResponse]:
        """List all shared chats created by a user."""
        async with get_async_db_context(db) as db:
            stmt = select(SharedChat).filter_by(user_id=user_id)

            if filter:
                query_key = filter.get('query')
                if query_key:
                    stmt = stmt.filter(SharedChat.title.ilike(f'%{query_key}%'))

                order_by = filter.get('order_by')
                direction = filter.get('direction')

                if order_by and direction:
                    col = getattr(SharedChat, order_by, None)
                    if not col:
                        raise ValueError('Invalid order_by field')
                    if direction.lower() == 'asc':
                        stmt = stmt.order_by(col.asc())
                    elif direction.lower() == 'desc':
                        stmt = stmt.order_by(col.desc())
                    else:
                        raise ValueError('Invalid direction for ordering')
            else:
                stmt = stmt.order_by(SharedChat.updated_at.desc())

            if skip:
                stmt = stmt.offset(skip)
            if limit:
                stmt = stmt.limit(limit)

            result = await db.execute(stmt)
            return [
                SharedChatResponse(
                    id=sc.chat_id,
                    chat_id=sc.chat_id,
                    title=sc.title,
                    share_id=sc.id,
                    updated_at=sc.updated_at,
                    created_at=sc.created_at,
                )
                for sc in result.scalars().all()
            ]

    async def delete_by_id(self, share_id: str, db: Optional[AsyncSession] = None) -> bool:
        """Delete a shared chat by its share token."""
        try:
            async with get_async_db_context(db) as db:
                await db.execute(delete(SharedChat).filter_by(id=share_id))
                await db.commit()
                return True
        except Exception:
            return False

    async def delete_by_chat_id(self, chat_id: str, db: Optional[AsyncSession] = None) -> bool:
        """Delete all shared chats for a given original chat."""
        try:
            async with get_async_db_context(db) as db:
                await db.execute(delete(SharedChat).filter_by(chat_id=chat_id))
                await db.commit()
                return True
        except Exception:
            return False

    async def delete_by_chat_ids(self, chat_ids: list[str], db: Optional[AsyncSession] = None) -> bool:
        """Delete all shared chats for the given original chats in one statement."""
        if not chat_ids:
            return True
        try:
            async with get_async_db_context(db) as db:
                await db.execute(delete(SharedChat).where(SharedChat.chat_id.in_(chat_ids)))
                await db.commit()
                return True
        except Exception:
            return False

    async def delete_all_by_user_id(self, user_id: str, db: Optional[AsyncSession] = None) -> bool:
        """Delete all shared chats created by a user."""
        try:
            async with get_async_db_context(db) as db:
                await db.execute(delete(SharedChat).filter_by(user_id=user_id))
                await db.commit()
                return True
        except Exception:
            return False


SharedChats = SharedChatsTable()
