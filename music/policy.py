"""Cross-decision safeguards for autonomous playback and public comments."""

import re
import time
from difflib import SequenceMatcher
from datetime import datetime
from zoneinfo import ZoneInfo

SONG_COOLDOWN_SECONDS = 24 * 3600
COMMENT_SONG_COOLDOWN_SECONDS = 7 * 24 * 3600
COMMENT_GAP_SECONDS = 6 * 3600
COMMENT_DAILY_LIMIT = 1
_COMMENT_STATUSES = {"posted", "pending", "unknown"}
_PLAY_STATUSES = {"completed", "partial", "pending", "unknown"}
_PRIVATE_INVITATION = re.compile(
    r"一起.{0,5}(?:听|听歌|听听|进房)|要不要|愿不愿意|陪[我你].{0,6}(?:听|歌)|"
    r"邀请你|等你.{0,6}(?:来|进|听)|(?:私聊|QQ|建房)|"
    r"(?:来|进|加入).{0,5}房间|发(?:给|到)你|你(?:有空|方便|来听|想听|要听|也来)|"
    r"listen(?:ing)?\s+together|join\s+me|wanna\s+listen|would\s+you\s+like|let['’]?s\s+listen",
    re.IGNORECASE,
)


def normalized(text):
    return re.sub(r"[^\w\u4e00-\u9fff]", "", str(text).casefold())


def recent_songs(store, now=None):
    """Include durable receipts and actual playback, surviving plugin restarts."""
    now = time.time() if now is None else now
    ids, names = set(), set()
    for row in store.data.get("operations", {}).values():
        if row.get("kind") != "listen" or row.get("status") not in _PLAY_STATUSES:
            continue
        if now - float(row.get("at", 0)) >= SONG_COOLDOWN_SECONDS:
            continue
        if row.get("song_id"):
            ids.add(str(row["song_id"]))
        song = row.get("song") or {}
        if song.get("name"):
            names.add(normalized(song["name"]))
    for row in store.data.get("observations", []):
        if now - float(row.get("at", 0)) >= SONG_COOLDOWN_SECONDS:
            continue
        if row.get("status") not in {"completed", "partial"} and not row.get(
            "played_seconds", 0
        ):
            continue
        song = row.get("song") or {}
        if song.get("id"):
            ids.add(str(song["id"]))
        if song.get("name"):
            names.add(normalized(song["name"]))
    return ids, names


def comment_block_reason(store, song_id, content=None, now=None):
    """Return a reason before any autonomous public write; uncertainty counts as sent."""
    now = time.time() if now is None else now
    if content and _PRIVATE_INVITATION.search(str(content)):
        return "private_invitation"
    zone = ZoneInfo("Asia/Shanghai")
    day = datetime.fromtimestamp(now, zone).date()
    rows = [
        row
        for row in store.data.get("operations", {}).values()
        if row.get("kind") == "comment" and row.get("status") in _COMMENT_STATUSES
    ]
    if any(
        str(r.get("song_id")) == str(song_id)
        and now - float(r.get("at", 0)) < COMMENT_SONG_COOLDOWN_SECONDS
        for r in rows
    ):
        return "song_comment_cooldown"
    if (
        sum(
            datetime.fromtimestamp(float(r.get("at", 0)), zone).date() == day
            for r in rows
        )
        >= COMMENT_DAILY_LIMIT
    ):
        return "daily_comment_limit"
    if any(now - float(r.get("at", 0)) < COMMENT_GAP_SECONDS for r in rows):
        return "comment_cooldown"
    if content:
        current = normalized(content)
        for row in rows:
            if now - float(row.get("at", 0)) >= 30 * 24 * 3600:
                continue
            old = normalized(row.get("content", ""))
            if min(len(old), len(current)) >= 8 and (
                old in current
                or current in old
                or SequenceMatcher(None, old, current).ratio() >= 0.8
            ):
                return "duplicate_comment"
    return ""
