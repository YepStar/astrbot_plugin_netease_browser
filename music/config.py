"""Validated, hot-reloadable settings independent of AstrBot."""

import re
from urllib.parse import urlparse

DEFAULTS = {
    "enabled": True,
    "api_base": "http://ncm-api:3000",
    "owner_umo": "",
    "owner_uid": "",
    "persona_id": "",
    "provider_id": "",
    "browse_enabled": True,
    "share_enabled": True,
    "together_enabled": True,
    "auto_accept": False,
    "notify_song_change": False,
    "comments_enabled": False,
    "autonomous_enabled": False,
    "autonomous_share": False,
    "autonomous_invite": False,
    "autonomous_comment": False,
    "qq_notice": True,
    "start_hour": 9,
    "end_hour": 23,
    "decision_gap_minutes": 120,
    "daily_listen_limit": 5,
    "daily_outreach_limit": 2,
    "outreach_gap_minutes": 240,
    "invite_ttl_minutes": 10,
    "offer_ttl_minutes": 15,
    "join_reminder_seconds": 120,
    "room_control_enabled": True,
    "autonomous_room_control": True,
    "room_action_gap_seconds": 180,
    "room_session_minutes": 60,
    "poll_seconds": 20,
    "max_listen_seconds": 600,
}
BOOLS = {k for k, v in DEFAULTS.items() if type(v) is bool}
BOUNDS = {
    "start_hour": (0, 23),
    "end_hour": (1, 24),
    "decision_gap_minutes": (30, 1440),
    "daily_listen_limit": (1, 30),
    "daily_outreach_limit": (1, 10),
    "outreach_gap_minutes": (10, 1440),
    "invite_ttl_minutes": (2, 60),
    "offer_ttl_minutes": (2, 60),
    "join_reminder_seconds": (30, 600),
    "room_action_gap_seconds": (60, 1800),
    "room_session_minutes": (10, 240),
    "poll_seconds": (10, 60),
    "max_listen_seconds": (30, 1800),
}


def validate(values):
    """Validate a partial update and return a complete settings object."""
    if not isinstance(values, dict) or set(values) - set(DEFAULTS):
        raise ValueError("未知配置项")
    cfg = {**DEFAULTS, **values}
    for key in BOOLS:
        if type(cfg[key]) is not bool:
            raise ValueError(f"{key} 必须为开关")
    for key, (low, high) in BOUNDS.items():
        if type(cfg[key]) is not int or not low <= cfg[key] <= high:
            raise ValueError(f"{key} 必须在 {low}—{high} 之间")
    for key in ("api_base", "owner_umo", "owner_uid", "persona_id", "provider_id"):
        if not isinstance(cfg[key], str) or len(cfg[key]) > 250:
            raise ValueError("文本配置无效")
        cfg[key] = cfg[key].strip()
    cfg["api_base"] = cfg["api_base"].rstrip("/")
    u = urlparse(cfg["api_base"])
    if (
        u.scheme not in ("http", "https")
        or not u.hostname
        or u.username
        or u.password
        or u.query
        or u.fragment
        or u.path not in ("", "/")
    ):
        raise ValueError("API 地址必须是 http(s) 服务根地址")
    if cfg["owner_umo"] and not re.fullmatch(
        r"[^:]+:FriendMessage:\d+", cfg["owner_umo"]
    ):
        raise ValueError("请绑定完整 QQ 私聊 UMO")
    if cfg["owner_uid"] and not re.fullmatch(r"[1-9]\d{0,19}", cfg["owner_uid"]):
        raise ValueError("网易云 UID 必须为数字")
    if cfg["start_hour"] >= cfg["end_hour"]:
        raise ValueError("活动时间必须在同一天内，开始早于结束")
    if cfg["autonomous_enabled"] and (not cfg["persona_id"] or not cfg["owner_umo"]):
        raise ValueError("自主活动需要指定人设和 QQ 会话")
    return cfg
