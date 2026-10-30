# 可选陪伴、记忆与意图路由集成

核心音乐工具可独立使用；自主活动及人格表达依赖兼容的外部插件接口，不会由此插件自动安装或改写外部插件。

## 陪伴接口

通过已加载的 `astrbot_plugin_private_companion.main.get_private_companion_api()` 发现活动门面；接口缺失时关闭依赖该门面的自主能力。

门面需要提供 `get_scene_context(user_id)`、`get_realtime_context(user_id, purpose)`、`get_reality_touch_host_context(user_id)`，以及 `notify_external_activity_started/updated/ended`。本插件通过这些接口读取结构化场景与关系，并报告真实播放活动；不读取陪伴插件内部数据文件。

## LivingMemory 接口

已启用的 LivingMemory 实例可提供异步方法：

```python
async def recall_behavior_context(self, *, umo: str, persona_id: str, query: str) -> dict:
    # Return {"status": "ok", "memories": [{"id": "...", "content": "..."}]}.
    # Enforce session/plugin enablement, allowlists, and the current persona binding.
    ...
```

只读检索应限定当前原生 QQ 私聊与已绑定人格，不能接受跨会话或跨人格查询。接口缺失、不可用或不匹配时，额外人格表达静默降级，不假装检索成功。

## 意图路由接口

原生工具由 AstrBot 注册。路由应在当前会话的原有权限过滤后调用 `intent_bridge_tool_ready(name)`；必要时读取 `intent_bridge_context(event)` 并将待确认提议作为本轮资料供分类器参考。

- 只将用户当前明确接受/拒绝匹配到真实 pending offer；不能猜 offer ID。
- “等会儿”、疑问和含糊回答不发送邀请。
- 搜索结果决定分享/切歌的真实歌曲 ID，不能在分类阶段预造依赖结果。
- 遵守工具的 `expression.mode`，silent 不补报内部理由，已发送表达不重复播报。

## 兼容补丁

`personality_expression.patch` 是一份特定集成环境的参考补丁，主要增加 LivingMemory 只读门面和路由表达约定，**不是适用于所有版本的一键安装器**；它也不包含完整的外部陪伴或路由插件。应用前应备份对应仓库并检查上下文，版本不匹配时按上述接口实现适配。

参考补丁涉及 [LivingMemory](https://github.com/lxfight-s-Astrbot-Plugins/astrbot_plugin_livingmemory)（作者 lxfight）和 YepStar 的意图路由插件，沿用其 AGPL-3.0 声明；此目录的补丁许可见 [LICENSE](LICENSE)。它们与仓库根目录 MIT 许可的音乐适配器分别标注。
