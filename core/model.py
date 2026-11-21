from dataclasses import dataclass, field
from enum import Enum
from typing import Literal

TargetType = Literal["group", "friend"]


class BroadcastScope(Enum):
    GROUP = ("group", "群聊", ("群", "群聊", "g", "group"))
    FRIEND = (
        "friend",
        "私聊",
        ("好友", "私聊", "f", "friend"),
    )
    ALL = ("all", "全部", ("全部", "a", "all"))

    def __init__(self, code: str, display_name: str, aliases: tuple[str, ...]):
        self.code = code
        self.display_name = display_name
        self.aliases = aliases

    @classmethod
    def parse(cls, text: str = "") -> "BroadcastScope":
        """Parse a command argument into a broadcast scope.

        Args:
            text: User-provided scope text. Empty text defaults to groups.

        Returns:
            Parsed broadcast scope.

        Raises:
            ValueError: If the scope text is not recognized.
        """
        value = text.strip().lower()
        if not value:
            return cls.GROUP
        for scope in cls:
            if value in scope.aliases:
                return scope
        raise ValueError(f"Unknown broadcast scope: {text}")

    @property
    def target_types(self) -> tuple[TargetType, ...]:
        """Return target types included in this scope.

        Returns:
            Target types represented by the scope.
        """
        if self is BroadcastScope.GROUP:
            return ("group",)
        if self is BroadcastScope.FRIEND:
            return ("friend",)
        return ("group", "friend")


@dataclass(frozen=True, slots=True)
class BroadcastTarget:
    target_type: TargetType
    target_id: str
    name: str = ""

    @property
    def key(self) -> str:
        """Return the stable target key.

        Returns:
            Target type and ID joined as a stable key.
        """
        return f"{self.target_type}:{self.target_id}"


@dataclass(frozen=True, slots=True)
class BroadcastRecord:
    self_id: str
    target_type: TargetType
    target_id: str
    source_message_id: str
    broadcast_message_id: str
    sent_at: int

    def to_dict(self) -> dict[str, str | int]:
        """Serialize the record for JSON persistence.

        Returns:
            JSON-compatible record mapping.
        """
        return {
            "self_id": self.self_id,
            "target_type": self.target_type,
            "target_id": self.target_id,
            "source_message_id": self.source_message_id,
            "broadcast_message_id": self.broadcast_message_id,
            "sent_at": self.sent_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "BroadcastRecord | None":
        """Deserialize a persisted broadcast record.

        Args:
            data: Persisted record mapping.

        Returns:
            Parsed record, or None when required data is invalid.
        """
        target_type = data.get("target_type")
        if target_type not in ("group", "friend"):
            return None
        required = (
            "self_id",
            "target_id",
            "source_message_id",
            "broadcast_message_id",
            "sent_at",
        )
        if any(data.get(key) is None for key in required):
            return None
        try:
            sent_at = int(data["sent_at"])
        except (TypeError, ValueError):
            return None
        return cls(
            self_id=str(data["self_id"]),
            target_type=target_type,
            target_id=str(data["target_id"]),
            source_message_id=str(data["source_message_id"]),
            broadcast_message_id=str(data["broadcast_message_id"]),
            sent_at=sent_at,
        )


@dataclass(frozen=True, slots=True)
class BroadcastFailure:
    target: BroadcastTarget
    reason: str


@dataclass(slots=True)
class BroadcastResult:
    success_records: list[BroadcastRecord] = field(default_factory=list)
    unresolved_targets: list[BroadcastTarget] = field(default_factory=list)
    skipped_targets: list[BroadcastTarget] = field(default_factory=list)
    failed_targets: list[BroadcastFailure] = field(default_factory=list)
    cancelled: bool = False

    @property
    def success_count(self) -> int:
        """Return the count of successfully sent targets.

        Returns:
            Recorded and unresolved successful sends.
        """
        return len(self.success_records) + len(self.unresolved_targets)

    @property
    def recorded_count(self) -> int:
        """Return the count of sends with captured message IDs.

        Returns:
            Number of persisted successful records.
        """
        return len(self.success_records)

    @property
    def skipped_count(self) -> int:
        """Return the inactivity skip count.

        Returns:
            Number of targets skipped by recent-history checks.
        """
        return len(self.skipped_targets)

    @property
    def failed_count(self) -> int:
        """Return the failed send count.

        Returns:
            Number of failed targets.
        """
        return len(self.failed_targets)


@dataclass(slots=True)
class RecallResult:
    success_count: int = 0
    failed_records: list[BroadcastRecord] = field(default_factory=list)
    cancelled: bool = False

    @property
    def failed_count(self) -> int:
        """Return the failed recall count.

        Returns:
            Number of records that remain available for retry.
        """
        return len(self.failed_records)
