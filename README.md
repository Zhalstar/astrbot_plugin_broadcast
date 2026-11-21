<div align="center">

![:name](https://count.getloli.com/@astrbot_plugin_broadcast?name=astrbot_plugin_broadcast&theme=minecraft&padding=6&offset=0&align=top&scale=1&pixelated=1&darkmode=auto)

# astrbot_plugin_broadcast

_✨ 广播助手 ✨_

[![License](https://img.shields.io/badge/License-AGPL--3.0-blue.svg)](https://www.gnu.org/licenses/agpl-3.0.html)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/)
[![AstrBot](https://img.shields.io/badge/AstrBot-4.0%2B-orange.svg)](https://github.com/Soulter/AstrBot)

</div>

## 介绍

面向 aiocqhttp 的广播插件，支持将引用消息转发到群聊、私聊或全部会话。

- 广播前检查最近历史，避免持续向不活跃会话刷屏。
- 发送后从历史记录获取实际广播消息 ID。
- 按源消息保留广播批次，支持部分失败后重试撤回。
- 服务层与 AstrBot 命令层解耦，便于后续接入 WebUI 或 API。

## 命令

| 命令 | 说明 |
| --- | --- |
| `开启广播 [群聊/私聊] [序号]` | 开启当前会话或指定列表目标的广播 |
| `关闭广播 [群聊/私聊] [序号]` | 关闭当前会话或指定列表目标的广播 |
| `广播列表 [群聊/私聊]` | 查看开启与关闭广播的目标 |
| `引用消息 + 广播 [群聊/私聊/全部] [true/false]` | 执行广播，第二个参数默认为 `true`，设为 `false` 可关闭本轮跳过 |
| `引用原消息 + 撤回广播` | 撤回该源消息产生的所有未撤回广播 |
| `取消广播` | 取消当前正在进行的广播任务 |

## 不活跃会话策略

插件会按 Bot 账号和会话记录上一次成功广播的实际消息 ID。如果该 ID 仍在最近 `history_check_count` 条消息中，本轮将跳过该会话。历史接口调用失败时会放行发送，不会因接口兼容问题造成漏发。

## 持久化

广播状态保存在 AstrBot 的 `data/plugin_data/astrbot_plugin_broadcast/broadcast_state.json`，插件重载或 AstrBot 重启后仍可继续跳过和撤回。

## 注意事项

- 历史查询和撤回能力取决于当前 OneBot 实现。
- 转发成功但无法唯一定位新消息 ID 时，会计为发送成功，但该条无法用于后续跳过和撤回。
- 想第一时间得到反馈的可以来作者的插件反馈群（QQ群）：460973561（不点star不给进）
