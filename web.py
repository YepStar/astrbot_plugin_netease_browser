"""Authenticated Plugin Page routes, without a standalone web server."""

import asyncio
import time

from astrbot.api.web import json_response, request

from .music.api import ApiError
from .music.config import DEFAULTS, validate


class Panel:
    def __init__(self, plugin):
        self.plugin = plugin
        self.qr_key = None
        self.qr_at = 0
        self.lock = asyncio.Lock()
        for path, handler, methods in [
            ("status", self.status, ["GET"]),
            ("comments", self.comments, ["GET"]),
            ("settings", self.settings, ["POST"]),
            ("login/qr", self.qr, ["POST"]),
            ("login/check", self.check, ["POST"]),
            ("account/check", self.account, ["POST"]),
            ("search", self.search, ["POST"]),
            ("read", self.read, ["POST"]),
            ("stop", self.stop, ["POST"]),
        ]:
            plugin.context.register_web_api(
                "/astrbot_plugin_netease_browser/" + path,
                handler,
                methods,
                "网易云适配器",
            )

    async def status(self):
        p = self.plugin
        return json_response(
            {
                "settings": dict(p.settings),
                "configured": bool(p.store.cookie()),
                "account": p.account_view,
                "playback": p.service.current,
                "room": p.service.room_snapshot,
                "together_offer": p.flow.pending(),
                "autonomy": p.autonomy.last_status,
                "recent": list(p.store.data["operations"].values())[-30:][::-1],
                "observations": p.store.data["observations"][-20:][::-1],
                "tools_ready": {
                    name: p.intent_bridge_tool_ready(name) for name in p.TOOLS
                },
            }
        )

    async def comments(self):
        try:
            offset = int(request.query.get("offset", "0"))
            if offset < 0:
                raise ValueError
        except (ValueError, TypeError):
            return json_response({"error": "分页参数无效"}, status_code=400)
        records = sorted(
            (
                row
                for row in self.plugin.store.data["operations"].values()
                if row.get("kind") == "comment" and row.get("status") == "posted"
            ),
            key=lambda row: row.get("posted_at", row.get("at", 0)),
            reverse=True,
        )
        return json_response(
            {
                "total": len(records),
                "offset": offset,
                "limit": 50,
                "items": [
                    {
                        key: row.get(key)
                        for key in (
                            "song_id",
                            "song",
                            "content",
                            "reply_id",
                            "comment_id",
                            "posted_at",
                            "at",
                        )
                    }
                    for row in records[offset : offset + 50]
                ],
            }
        )

    async def settings(self):
        body = await request.json()
        try:
            if not isinstance(body, dict) or set(body) - set(DEFAULTS):
                raise ValueError("配置无效")
            async with self.lock:
                p = self.plugin
                cfg = validate({**p.settings, **body})
                async with p.flow.lock:
                    changed_identity = any(
                        cfg[k] != p.settings[k]
                        for k in ("owner_uid", "owner_umo", "api_base")
                    )
                    if (
                        changed_identity
                        or not cfg["enabled"]
                        or not cfg["together_enabled"]
                    ):
                        await p.service.end_room()
                    # Cancel pending autonomous decisions before applying new recipient/persona gates.
                    if p.auto_task:
                        p.auto_task.cancel()
                        await asyncio.gather(p.auto_task, return_exceptions=True)
                        p.auto_task = None
                    if (
                        changed_identity
                        or not cfg["enabled"]
                        or not cfg["browse_enabled"]
                        or not cfg["autonomous_enabled"]
                    ):
                        await p.service.stop_audio()
                    if (
                        changed_identity
                        or not cfg["enabled"]
                        or not cfg["together_enabled"]
                    ):
                        offer = p.store.data.get("together_offer") or {}
                        if offer.get("status") == "pending":
                            offer["status"] = "cancelled"
                            p.store.save()
                    old = dict(p.config)
                    p.config.update(cfg)
                    try:
                        p.config.save_config()
                    except Exception:
                        p.config.clear()
                        p.config.update(old)
                        raise ValueError("保存失败，请重试") from None
                    p.settings.clear()
                    p.settings.update(cfg)
                    p.autonomy.last_status = (
                        "等待下一轮陪伴状态检查"
                        if cfg["autonomous_enabled"]
                        else "自主活动已关闭"
                    )
                    if changed_identity:
                        p.service.own_uid = ""
                        p.account_view = {}
            return json_response({"ok": True})
        except (ValueError, ApiError) as exc:
            return json_response({"error": str(exc)}, status_code=400)

    async def qr(self):
        async with self.lock:
            try:
                p = self.plugin
                result = await p.api.call("login/qr/key", authenticated=False)
                self.qr_key = (result.get("data") or {}).get("unikey")
                if not self.qr_key:
                    raise ApiError("qr_missing")
                self.qr_at = time.time()
                result = await p.api.call(
                    "login/qr/create",
                    authenticated=False,
                    key=self.qr_key,
                    qrimg="true",
                )
                image = (result.get("data") or {}).get("qrimg", "")
                if not image.startswith("data:image/"):
                    raise ApiError("qr_image_missing")
                return json_response(
                    {
                        "image": image,
                        "message": "使用机器人网易云账号扫码并在手机确认。",
                    }
                )
            except ApiError as exc:
                return json_response({"error": str(exc)}, status_code=502)

    async def check(self):
        async with self.lock:
            if not self.qr_key or time.time() - self.qr_at > 180:
                return json_response({"code": 800, "message": "请先生成有效二维码。"})
            try:
                p = self.plugin
                result = await p.api.call(
                    "login/qr/check",
                    authenticated=False,
                    key=self.qr_key,
                    noCookie="true",
                )
                code = result.get("code")
                cookie = result.get("cookie", "")
                if code == 803 and cookie:
                    p.store.save_cookie(cookie)
                    p.service.own_uid = ""
                    self.qr_key = None
                    p.account_view = await p.service.account()
                    return json_response(
                        {
                            "code": 803,
                            "message": "登录成功，已安全保存到本地。",
                            "account": p.account_view,
                        }
                    )
                return json_response(
                    {
                        "code": code,
                        "message": {
                            800: "二维码已过期。",
                            801: "等待扫码。",
                            802: "请在手机确认。",
                        }.get(code, "尚未完成登录。"),
                    }
                )
            except ApiError as exc:
                return json_response({"error": str(exc)}, status_code=502)

    async def account(self):
        try:
            self.plugin.account_view = await self.plugin.service.account()
            return json_response({"ok": True, "account": self.plugin.account_view})
        except ApiError as exc:
            self.plugin.account_view = {}
            return json_response({"error": str(exc)}, status_code=502)

    async def search(self):
        body = await request.json()
        try:
            return json_response(
                await self.plugin.service.search((body or {}).get("query", ""))
            )
        except (ValueError, ApiError) as exc:
            return json_response({"error": str(exc)}, status_code=400)

    async def read(self):
        body = await request.json()
        try:
            return json_response(
                await self.plugin.service.read((body or {}).get("song_id", ""))
            )
        except (ValueError, ApiError) as exc:
            return json_response({"error": str(exc)}, status_code=400)

    async def stop(self):
        if self.plugin.auto_task:
            self.plugin.auto_task.cancel()
            await asyncio.gather(self.plugin.auto_task, return_exceptions=True)
        await self.plugin.service.stop_audio()
        try:
            result = await self.plugin.service.end_room()
            return json_response(result)
        except ApiError as exc:
            return json_response({"error": str(exc)}, status_code=502)
