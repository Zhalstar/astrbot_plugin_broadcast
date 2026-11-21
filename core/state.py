import json
from pathlib import Path

from astrbot.api import logger

from ..config import PluginConfig
from .model import BroadcastRecord, TargetType


class BroadcastState:
    """Persist broadcast message IDs and recall campaigns."""

    VERSION = 1

    def __init__(self, config: PluginConfig, state_path: Path):
        self.config = config
        self.state_path = state_path
        self._last_records: dict[str, BroadcastRecord] = {}
        self._campaigns: dict[str, list[BroadcastRecord]] = {}
        self._load()

    def get_last_record(
        self,
        self_id: str,
        target_type: TargetType,
        target_id: str,
    ) -> BroadcastRecord | None:
        """Return the latest broadcast record for a conversation.

        Args:
            self_id: Bot account identifier.
            target_type: Group or friend target type.
            target_id: Platform conversation identifier.

        Returns:
            Latest record for the conversation, if available.
        """
        return self._last_records.get(self._target_key(self_id, target_type, target_id))

    def get_campaign_records(
        self,
        self_id: str,
        source_message_id: str | int,
    ) -> tuple[BroadcastRecord, ...]:
        """Return recallable records created from a source message.

        Args:
            self_id: Bot account identifier.
            source_message_id: Original quoted message identifier.

        Returns:
            Immutable view of matching broadcast records.
        """
        records = self._campaigns.get(
            self._campaign_key(self_id, source_message_id), []
        )
        return tuple(records)

    def add_record(self, record: BroadcastRecord) -> None:
        """Store a successful broadcast record.

        Args:
            record: Captured target message record.
        """
        self._last_records[
            self._target_key(record.self_id, record.target_type, record.target_id)
        ] = record
        campaign_key = self._campaign_key(record.self_id, record.source_message_id)
        campaign = self._campaigns.setdefault(campaign_key, [])
        if not any(
            item.target_type == record.target_type
            and item.target_id == record.target_id
            and item.broadcast_message_id == record.broadcast_message_id
            for item in campaign
        ):
            campaign.append(record)
        self._trim_campaigns()
        self._save()

    def remove_record(self, record: BroadcastRecord) -> None:
        """Remove a successfully recalled broadcast record.

        Args:
            record: Record whose platform message was deleted.
        """
        target_key = self._target_key(
            record.self_id, record.target_type, record.target_id
        )
        latest = self._last_records.get(target_key)
        if latest and latest.broadcast_message_id == record.broadcast_message_id:
            self._last_records.pop(target_key, None)

        campaign_key = self._campaign_key(record.self_id, record.source_message_id)
        campaign = self._campaigns.get(campaign_key, [])
        remaining = [
            item
            for item in campaign
            if not (
                item.target_type == record.target_type
                and item.target_id == record.target_id
                and item.broadcast_message_id == record.broadcast_message_id
            )
        ]
        if remaining:
            self._campaigns[campaign_key] = remaining
        else:
            self._campaigns.pop(campaign_key, None)
        self._save()

    def _load(self) -> None:
        if not self.state_path.exists():
            return
        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("state root must be an object")

            raw_last_records = data.get("last_records", {})
            if isinstance(raw_last_records, dict):
                for key, raw_record in raw_last_records.items():
                    if not isinstance(raw_record, dict):
                        continue
                    record = BroadcastRecord.from_dict(raw_record)
                    if record:
                        self._last_records[str(key)] = record

            raw_campaigns = data.get("campaigns", {})
            if isinstance(raw_campaigns, dict):
                for key, raw_records in raw_campaigns.items():
                    if not isinstance(raw_records, list):
                        continue
                    records = [
                        record
                        for raw_record in raw_records
                        if isinstance(raw_record, dict)
                        and (record := BroadcastRecord.from_dict(raw_record))
                    ]
                    if records:
                        self._campaigns[str(key)] = records
            self._trim_campaigns()
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            logger.exception("Failed to load broadcast state; using empty state")
            self._last_records.clear()
            self._campaigns.clear()

    def _save(self) -> None:
        data = {
            "version": self.VERSION,
            "last_records": {
                key: record.to_dict() for key, record in self._last_records.items()
            },
            "campaigns": {
                key: [record.to_dict() for record in records]
                for key, records in self._campaigns.items()
            },
        }
        temporary_path = self.state_path.with_suffix(f"{self.state_path.suffix}.tmp")
        try:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            temporary_path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            temporary_path.replace(self.state_path)
        except OSError:
            logger.exception("Failed to persist broadcast state")
            temporary_path.unlink(missing_ok=True)

    def _trim_campaigns(self) -> None:
        excess = len(self._campaigns) - self.config.record_retention_count
        if excess <= 0:
            return
        oldest_keys = sorted(
            self._campaigns,
            key=lambda key: max(
                (record.sent_at for record in self._campaigns[key]), default=0
            ),
        )[:excess]
        for key in oldest_keys:
            self._campaigns.pop(key, None)

    @staticmethod
    def _target_key(
        self_id: str,
        target_type: TargetType,
        target_id: str,
    ) -> str:
        return f"{self_id}:{target_type}:{target_id}"

    @staticmethod
    def _campaign_key(self_id: str, source_message_id: str | int) -> str:
        return f"{self_id}:{source_message_id}"
