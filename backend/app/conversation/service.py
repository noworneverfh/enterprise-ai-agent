from datetime import datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.conversation.models import Conversation, Message
from app.conversation.schemas import ConversationCreate, MessageCreate


def create_conversation(
    db: Session,
    conversation_data: ConversationCreate | None = None,
    title: str | None = None,
) -> Conversation:
    """Create one conversation."""

    if conversation_data is None:
        conversation_data = ConversationCreate(
            conversation_id=_generate_conversation_id(),
            title=title,
        )

    conversation = Conversation(**conversation_data.model_dump())
    db.add(conversation)
    db.commit()
    db.refresh(conversation)
    return conversation


def get_conversation(
    db: Session,
    conversation_id: str,
) -> Conversation | None:
    """Return one conversation by external conversation id."""

    return db.scalar(
        select(Conversation).where(Conversation.conversation_id == conversation_id)
    )


def add_message(
    db: Session,
    conversation: Conversation,
    message_data: MessageCreate | None = None,
    *,
    role: str | None = None,
    content: str | None = None,
) -> Message:
    """Save one message for a conversation."""

    if message_data is None:
        if role is None or content is None:
            raise ValueError("role and content are required when message_data is absent.")
        message_data = MessageCreate(role=role, content=content)

    message = Message(
        conversation_id=conversation.conversation_id,
        **message_data.model_dump(),
    )
    conversation.updated_at = datetime.utcnow()
    db.add(message)
    db.commit()
    db.refresh(message)
    return message


def get_recent_messages(
    db: Session,
    conversation_id: str,
    limit: int = 20,
) -> list[Message]:
    """Return recent messages by conversation id in chronological order."""

    conversation = get_conversation(db, conversation_id)
    if conversation is None:
        return []

    return list_recent_messages(db, conversation, limit=limit)


def list_recent_messages(
    db: Session,
    conversation: Conversation,
    limit: int = 20,
) -> list[Message]:
    """Return recent messages for one conversation in chronological order."""

    recent_messages = list(
        db.scalars(
            select(Message)
            .where(Message.conversation_id == conversation.conversation_id)
            .order_by(Message.created_at.desc(), Message.id.desc())
            .limit(limit)
        ).all()
    )
    return list(reversed(recent_messages))


def _generate_conversation_id() -> str:
    return f"conv-{uuid4().hex}"
