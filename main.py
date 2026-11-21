import asyncio
from contextlib import suppress

from astrbot.api import logger
from astrbot.api.event import filter
from astrbot.api.star import Context, Star, StarTools
from astrbot.core.config.astrbot_config import AstrBotConfig
from astrbot.core.message.components import Plain, Reply
from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import (
    AiocqhttpMessageEvent,
)

from .config import PluginConfig
from .core.model import BroadcastResult, BroadcastScope
from .core.service import BroadcastService
from .core.state import BroadcastState
from .core.utils import (
    get_reply_id,
    parse_target_and_index,
    parse_target_type,
    resolve_command_target,
)


class BroadcastPlugin(Star):
    """提供广播相关 AstrBot 命令。"""

    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = PluginConfig(config)
        state_path = (
            StarTools.get_data_dir("astrbot_plugin_broadcast") / "broadcast_state.json"
        )
        self.state = BroadcastState(self.config, state_path)
        self.service = BroadcastService(self.config, self.state)
        self._broadcast_task: asyncio.Task[BroadcastResult] | None = None
        self._report_task: asyncio.Task | None = None

    @filter.command("开启广播")
    async def enable_broadcast(
        self,
        event: AiocqhttpMessageEvent,
        first_argument: str = "",
        second_argument: str = "",
    ):
        """开启指定群聊或私聊的广播"""
        target_type, index, error = parse_target_and_index(
            first_argument, second_argument
        )
        if error:
            yield event.plain_result(error)
            return
        try:
            target = await resolve_command_target(
                event, self.service, target_type, index
            )
        except ValueError as exc:
            yield event.plain_result(str(exc))
            return
        if target is None:
            yield event.plain_result("未找到对应会话")
            return

        changed = self.service.enable_target(target)
        status = "已开启" if changed else "已处于开启状态"
        yield event.plain_result(f"【{target.name}】{status}广播")

    @filter.command("关闭广播")
    async def disable_broadcast(
        self,
        event: AiocqhttpMessageEvent,
        first_argument: str = "",
        second_argument: str = "",
    ):
        """关闭指定群聊或私聊的广播"""
        target_type, index, error = parse_target_and_index(
            first_argument, second_argument
        )
        if error:
            yield event.plain_result(error)
            return
        try:
            target = await resolve_command_target(
                event, self.service, target_type, index
            )
        except ValueError as exc:
            yield event.plain_result(str(exc))
            return
        if target is None:
            yield event.plain_result("未找到对应会话")
            return

        changed = self.service.disable_target(target)
        status = "已关闭" if changed else "已处于关闭状态"
        yield event.plain_result(f"【{target.name}】{status}广播")

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("广播列表")
    async def broadcast_list(
        self,
        event: AiocqhttpMessageEvent,
        scope_name: str = "",
    ):
        """查看群聊或好友的广播开关列表"""
        target_type = parse_target_type(scope_name)
        if target_type is None:
            target_type = "group"
        targets = await self.service.list_targets(event.bot, target_type)
        enabled = []
        disabled = []
        for index, target in enumerate(targets, 1):
            line = f"{index}. {target.name} ({target.target_id})"
            if self.config.is_disabled(target.target_type, target.target_id):
                disabled.append(line)
            else:
                enabled.append(line)

        scope_text = "群聊" if target_type == "group" else "好友"
        message = f"【{scope_text}开启广播】\n" + ("\n".join(enabled) or "无")
        message += f"\n\n【{scope_text}关闭广播】\n" + ("\n".join(disabled) or "无")
        yield event.plain_result(message)

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("广播")
    async def broadcast_message(
        self,
        event: AiocqhttpMessageEvent,
        scope_name: str = "",
        skip_recent: bool = True,
    ):
        """（引用消息）广播 <群聊|私聊|全部> <true|false>，广播到指定范围并跳过最近已广播过的"""
        source_message_id = get_reply_id(event)
        if source_message_id is None:
            yield event.plain_result("需要引用要广播的消息")
            return
        if self._broadcast_task and not self._broadcast_task.done():
            yield event.plain_result("已有广播正在进行中")
            return
        try:
            scope = BroadcastScope.parse(scope_name)
        except ValueError:
            yield event.plain_result("广播范围必须是：群聊、私聊或全部")
            return

        source_target_type = "group" if event.get_group_id() else "friend"
        source_target_id = str(event.get_group_id() or event.get_sender_id())
        task = asyncio.create_task(
            self.service.broadcast(
                event.bot,
                source_message_id=source_message_id,
                scope=scope,
                self_id=event.get_self_id(),
                source_target_type=source_target_type,
                source_target_id=source_target_id,
                skip_recent=skip_recent,
            ),
            name="broadcast_task",
        )
        self._broadcast_task = task
        yield event.chain_result(
            [
                Reply(id=source_message_id),
                Plain(f"正在向所有{scope.display_name}广播"),
            ]
        )

        async def report_result() -> None:
            try:
                result = await task
                message = (
                    f"广播完成：成功 {result.success_count}，"
                    f"跳过 {result.skipped_count}，"
                    f"失败 {result.failed_count}，"
                    f"未记录 {len(result.unresolved_targets)}"
                )
                if result.cancelled:
                    message += "（中途取消）"
                await event.send(event.plain_result(message))
            except Exception as exc:
                logger.exception("Broadcast task failed")
                await event.send(
                    event.plain_result(f"广播任务失败：{type(exc).__name__}: {exc}")
                )
            finally:
                if self._broadcast_task is task:
                    self._broadcast_task = None
                self._report_task = None

        self._report_task = asyncio.create_task(
            report_result(),
            name="broadcast_report_task",
        )

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("撤回广播")
    async def recall_broadcast(self, event: AiocqhttpMessageEvent):
        """（引用源消息）撤回广播"""
        source_message_id = get_reply_id(event)
        if source_message_id is None:
            yield event.plain_result("需要引用原广播消息")
            return
        if self._broadcast_task and not self._broadcast_task.done():
            yield event.plain_result("广播仍在进行，请先取消或等待完成")
            return
        try:
            result = await self.service.recall(
                event.bot,
                self_id=event.get_self_id(),
                source_message_id=source_message_id,
            )
        except ValueError:
            yield event.plain_result("未找到该源消息的可撤回广播记录")
            return

        message = f"撤回完成：成功 {result.success_count}，失败 {result.failed_count}"
        if result.cancelled:
            message += "（中途取消）"
        elif result.failed_count:
            message += "，失败记录已保留，可重试"
        yield event.plain_result(message)

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("取消广播")
    async def cancel_broadcast(self, event: AiocqhttpMessageEvent):
        """取消当前正在执行的广播任务。"""
        task = self._broadcast_task
        if not task or task.done():
            yield event.plain_result("当前没有进行中的广播")
            return
        task.cancel()
        yield event.plain_result("已请求取消广播")

    async def terminate(self) -> None:
        """卸载插件时取消后台任务。"""
        if self._broadcast_task and not self._broadcast_task.done():
            self._broadcast_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._broadcast_task
        if self._report_task and not self._report_task.done():
            self._report_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._report_task
