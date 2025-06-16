import collections
import json
import typing
import datetime


class Message:
    role: str
    content: str
    timestamp: typing.Optional[datetime.datetime]

    ROLE_USER = "user"
    ROLE_ASSISTANT = "assistant"
    ROLE_SYSTEM = "system"
    ROLE_FUNCTION = "function"

    VALID_ROLES = {ROLE_USER, ROLE_ASSISTANT, ROLE_SYSTEM, ROLE_FUNCTION}

    def __init__(self, role: str, content: str, timestamp: typing.Optional[datetime.datetime] = None):
        if role not in self.VALID_ROLES:
            raise ValueError(f"Некорректная роль: {role}. Должна быть одна из: {', '.join(self.VALID_ROLES)}")

        if not content or not content.strip():
            raise ValueError("Сообщение не может быть пустым")

        self.role = role
        self.content = content.strip()
        self.timestamp = timestamp if timestamp else datetime.datetime.now()

    def to_dict(self) -> dict:
        return {
            "role": self.role,
            "content": self.content,
        }

    def __str__(self) -> str:
        return f"Message(role='{self.role}', content='{self.content}')"

    def __repr__(self) -> str:
        return f"Message(role='{self.role}', content='{self.content}', timestamp='{self.timestamp}')"

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)


class MessageHistory:
    messages: list[Message]
    max_messages: typing.Optional[int]
    _iterator_index: int

    def __init__(self, max_messages: typing.Optional[int] = None) -> None:
        self.messages: list[Message] = []
        self.max_messages = max_messages
        self._iterator_index = 0

    def add_message(self, role: str, content: str):
        message = Message(role=role, content=content)
        self.messages.append(message)
        if self.max_messages and len(self.messages) > self.max_messages:
            self.messages = self.messages[-self.max_messages:]
        return self

    def clear(self) -> None:
        self.messages.clear()
        self._iterator_index = 0

    def pop(self):
        return self.messages.pop()

    def get_last_n_messages(self, n: int) -> list[Message]:
        return self.messages[-n:] if n > 0 else []

    def to_api_format(self) -> list[dict]:
        return [msg.to_dict() for msg in self.messages]

    def to_json(self) -> list[dict]:
        return self.to_api_format()

    def __len__(self) -> int:
        return len(self.messages)

    def __str__(self) -> str:
        return f"MessageHistory(messages={len(self.messages)})"

    def __iter__(self) -> typing.Iterator[Message]:
        self._iterator_index = 0
        return self

    def __next__(self) -> Message:
        if self._iterator_index >= len(self.messages):
            raise StopIteration
        message = self.messages[self._iterator_index]
        self._iterator_index += 1
        return message

    def __getitem__(self, index: int) -> Message:
        return self.messages[index]


class MessageHistoryManager:
    def __init__(self, default_max_messages: typing.Optional[int] = None) -> None:
        self.default_max_messages = default_max_messages
        self._histories: dict[int, MessageHistory] = collections.defaultdict(
            lambda: MessageHistory(max_messages=default_max_messages)
        )

    def __getitem__(self, user_id: int) -> MessageHistory:
        return self._histories[user_id]

    def __iter__(self) -> typing.Iterator[int]:
        return iter(self._histories)

    def __contains__(self, user_id: int) -> bool:
        return user_id in self._histories

    def get_user_ids(self) -> list[int]:
        return list(self._histories.keys())

    def remove_user(self, user_id: int) -> None:
        if user_id in self._histories:
            del self._histories[user_id]

    def clear_all(self) -> None:
        self._histories.clear()

    def to_json(self) -> str:
        histories_as_dict = {
            user_id: history.to_api_format() for user_id, history in self._histories.items()
        }
        return json.dumps(histories_as_dict, ensure_ascii=False)

    def __len__(self) -> int:
        return len(self._histories)
