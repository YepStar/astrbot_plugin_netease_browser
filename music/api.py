"""NCM adapter. Credentials never enter URLs, logs or model prompts."""

import time

import aiohttp


class ApiError(Exception):
    def __init__(self, code="network", *, path=None, http_status=None):
        self.path, self.http_status = path, http_status
        self.code = str(code)
        reason = "网络环境临时风控（-460），尚未取得可播放音源" if self.code == "-460" else self.code
        super().__init__("网易云请求未完成：" + reason)


class NcmApi:
    def __init__(self, config, store):
        self.config, self.store = config, store
        self.session = None
        self._audio_cache = {}

    async def call(self, path, *, authenticated=True, **params):
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=25)
            )
        if authenticated:
            cookie = self.store.cookie()
            if not cookie:
                raise ApiError("not_logged_in")
            params["cookie"] = cookie
        params["timestamp"] = time.time_ns() // 1000000
        try:
            async with self.session.post(
                self.config["api_base"] + "/" + path,
                params={"timestamp": time.time_ns()}, data=params
            ) as response:
                body = await response.json(content_type=None)
                if not isinstance(body, dict):
                    raise ApiError("http_" + str(response.status), path=path, http_status=response.status)
                if response.status != 200 or body.get("code", 200) not in (200, 800, 801, 802, 803):
                    # Preserve a safe upstream code; never include arbitrary response text or credentials.
                    code = body.get("code")
                    if not isinstance(code, int):
                        code = "http_" + str(response.status)
                    raise ApiError(code, path=path, http_status=response.status)
                return body
        except (aiohttp.ClientError, TimeoutError, ValueError):
            raise ApiError() from None

    async def close(self):
        if self.session:
            await self.session.close()

    async def search(self, query, limit=5):
        if not isinstance(query, str) or not query.strip() or len(query) > 160:
            raise ValueError("搜索词应为 1—160 字")
        result = await self.call(
            "cloudsearch", keywords=query.strip(), type=1, limit=limit
        )
        return [self.song(x) for x in result.get("result", {}).get("songs", [])]

    @staticmethod
    def song(raw):
        return {
            "id": str(raw["id"]),
            "name": str(raw.get("name", ""))[:160],
            "artists": " / ".join(
                a.get("name", "") for a in raw.get("ar", raw.get("artists", []))
            )[:160],
            "album": raw.get("al", raw.get("album", {})).get("name", ""),
            "duration_ms": int(raw.get("dt", raw.get("duration", 0)) or 0),
        }

    async def detail(self, song_id):
        result = await self.call("song/detail", ids=song_id)
        songs = result.get("songs", [])
        if not songs:
            raise ApiError("song_missing")
        return self.song(songs[0])

    async def audio(self, song_id):
        cached = self._audio_cache.get(str(song_id))
        if cached and cached["expires_at"] > time.monotonic() + 30:
            return cached["url"]
        try:
            result = await self.call("song/url/v1", id=song_id, level="standard")
        except ApiError as exc:
            if exc.code != "-460":
                raise
            # One authenticated, ordinary NCM read endpoint. Never enable third-party unlocking.
            result = await self.call("song/url", id=song_id, br=128000)
        rows = result.get("data") or []
        if not rows or not rows[0].get("url") or rows[0].get("freeTrialInfo"):
            raise ApiError("audio_unavailable_or_trial")
        expiry = rows[0].get("expi", 120)
        if not isinstance(expiry, (int, float)):
            expiry = 120
        self._audio_cache[str(song_id)] = {
            "url": rows[0]["url"],
            "expires_at": time.monotonic() + max(0, min(expiry, 1800)),
        }
        # Only URLs for recent tracks, in memory; cookies and URLs never enter the ledger/model.
        while len(self._audio_cache) > 32:
            self._audio_cache.pop(next(iter(self._audio_cache)))
        return rows[0]["url"]
