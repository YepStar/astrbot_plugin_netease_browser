"""Regression checks for cross-run variety and public/private audience boundaries."""

import time
from unittest.mock import AsyncMock, MagicMock

import pytest
from test_music import SONG

pytest_plugins = ("test_music",)
from music.autonomy import Autonomy
from music.policy import comment_block_reason, recent_songs
from music.storage import Store

OTHER = {**SONG, "id": "202", "name": "Another Song"}


def enable(cfg):
    cfg.update(
        autonomous_enabled=True,
        autonomous_comment=True,
        comments_enabled=True,
        start_hour=0,
        end_hour=24,
    )


def old_comment(
    store, content="这段歌词写得很具体。", age=3600, sid="101", status="posted"
):
    store.data["operations"]["autonomous:old:comment"] = {
        "kind": "comment",
        "status": status,
        "song_id": sid,
        "at": time.time() - age,
        "content": content,
    }


@pytest.mark.asyncio
async def test_new_operation_key_does_not_bypass_autonomous_song_cooldown(setup):
    cfg, store, api, svc = setup
    enable(cfg)
    store.data["operations"]["old"] = {
        "kind": "listen",
        "status": "completed",
        "song_id": "101",
        "at": time.time() - 7200,
        "origin": "autonomous",
    }
    result = await svc.listen("101", "new-autonomous", origin="autonomous")
    assert result["status"] == "recently_played"
    api.audio.assert_not_awaited()
    result = await svc.listen("101", "user-explicit-repeat", origin="requested")
    assert result["status"] == "started"
    await svc.play_task


@pytest.mark.asyncio
async def test_autonomous_selection_cannot_pick_recent_song_or_same_name_version(setup):
    cfg, store, api, svc = setup
    enable(cfg)
    store.data["observations"].append(
        {
            "at": time.time() - 3600,
            "song": SONG,
            "status": "completed",
            "played_seconds": 2,
        }
    )
    api.search.return_value = [SONG, {**SONG, "id": "303"}, OTHER]
    api.detail.return_value = OTHER

    async def generate(phase, data):
        if phase == "plan":
            assert "101" in data["excluded_song_ids_24h"]
            return {"action": "listen", "query": "music"}
        if phase == "select":
            assert [row["id"] for row in data["songs"]] == ["202"]
            return {"song_id": "202"}
        return {"action": "none", "note": "a note"}

    await Autonomy(cfg, store, svc, MagicMock(), generate).tick()
    assert store.data["observations"][-1]["song"]["id"] == "202"


@pytest.mark.asyncio
async def test_only_recent_candidates_produce_no_replay(setup):
    cfg, store, api, svc = setup
    enable(cfg)
    store.data["observations"].append(
        {"at": time.time(), "song": SONG, "status": "completed"}
    )
    api.search.return_value = [SONG]
    generate = AsyncMock(return_value={"action": "listen", "query": "same song"})
    a = Autonomy(cfg, store, svc, MagicMock(), generate)
    await a.tick()
    assert generate.await_count == 1
    assert "不自主重播" in a.last_status
    api.audio.assert_not_awaited()


@pytest.mark.asyncio
async def test_comment_uses_dedicated_public_generation_not_shared_message(setup):
    cfg, store, api, svc = setup
    enable(cfg)
    api.search.return_value = [SONG]
    generate = AsyncMock(
        side_effect=[
            {"action": "listen", "query": "song"},
            {"song_id": "101"},
            {
                "action": "comment",
                "note": "歌词很具体",
                "message": "要不要一起听？",
                "private_message": "要不要一起听？",
            },
            {"content": "歌词把过去的片段慢慢收拢起来。"},
        ]
    )
    await Autonomy(cfg, store, svc, MagicMock(), generate).tick()
    assert generate.await_args_list[-1].args[0] == "public_comment"
    public_calls = [
        call for call in api.call.await_args_list if call.args[0] == "comment"
    ]
    assert len(public_calls) == 1
    assert public_calls[0].kwargs["content"] == "歌词把过去的片段慢慢收拢起来。"
    svc.notice.assert_not_awaited()


@pytest.mark.asyncio
async def test_wrong_audience_text_is_blocked_before_network_post(setup):
    cfg, store, api, svc = setup
    enable(cfg)
    result = await svc.comment(
        "101",
        "这首适合夜里听，要不要一起听听看？",
        "",
        "autonomous:new:comment",
        origin="autonomous",
    )
    assert result == {"status": "suppressed", "reason": "private_invitation"}
    api.call.assert_not_awaited()
    api.detail.assert_not_awaited()
    assert store.data["operations"]["autonomous:new:comment"]["status"] == "suppressed"


@pytest.mark.asyncio
async def test_concurrent_different_keys_cannot_double_post(setup):
    import asyncio

    cfg, store, api, svc = setup
    enable(cfg)
    results = await asyncio.gather(
        svc.comment("101", "歌词有清楚的画面。", "", "a", origin="autonomous"),
        svc.comment("101", "歌词里的场景写得很具体。", "", "b", origin="autonomous"),
    )
    assert sorted(r["status"] for r in results) == ["posted", "suppressed"]
    assert len([c for c in api.call.await_args_list if c.args[0] == "comment"]) == 1


def test_comment_guard_uses_legacy_receipts_and_uncertain_writes(setup):
    _, store, _, _ = setup
    old_comment(store, status="unknown")
    assert comment_block_reason(store, "101") == "song_comment_cooldown"
    assert comment_block_reason(store, "202") in {
        "daily_comment_limit",
        "comment_cooldown",
    }
    store.save()
    recovered = Store(store.root)
    assert comment_block_reason(recovered, "101") == "song_comment_cooldown"


def test_near_duplicate_comment_including_omitted_quote_is_blocked(setup):
    _, store, _, _ = setup
    old_comment(
        store,
        content="“我们提着过去，走入人群”，每次听到这句，总觉得有种散落又收拢的余味。",
        age=2 * 86400,
        sid="303",
    )
    assert (
        comment_block_reason(store, "202", "每次听到这句，总觉得有种散落又收拢的余味。")
        == "duplicate_comment"
    )


def test_song_cooldown_expires_and_failed_attempt_does_not_count(setup):
    _, store, _, _ = setup
    store.data["operations"]["a"] = {
        "kind": "listen",
        "status": "completed",
        "song_id": "101",
        "at": time.time() - 25 * 3600,
    }
    store.data["operations"]["b"] = {
        "kind": "listen",
        "status": "failed",
        "song_id": "202",
        "at": time.time(),
    }
    assert recent_songs(store)[0] == set()


@pytest.mark.asyncio
async def test_explicit_user_comment_is_not_rewritten_as_a_private_proposal(setup):
    cfg, store, api, svc = setup
    cfg["comments_enabled"] = True
    assert (
        await svc.comment("101", "有没有人也喜欢一起听现场版？", "", "user-command")
    )["status"] == "posted"
