from astrbot.core.message.components import Reply
from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import (
    AiocqhttpMessageEvent,
)

from .model import BroadcastTarget, TargetType
from .service import BroadcastService


def parse_target_type(
    text: str = "",
    *,
    strict: bool = False,
    default: TargetType = "group",
) -> TargetType | None:
    """Parse a group or friend target type.

    Args:
        text: User-provided target type text.
        strict: Return None instead of the default for unknown text.
        default: Target type used for empty or unknown non-strict input.

    Returns:
        Parsed target type, the default, or None in strict mode.
    """
    value = text.strip().lower()
    if value in ("好友", "私聊", "friend", "f"):
        return "friend"
    if value in ("群聊", "群", "group", "g"):
        return "group"
    if strict and value:
        return None
    return default


def parse_target_and_index(
    first_argument: str = "",
    second_argument: str = "",
) -> tuple[TargetType, int | None, str | None]:
    """Parse enable or disable command arguments.

    Args:
        first_argument: Optional target type or group index.
        second_argument: Optional target index.

    Returns:
        Target type, optional one-based index, and optional error message.
    """
    first = first_argument.strip()
    second = second_argument.strip()
    if first.isdigit() and not second:
        index = int(first)
        if index <= 0:
            return "group", None, "序号必须大于 0"
        return "group", index, None
    if not first:
        return "group", None, None

    target_type = parse_target_type(first, strict=True)
    if target_type is None:
        return (
            "group",
            None,
            "参数错误，格式：[群聊|私聊] [序号]",
        )
    if not second:
        return target_type, None, None
    if not second.isdigit() or int(second) <= 0:
        return target_type, None, "序号必须是正整数"
    return target_type, int(second), None


def get_reply_id(event: AiocqhttpMessageEvent) -> str | int | None:
    """Return the quoted message ID from an event.

    Args:
        event: Current OneBot message event.

    Returns:
        Quoted message ID, if present.
    """
    for segment in event.get_messages():
        if isinstance(segment, Reply):
            return segment.id
    return None


async def resolve_command_target(
    event: AiocqhttpMessageEvent,
    service: BroadcastService,
    target_type: TargetType,
    index: int | None,
) -> BroadcastTarget | None:
    """Resolve a command target from the current session or an admin index.

    Args:
        event: Current OneBot message event.
        service: Broadcast service used to list platform targets.
        target_type: Group or friend target type.
        index: Optional one-based admin list index.

    Returns:
        Resolved target, or None when it cannot be found.

    Raises:
        ValueError: If an administrator provides an out-of-range index.
    """
    targets = await service.list_targets(event.bot, target_type)
    if index and event.is_admin():
        if not targets:
            raise ValueError("当前没有可选会话")
        if index > len(targets):
            raise ValueError(f"序号 {index} 超出范围，可用范围：1-{len(targets)}")
        return targets[index - 1]

    current_id = (
        str(event.get_group_id())
        if target_type == "group" and event.get_group_id()
        else str(event.get_sender_id())
        if target_type == "friend"
        else ""
    )
    target = next(
        (item for item in targets if item.target_id == current_id),
        None,
    )
    if target is None and target_type == "friend" and current_id:
        return BroadcastTarget("friend", current_id, current_id)
    return target
