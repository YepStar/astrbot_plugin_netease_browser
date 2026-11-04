"""Durable QQ consent and room lifecycle, separate from the NCM transport."""

import asyncio
import time
import uuid


class TogetherFlow:
    def __init__(self, config, store, service):
        self.cfg, self.store, self.service = config, store, service
        self.lock = asyncio.Lock()

    def pending(self):
        offer = self.store.data.get("together_offer") or {}
        if (
            offer.get("status") == "pending"
            and offer.get("qq_status") == "sent"
            and offer.get("expires_at", 0) > time.time()
            and offer.get("owner_umo") == self.cfg["owner_umo"]
            and offer.get("recipient") == self.cfg["owner_uid"]
        ):
            return offer
        return None

    async def propose(self, song_id, message, key, source_event=None):
        async with self.lock:
            self.service.require("together_enabled")
            await self.service.recipient()
            if not self.cfg["qq_notice"]:
                raise ValueError("需要开启 QQ 告知，才能先征求一起听确认")
            if self.pending():
                return {
                    "status": "awaiting_confirmation",
                    "offer_id": self.pending()["id"],
                }
            if self.store.data.get("room"):
                return {"status": "room_busy"}
            if self.store.receipt(key):
                return self.store.receipt(key)
            song = await self.service.api.detail(song_id)
            offer = {
                "id": uuid.uuid4().hex,
                "song": song,
                "message": message[:200],
                "owner_umo": self.cfg["owner_umo"],
                "recipient": self.cfg["owner_uid"],
                "source_event": source_event,
                "created_at": time.time(),
                "expires_at": time.time() + self.cfg["offer_ttl_minutes"] * 60,
                "status": "pending",
                "qq_status": "pending",
            }
            self.store.data["together_offer"] = offer
            self.store.reserve(
                key, "together_proposal", song_id=song["id"], offer_id=offer["id"]
            )
            text = message.strip()[:200] or f"刚听到《{song['name']}》，想和你一起听会儿。"
            status = await self.service.notice(text)
            offer["qq_status"] = status
            if status != "sent":
                offer["status"] = "delivery_unknown"
            self.store.finish(key, "sent" if status == "sent" else "unknown")
            return {
                "status": "awaiting_confirmation" if status == "sent" else "unknown",
                "offer_id": offer["id"],
                "note": "仅在 QQ 征求确认，尚未创建房间或发送网易云邀请。",
            }

    async def reply(self, offer_id, accept, key, source_event=None):
        async with self.lock:
            self.service.require("together_enabled")
            if self.store.receipt(key):
                return self.store.receipt(key)
            offer = self.pending()
            if not offer or offer["id"] != offer_id:
                return {
                    "status": "no_pending_offer",
                    "note": "提议不存在、已处理或已过期，不发送邀请。",
                }
            if not source_event or source_event == offer.get("source_event"):
                return {
                    "status": "needs_new_user_reply",
                    "note": "必须等待提议发送后的新一条用户回答，不能在提议的同一轮自行确认。",
                }
            if type(accept) is not bool:
                raise ValueError("确认必须为布尔值")
            offer["status"] = "accepted" if accept else "declined"
            offer["replied_at"] = time.time()
            self.store.reserve(
                key, "together_reply", offer_id=offer_id, accepted=accept
            )
            if not accept:
                self.store.finish(key, "declined")
                return {
                    "status": "declined",
                    "note": "已取消提议，没有发送网易云邀请。",
                }
            try:
                # Acceptance authorizes this exact stored song/recipient once, never arbitrary IDs.
                if (
                    self.service.current
                    and self.service.current["origin"] != "together"
                ):
                    await self.service.stop_audio()
                result = await self.service.invite(
                    offer["song"]["id"],
                    offer["message"],
                    "consented_invite:" + offer_id,
                    consent_id=offer_id,
                )
                offer["status"] = "invited" if result["status"] == "sent" else "failed"
                self.store.finish(key, result["status"])
                self.store.save()
                return result
            except BaseException:
                offer["status"] = "unknown"
                self.store.finish(key, "unknown")
                raise

    async def tick(self):
        if not self.cfg["enabled"] or not self.cfg["together_enabled"]:
            return
        offer = self.store.data.get("together_offer") or {}
        if (
            offer.get("status") == "pending"
            and offer.get("expires_at", 0) <= time.time()
        ):
            offer["status"] = "expired"
            self.store.save()
        room = self.store.data.get("room")
        if not room or not room.get("owned") or room.get("joined_at"):
            return
        sent_at = room.get("invited_at")
        if not sent_at or time.time() - sent_at < self.cfg["join_reminder_seconds"]:
            return
        # Reserve before QQ I/O: restarts and uncertain deliveries never send another nudge.
        key = "join_reminder:" + room["id"]
        async with self.lock:
            if self.store.receipt(key):
                return
            self.store.reserve(key, "join_reminder", room_id=room["id"])
            room["reminded_at"] = time.time()
            self.store.save()
            status = await self.service.notice(
                "我还在网易云等你呢，有空就过来一起听会儿。"
            )
            self.store.finish(key, "sent" if status == "sent" else "unknown")

    async def room_decision(self, generate, companion):
        room = self.store.data.get("room")
        if (
            not room
            or not room.get("joined_at")
            or not self.cfg["room_control_enabled"]
            or not self.cfg["autonomous_room_control"]
        ):
            return
        now = time.time()
        if now - room.get("last_decision_at", 0) < self.cfg["room_action_gap_seconds"]:
            return
        snapshot = dict(self.service.room_snapshot)
        if self.cfg["owner_uid"] not in {u["uid"] for u in snapshot.get("users", [])}:
            return
        if snapshot.get("play_status") == "PAUSE":
            return
        room["last_decision_at"] = now
        self.store.save()
        result = await generate(
            "together_control",
            {
                "room": snapshot,
                "scene": companion.scene(self.cfg["owner_umo"].split(":")[-1]),
                "last_reason": room.get("last_control_reason", ""),
                "instruction": "你正在和用户一起听。通常继续当前歌曲，只有具体且合适的原因才切歌或暂停；不为了表现主动而操作，不假称听到音色。原因应来自已知歌词、曲目、人设或当前活动，先有原因再决定动作，失败不编造完成。用户刚暂停时不要擅自恢复。",
                "schema": {
                    "action": "none/pause/resume/switch",
                    "query": "切歌时的具体搜索词",
                    "reason": "内部行动动机，不等于需要向用户解释",
                },
            },
        )
        if (
            self.store.data.get("room") is not room
            or not self.cfg["autonomous_room_control"]
        ):
            return
        action = result.get("action")
        if action not in ("pause", "resume", "switch"):
            return
        sid = ""
        if action == "switch":
            songs = (await self.service.search(result.get("query", "")))["songs"]
            if not songs:
                return
            selected = await generate(
                "select",
                {
                    "songs": songs,
                    "schema": {"song_id": "候选真实ID"},
                    "instruction": "从候选中选适合此刻一起听的一首。",
                },
            )
            sid = str(selected.get("song_id", ""))
            if sid not in {song["id"] for song in songs}:
                return
        await self.service.control(
            action,
            str(result.get("reason", ""))[:200],
            "room_decision:" + room["id"] + ":" + str(int(now)),
            song_id=sid,
            actor="bot",
        )
