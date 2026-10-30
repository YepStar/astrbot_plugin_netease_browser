"""Headless real-time audio consumption, independent of room signalling."""

import asyncio
import re
import shutil
import time
from urllib.parse import urlparse


class AudioPlayer:
    def __init__(self):
        self.process = None
        self.current = None

    async def play(self, url, seconds, on_progress, offset=0):
        if not shutil.which("ffmpeg"):
            raise RuntimeError("ffmpeg_unavailable")
        host = (urlparse(url).hostname or "").lower()
        if not host.endswith((".music.126.net", ".music.163.com")):
            raise ValueError("Untrusted audio host")
        if self.process:
            raise RuntimeError("player_busy")
        started = time.monotonic()
        self.process = await asyncio.create_subprocess_exec(
            "ffmpeg",
            "-nostdin",
            "-v",
            "error",
            "-rw_timeout",
            "15000000",
            "-re",
            "-ss",
            str(max(0, offset)),
            "-i",
            url,
            "-t",
            str(seconds),
            "-vn",
            "-progress",
            "pipe:1",
            "-stats_period",
            "10",
            "-f",
            "null",
            "-",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        progress = 0
        try:

            async def consume():
                nonlocal progress
                async for line in self.process.stdout:
                    match = re.fullmatch(rb"out_time_us=(\d+)\s*", line)
                    if match:
                        progress = int(match.group(1)) / 1000000
                        await on_progress(progress)
                code = await self.process.wait()
                if code != 0 or progress < min(1, seconds):
                    raise RuntimeError("audio_decode_failed")

            await asyncio.wait_for(consume(), timeout=seconds + 45)
            return {
                "played_seconds": min(progress, time.monotonic() - started),
                "complete": progress >= seconds - 2,
            }
        finally:
            await self.stop()

    async def stop(self):
        process = self.process
        if process and process.returncode is None:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), 5)
            except TimeoutError:
                process.kill()
                await process.wait()
        self.process = None
