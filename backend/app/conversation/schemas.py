from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


MessageRole = Literal["user", "assistant", "system"]


class ConversationCreate(BaseModel):
    """Input for creating one conversation."""

    conversation_id: str
    title: str | None = None

    @field_validator("conversation_id")
    @classmethod
    def normalize_conversation_id(cls, conversation_id: str) -> str:
        normalized = conversation_id.strip()

        if not normalized:
            raise ValueError("conversation_id must not be empty.")

        return normalized

    @field_validator("title")
    @classmethod
    def normalize_title(cls, title: str | None) -> str | None:
        if title is None:
            return None

        normalized = title.strip()
        return normalized or None


class ConversationResponse(BaseModel):
    """Conversation data returned by service or API layers."""

    id: int
    conversation_id: str
    title: str | None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class MessageCreate(BaseModel):
    """Input for saving one message."""

    role: MessageRole
    content: str

    @field_validator("content")
    @classmethod
    def normalize_content(cls, content: str) -> str:
        normalized = content.strip()

        if not normalized:
            raise ValueError("content must not be empty.")

        return normalized


class MessageResponse(BaseModel):
    """Message data returned by service or API layers."""

    id: int
    conversation_id: str
    role: MessageRole
    content: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class RecentMessagesQuery(BaseModel):
    """Query parameters for recent conversation messages."""

    limit: int = Field(default=20, ge=1, le=100)
