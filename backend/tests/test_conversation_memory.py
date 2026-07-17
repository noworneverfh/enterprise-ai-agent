import sys
from collections.abc import Generator
from pathlib import Path

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool


BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from app.conversation import service as conversation_service  # noqa: E402
from app.conversation.models import Conversation, Message  # noqa: E402,F401
from app.conversation.schemas import ConversationCreate, MessageCreate  # noqa: E402
from app.db.base import Base  # noqa: E402


@pytest.fixture
def db_session() -> Generator[Session, None, None]:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
    )
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()

    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


def test_create_conversation(db_session: Session) -> None:
    conversation = conversation_service.create_conversation(
        db_session,
        title="Pump diagnosis",
    )

    assert conversation.id is not None
    assert conversation.conversation_id.startswith("conv-")
    assert conversation.title == "Pump diagnosis"
    assert conversation.created_at is not None
    assert conversation.updated_at is not None


def test_create_conversation_keeps_conversation_id_unique(
    db_session: Session,
) -> None:
    first = conversation_service.create_conversation(db_session)
    second = conversation_service.create_conversation(db_session)

    assert first.conversation_id != second.conversation_id


def test_save_message(db_session: Session) -> None:
    conversation = _create_conversation(db_session)

    message = conversation_service.add_message(
        db_session,
        conversation,
        MessageCreate(role="user", content="DEV-001 is overheating."),
    )

    assert message.id is not None
    assert message.conversation_id == "conv-001"
    assert message.role == "user"
    assert message.content == "DEV-001 is overheating."
    assert message.created_at is not None


def test_save_message_validates_role(db_session: Session) -> None:
    conversation = _create_conversation(db_session)

    with pytest.raises(ValidationError):
        conversation_service.add_message(
            db_session,
            conversation,
            role="invalid",
            content="hello",
        )


def test_save_multiple_messages(db_session: Session) -> None:
    conversation = _create_conversation(db_session)

    user_message = conversation_service.add_message(
        db_session,
        conversation,
        role="user",
        content="What caused E101?",
    )
    assistant_message = conversation_service.add_message(
        db_session,
        conversation,
        role="assistant",
        content="Check cooling and sensor data.",
    )

    assert user_message.role == "user"
    assert assistant_message.role == "assistant"
    assert assistant_message.id > user_message.id


def test_list_recent_messages(db_session: Session) -> None:
    conversation = _create_conversation(db_session)
    for index in range(5):
        conversation_service.add_message(
            db_session,
            conversation,
            MessageCreate(role="user", content=f"message {index}"),
        )

    messages = conversation_service.list_recent_messages(
        db_session,
        conversation,
        limit=3,
    )

    assert [message.content for message in messages] == [
        "message 2",
        "message 3",
        "message 4",
    ]


def test_get_recent_messages_by_conversation_id(db_session: Session) -> None:
    conversation = _create_conversation(db_session)
    for index in range(4):
        conversation_service.add_message(
            db_session,
            conversation,
            role="user",
            content=f"message {index}",
        )

    messages = conversation_service.get_recent_messages(
        db_session,
        "conv-001",
        limit=2,
    )

    assert [message.content for message in messages] == ["message 2", "message 3"]


def test_get_recent_messages_for_missing_conversation_returns_empty_list(
    db_session: Session,
) -> None:
    assert conversation_service.get_recent_messages(db_session, "missing") == []


def test_get_conversation_for_missing_id_returns_none(db_session: Session) -> None:
    assert conversation_service.get_conversation(db_session, "missing") is None


def test_conversation_id_unique_constraint(db_session: Session) -> None:
    _create_conversation(db_session)

    with pytest.raises(IntegrityError):
        conversation_service.create_conversation(
            db_session,
            ConversationCreate(conversation_id="conv-001", title="Duplicate"),
        )


def _create_conversation(db: Session) -> Conversation:
    return conversation_service.create_conversation(
        db,
        ConversationCreate(conversation_id="conv-001", title="Pump diagnosis"),
    )
