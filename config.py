import random

from astrbot.core.config.astrbot_config import AstrBotConfig

from .core.model import TargetType


class PluginConfig:
    """Provide typed access to broadcast plugin configuration."""

    def __init__(self, config: AstrBotConfig):
        self._config = config
        self._config.setdefault("disable_gids", [])
        self._config.setdefault("disable_uids", [])

    @property
    def skip_source(self) -> bool:
        """Return whether the command source conversation is skipped.

        Returns:
            True when the source conversation should not receive the broadcast.
        """
        return bool(self._config.get("skip_source", True))

    @property
    def history_check_count(self) -> int:
        """Return the number of recent messages used for inactivity checks.

        Returns:
            Non-negative recent-history count.
        """
        try:
            return max(0, int(self._config.get("history_check_count", 10)))
        except (TypeError, ValueError):
            return 10

    @property
    def record_retention_count(self) -> int:
        """Return the maximum number of retained broadcast campaigns.

        Returns:
            Positive campaign retention count.
        """
        try:
            return max(1, int(self._config.get("record_retention_count", 100)))
        except (TypeError, ValueError):
            return 100

    def get_broadcast_delay(self) -> float:
        """Return a randomized per-target delay.

        Returns:
            Delay in seconds between zero and the configured maximum.
        """
        try:
            maximum = max(0.0, float(self._config.get("broadcast_max_delay", 1.1)))
        except (TypeError, ValueError):
            maximum = 1.1
        return random.uniform(0, maximum)

    def disabled_ids(self, target_type: TargetType) -> list[str]:
        """Return the mutable disabled-ID list for a target type.

        Args:
            target_type: Group or friend target type.

        Returns:
            Config-backed list containing disabled target IDs.
        """
        key = "disable_gids" if target_type == "group" else "disable_uids"
        values = self._config.get(key)
        if not isinstance(values, list):
            values = []
            self._config[key] = values
        return values

    def is_disabled(self, target_type: TargetType, target_id: str) -> bool:
        """Check whether a target is disabled.

        Args:
            target_type: Group or friend target type.
            target_id: Platform target identifier.

        Returns:
            True when the target is excluded from broadcasts.
        """
        return str(target_id) in self.disabled_ids(target_type)

    def enable_target(self, target_type: TargetType, target_id: str) -> bool:
        """Enable broadcasts for a target.

        Args:
            target_type: Group or friend target type.
            target_id: Platform target identifier.

        Returns:
            True when configuration changed.
        """
        disabled = self.disabled_ids(target_type)
        normalized_id = str(target_id)
        if normalized_id not in disabled:
            return False
        disabled.remove(normalized_id)
        self._config.save_config()
        return True

    def disable_target(self, target_type: TargetType, target_id: str) -> bool:
        """Disable broadcasts for a target.

        Args:
            target_type: Group or friend target type.
            target_id: Platform target identifier.

        Returns:
            True when configuration changed.
        """
        disabled = self.disabled_ids(target_type)
        normalized_id = str(target_id)
        if normalized_id in disabled:
            return False
        disabled.append(normalized_id)
        self._config.save_config()
        return True
