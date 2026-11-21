import asyncio
import hashlib
import json
import time
from typing import Any

from aiocqhttp import CQHttp

from astrbot.api import logger

from ..config import PluginConfig
from .model import (
    BroadcastFailure,
    BroadcastRecord,
    BroadcastResult,
    BroadcastScope,
    BroadcastTarget,
    RecallResult,
    TargetType,
)
from .state import BroadcastState


class BroadcastService:
    """Provide event-independent broadcast operations for OneBot clients."""

    def __init__(self, config: PluginConfig, state: BroadcastState):
        self.config = config
        self.state = state

    async def list_targets(
        self,
        client: CQHttp,
        target_type: TargetType,
    ) -> list[BroadcastTarget]:
        """List available groups or friends.

        Args:
            client: OneBot client used to query platform targets.
            target_type: Group or friend target type.

        Returns:
            Sorted platform targets with display names.
        """
        if target_type == "group":
            groups = await client.get_group_list()
            return sorted(
                [
                    BroadcastTarget(
                        target_type="group",
                        target_id=str(group["group_id"]),
                        name=str(group.get("group_name") or group["group_id"]),
                    )
                    for group in groups
                ],
                key=lambda target: int(target.target_id),
            )

        friends = await client.get_friend_list()
        return sorted(
            [
                BroadcastTarget(
                    target_type="friend",
                    target_id=str(friend["user_id"]),
                    name=str(
                        friend.get("remark")
                        or friend.get("nickname")
                        or friend["user_id"]
                    ),
                )
                for friend in friends
            ],
            key=lambda target: int(target.target_id),
        )

    def enable_target(self, target: BroadcastTarget) -> bool:
        """Enable broadcasting for a target.

        Args:
            target: Target to enable.

        Returns:
            True when configuration changed.
        """
        return self.config.enable_target(target.target_type, target.target_id)

    def disable_target(self, target: BroadcastTarget) -> bool:
        """Disable broadcasting for a target.

        Args:
            target: Target to disable.

        Returns:
            True when configuration changed.
        """
        return self.config.disable_target(target.target_type, target.target_id)

    async def broadcast(
        self,
        client: CQHttp,
        *,
        source_message_id: str | int,
        scope: BroadcastScope,
        self_id: str,
        skip_recent: bool = True,
        source_target_type: TargetType | None = None,
        source_target_id: str | None = None,
    ) -> BroadcastResult:
        """Broadcast a source message with inactivity filtering and ID capture.

        Args:
            client: OneBot client used for platform API calls.
            source_message_id: Original message ID forwarded to each target.
            scope: Group, friend, or all-target broadcast scope.
            self_id: Bot account identifier used to identify sent history entries.
            skip_recent: Whether to skip targets containing the previous broadcast.
            source_target_type: Conversation type where the command was issued.
            source_target_id: Conversation ID where the command was issued.

        Returns:
            Detailed broadcast outcome including skipped and unresolved targets.
        """
        result = BroadcastResult()
        source_fingerprint = await self._get_source_fingerprint(
            client, source_message_id
        )

        try:
            for target_type in scope.target_types:
                targets = await self.list_targets(client, target_type)
                for target in targets:
                    if self.config.is_disabled(target.target_type, target.target_id):
                        continue
                    if (
                        self.config.skip_source
                        and source_target_type == target.target_type
                        and str(source_target_id) == target.target_id
                    ):
                        continue

                    await asyncio.sleep(self.config.get_broadcast_delay())
                    history_count = self.config.history_check_count
                    before_messages: list[dict[str, Any]] = []
                    history_available = True
                    try:
                        before_messages = await self._get_history(
                            client,
                            target,
                            history_count,
                        )
                    except Exception as exc:
                        history_available = False
                        logger.warning(
                            "Failed to query history before broadcasting to %s: %s",
                            target.key,
                            exc,
                        )

                    previous_record = self.state.get_last_record(
                        self_id,
                        target.target_type,
                        target.target_id,
                    )
                    if (
                        skip_recent
                        and history_available
                        and self.config.history_check_count > 0
                        and previous_record
                    ):
                        recent_messages = sorted(
                            before_messages,
                            key=self._message_sort_key,
                            reverse=True,
                        )[: self.config.history_check_count]
                        if any(
                            str(message.get("message_id"))
                            == previous_record.broadcast_message_id
                            for message in recent_messages
                        ):
                            result.skipped_targets.append(target)
                            continue

                    before_ids = {
                        str(message["message_id"])
                        for message in before_messages
                        if message.get("message_id") is not None
                    }
                    sent_at = int(time.time())
                    try:
                        await self._forward_message(
                            client,
                            target,
                            source_message_id,
                        )
                    except Exception as exc:
                        result.failed_targets.append(
                            BroadcastFailure(target=target, reason=str(exc))
                        )
                        logger.warning("Failed to broadcast to %s: %s", target.key, exc)
                        continue

                    broadcast_message_id = await self._capture_message_id(
                        client,
                        target=target,
                        self_id=self_id,
                        before_ids=before_ids,
                        sent_at=sent_at,
                        source_fingerprint=source_fingerprint,
                        history_count=history_count,
                    )
                    if broadcast_message_id is None:
                        result.unresolved_targets.append(target)
                        logger.warning(
                            "Broadcast succeeded but message ID was not resolved for %s",
                            target.key,
                        )
                        continue

                    record = BroadcastRecord(
                        self_id=str(self_id),
                        target_type=target.target_type,
                        target_id=target.target_id,
                        source_message_id=str(source_message_id),
                        broadcast_message_id=broadcast_message_id,
                        sent_at=sent_at,
                    )
                    self.state.add_record(record)
                    result.success_records.append(record)
        except asyncio.CancelledError:
            result.cancelled = True
            logger.info("Broadcast task was cancelled")

        return result

    async def recall(
        self,
        client: CQHttp,
        *,
        self_id: str,
        source_message_id: str | int,
    ) -> RecallResult:
        """Recall all retained broadcasts created from a source message.

        Args:
            client: OneBot client used to delete target messages.
            self_id: Bot account identifier that created the campaign.
            source_message_id: Original source message identifier.

        Returns:
            Recall outcome. Failed records remain persisted for retry.

        Raises:
            ValueError: If no recallable records exist for the source message.
        """
        records = self.state.get_campaign_records(self_id, source_message_id)
        if not records:
            raise ValueError("No broadcast records found for the source message")

        result = RecallResult()
        try:
            for record in records:
                try:
                    await client.call_action(
                        "delete_msg",
                        message_id=int(record.broadcast_message_id),
                    )
                except Exception as exc:
                    result.failed_records.append(record)
                    logger.warning(
                        "Failed to recall %s:%s message %s: %s",
                        record.target_type,
                        record.target_id,
                        record.broadcast_message_id,
                        exc,
                    )
                    continue
                self.state.remove_record(record)
                result.success_count += 1
        except asyncio.CancelledError:
            result.cancelled = True
            logger.info("Broadcast recall task was cancelled")
        return result

    async def _get_source_fingerprint(
        self,
        client: CQHttp,
        source_message_id: str | int,
    ) -> str | None:
        try:
            result = await client.get_msg(message_id=int(source_message_id))
        except Exception as exc:
            logger.warning("Failed to load source message fingerprint: %s", exc)
            return None
        if not isinstance(result, dict):
            return None
        return self._message_fingerprint(result.get("message"))

    async def _capture_message_id(
        self,
        client: CQHttp,
        *,
        target: BroadcastTarget,
        self_id: str,
        before_ids: set[str],
        sent_at: int,
        source_fingerprint: str | None,
        history_count: int,
    ) -> str | None:
        try:
            messages = await self._get_history(client, target, history_count)
        except Exception as exc:
            logger.warning(
                "Failed to query history after broadcasting to %s: %s",
                target.key,
                exc,
            )
            return

        candidates = []
        for message in messages:
            message_id = message.get("message_id")
            if message_id is None or str(message_id) in before_ids:
                continue
            sender = message.get("sender", {})
            sender_id = sender.get("user_id") if isinstance(sender, dict) else None
            if sender_id is not None and str(sender_id) != str(self_id):
                continue
            message_time = message.get("time")
            if isinstance(message_time, (int, float)) and message_time < sent_at - 2:
                continue
            candidates.append(message)

        if source_fingerprint:
            matching_candidates = [
                message
                for message in candidates
                if self._message_fingerprint(message.get("message"))
                == source_fingerprint
            ]
            if len(matching_candidates) == 1:
                return str(matching_candidates[0]["message_id"])

        if len(candidates) == 1:
            return str(candidates[0]["message_id"])

    async def _get_history(
        self,
        client: CQHttp,
        target: BroadcastTarget,
        count: int,
    ) -> list[dict[str, Any]]:
        if target.target_type == "group":
            result = await client.get_group_msg_history(
                group_id=int(target.target_id),
                count=count,
            )
        else:
            result = await client.get_friend_msg_history(
                user_id=int(target.target_id),
                count=count,
            )
        if not isinstance(result, dict) or not isinstance(result.get("messages"), list):
            return []
        return [message for message in result["messages"] if isinstance(message, dict)]

    async def _forward_message(
        self,
        client: CQHttp,
        target: BroadcastTarget,
        source_message_id: str | int,
    ) -> None:
        if target.target_type == "group":
            await client.forward_group_single_msg(
                group_id=int(target.target_id),
                message_id=source_message_id,
            )
        else:
            await client.forward_friend_single_msg(
                user_id=int(target.target_id),
                message_id=source_message_id,
            )

    @classmethod
    def _message_fingerprint(cls, message: Any) -> str | None:
        if not isinstance(message, list):
            return None
        normalized_segments = []
        for segment in message:
            if not isinstance(segment, dict):
                continue
            segment_type = str(segment.get("type", ""))
            raw_data = segment.get("data", {})
            data = {}
            if isinstance(raw_data, dict):
                data = {
                    str(key): value
                    for key, value in raw_data.items()
                    if key not in {"cache", "proxy", "timeout"}
                    and not (segment_type == "reply" and key == "id")
                }
            normalized_segments.append({"type": segment_type, "data": data})
        if not normalized_segments:
            return None
        serialized = json.dumps(
            normalized_segments,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    @staticmethod
    def _message_sort_key(message: dict[str, Any]) -> tuple[int, int, int]:
        values = []
        for key in ("time", "message_seq", "message_id"):
            try:
                values.append(int(message.get(key, 0)))
            except (TypeError, ValueError):
                values.append(0)
        return values[0], values[1], values[2]
