# 网易云适配器

[![Plugin checks](https://github.com/YepStar/astrbot_plugin_netease_browser/actions/workflows/ci.yml/badge.svg)](https://github.com/YepStar/astrbot_plugin_netease_browser/actions/workflows/ci.yml)
[![Version](https://img.shields.io/badge/version-0.1.0-green)](CHANGELOG.md)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

面向 AstrBot 的网易云音乐插件。根据聊天意图搜索真实歌曲，在网易云站内分享；先在 QQ 征求确认，再发送一起听邀请。支持房间控制、人格自主选曲、歌词评论浏览，以及本地管理面板。

## 功能

- **歌曲搜索与分享**：根据当前想法、心情或歌名搜索，选择真实歌曲 ID，再发送网易云歌曲私信；不使用日推代替意图选曲。
- **QQ 确认一起听**：先提议，收到用户新回复中的明确接受后才创建房间、发送邀请。拒绝、过期、含糊回答和重复回复不会误发。
- **房间控制**：检测绑定用户入房；支持切歌、暂停和继续。未入房可提醒一次并超时关闭，用户暂停后不会被自主行为强行恢复。
- **自主听歌**：可依据人格和陪伴状态主动搜索选曲，用 ffmpeg 实时读取、解码音频，并按真实消耗时间上报听歌记录。日推由网易云随正常使用自然演变，本插件不读取或改造日推。
- **语境表达**：结合人格、陪伴状态、当前对话和长期记忆判断保持安静、简短表达或解释原因，不使用随机概率或说明频率设置。
- **评论与记录**：读取歌曲歌词及评论，支持公开评论和回复；面板显示本插件成功发表的评论对应歌曲、时间和正文。
- **独立面板**：二维码登录、账号绑定、功能开关、活动时间、听歌与执行记录、评论记录。

## 环境要求

| 依赖 | 要求 |
| --- | --- |
| AstrBot | `>=4.29.1,<5`，宿主需支持 Plugin Page SDK 与 `astrbot.api.web` |
| Python | 3.11 或更新版本 |
| 平台 | OneBot v11 / `aiocqhttp`，当前仅面向绑定的 QQ 私聊 |
| 网易云 API | 自建兼容 [api-enhanced](https://github.com/NeteaseCloudMusicApiEnhanced/api-enhanced) 的服务；已验证版本 4.30.3 |
| ffmpeg | 安装在 AstrBot 所在系统或容器内，`ffmpeg` 命令可执行 |

基础搜索、分享、评论和一起听工具独立运行。**人格自主活动需要兼容的陪伴插件；结合长期记忆进行表达判断还需要兼容的 LivingMemory 只读接口。** 这些不是所有安装环境都具备的标准能力，详见 [集成说明](integrations/README.md)。依赖缺失不会伪造人格判断；成功的音乐操作仍保留，额外表达静默降级。

## 安装

在 AstrBot 插件管理中选择通过仓库链接安装，填写：

```text
https://github.com/YepStar/astrbot_plugin_netease_browser
```

也可以克隆到 AstrBot 的插件目录，然后在管理面板加载：

```sh
git clone https://github.com/YepStar/astrbot_plugin_netease_browser \
  data/plugins/astrbot_plugin_netease_browser
```

不要与旧的一起听插件同时启用，以免 `/一起听`、`music_now`、`music_room` 等名称冲突。升级前备份原插件配置及数据。

## 首次配置

在 AstrBot 插件列表打开 **网易云适配器 → music 页面**。

1. 填写自建网易云 API 地址。默认 `http://ncm-api:3000` 适用于同一 Docker 网络中服务名为 `ncm-api` 的部署；其他环境请填写 AstrBot 能访问的实际地址。
2. 点击“生成登录二维码”，使用**机器人网易云账号**扫码并在手机确认，再点击“检查登录并保存”。“验证当前登录”可检查已有登录状态。
3. 填写你的完整 QQ 私聊 UMO，以及接收歌曲与一起听邀请的**网易云数字 UID**。两者分别绑定，不能将机器人自己的网易云 UID 填成收件人。
4. 根据需要开启分享、一起听、评论及自主活动。公开评论和自主评论默认关闭；自主活动需要明确的人格 ID，模型 Provider ID 留空时跟随绑定会话。
5. 保存设置。站内收件人未绑定时不发送分享或邀请，也不自动从联系人列表猜测用户。

建议机器人账号与接收账号互相关注。一起听目前通过网易云私信发送官方房间分享链接，**不是 App 原生邀请卡片**。

## 一起听流程

```text
陪伴状态与人格产生一起听想法
→ 搜索真实歌曲
→ QQ 私聊提议
→ 用户明确接受
→ 网易云建房并发送站内邀请链接
→ 按绑定 UID 检测入房
→ 一起听、切歌、暂停或继续
```

默认提议有效期 15 分钟；发送站内邀请后 120 秒未入房提醒一次，等待 10 分钟未入房则收束。检测到入房后改为最长 60 分钟的活动会话。这些流程时间可在面板调整。

只有成功读回操作状态后才将切歌或暂停记为完成。内部行动动机保存在记录里，不作为必发台词；是否开口由人格语境判断。一起听前的明确确认与约定的入房提醒仍保留。

## 指令与 AI 工具

手动指令：`/一起听` 接受绑定用户已经发来的邀请；`/听歌状态` 查看当前歌曲及房间状态。

| 工具 | 用途 |
| --- | --- |
| `ncm_search(query)` | 根据当前意图搜索真实歌曲 |
| `ncm_read(song_id)` | 读取详情、歌词和评论 |
| `ncm_share(song_id, message)` | 本轮搜索后站内分享；附言可留空 |
| `ncm_invite(song_id, message)` | 仅在 QQ 提议一起听，等待确认 |
| `ncm_reply_together(offer_id, accept)` | 接受/拒绝当前提议；接受后才发送邀请 |
| `ncm_join()` | 接受绑定用户已有邀请 |
| `ncm_room_control(action, reason, song_id)` | 同房后切歌、暂停或继续；reason 是内部动机 |
| `ncm_comment(song_id, content, reply_id)` | 先读取目标歌曲，再公开评论或回复 |
| `ncm_listen(song_id)` | 机器人自行实时读取、解码一首歌曲 |
| `music_now()` / `music_room()` | 读取真实歌曲、歌词位置、成员与队列 |

插件使用原生 `llm_tool`，无需指令转换器。提供：

- `intent_bridge_tool_ready(name)`：按开关、凭据、账号绑定和运行状态判断工具可用性。
- `intent_bridge_context(event)`：仅向绑定会话提供待确认提议和房间快照，帮助路由理解“好呀”“等会儿”等上下文回复。

意图路由可预执行 `ncm_search`、`ncm_read`、`ncm_join`、`ncm_reply_together`、`ncm_room_control`、`music_now`、`music_room`。分享或切歌依赖搜索结果，不能在分类时猜后续歌曲 ID。工具返回 `expression.mode=silent` 时，不再补报内部理由；已发送的表达不重复播报。

## 数据与行为边界

- 登录 Cookie、接收账号和执行账本只保存在 AstrBot 本地；仓库不携带运行时账号、Cookie、配置或私聊记录。
- 私信、邀请和评论在发送前持久化去重记录；结果不确定不自动重发，QQ 发送失败也不会重复网易云操作。
- 评论记录仅包含本插件成功发表的评论和回复，按北京时间倒序分页。旧记录缺失正文时明确标注，不补造内容。
- 长期记忆检索限定当前原生 QQ 私聊与人格，沿用记忆插件的会话开关和白名单；不跨用户读取，不为测试写入记忆。
- 模型收到的是曲目信息、歌词、评论及播放回执。实时解码不等于语言模型拥有听觉输入，不能据此编造音色、乐器或已经听懂整首歌的体验。
- 网易云 API 是第三方对内部接口的封装，账号权限、歌曲权限和客户端行为仍可能影响可用性。

数据目录：`data/plugin_data/astrbot_plugin_netease_browser/`。配置目录：`data/config/astrbot_plugin_netease_browser_config.json`。升级时保留这些目录和文件。

## 开发与验证

```sh
python -m pip install -r requirements.txt -r requirements-dev.txt
ruff check main.py web.py music
python -m pytest tests/test_music.py tests/test_together.py tests/test_expression.py -q
```

以上为不依赖 AstrBot 进程的核心测试。完整框架适配测试需要在支持本插件 API 的 AstrBot Python 环境运行：

```sh
python -m pytest tests -q
```

首发版本在 AstrBot 4.29.1 / Python 3.12 环境完成 81 项插件测试；相关路由回归及记忆接口测试另在集成环境验证。单元测试不会发送真实私信或公开评论。

模块结构：`main.py` 为 AstrBot 适配；`web.py` 与 `pages/` 为管理面板；`music/` 分离 API、存储、播放器、房间流程、自主活动、陪伴与记忆接口、表达决策；`integrations/` 包含可选接口说明与兼容补丁。

## 来源与许可

音乐适配器主体采用 MIT License，见 [LICENSE](LICENSE)。可选外部集成补丁单独沿用 AGPL-3.0，见 [integrations/LICENSE](integrations/LICENSE)。

一起听私信解析、LRC 定位等思路参考 [shamate-tv/astrbot_plugin_nomi_music](https://github.com/shamate-tv/astrbot_plugin_nomi_music)，原作者 MIT 声明保留在 [THIRD_PARTY_LICENSE.txt](THIRD_PARTY_LICENSE.txt)。网易云 HTTP 接口依赖自建 api-enhanced 服务，本仓库不包含其服务端代码。
