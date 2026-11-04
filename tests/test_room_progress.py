"""Regression: playlist playCommand.progress is a command offset, not a live clock."""
import asyncio
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import music.service as service_module
from test_music import SONG, setup  # noqa: F401


@pytest.fixture
def room(setup, monkeypatch):
    _, store, api, svc = setup
    clock = SimpleNamespace(now=100.0)
    monkeypatch.setattr(service_module, 'time', SimpleNamespace(
        monotonic=lambda: clock.now, time=time.time, time_ns=time.time_ns,
    ))
    store.data['room'] = {'id': '123', 'joined_at': 1, 'seq': 1}
    command = {'targetSongId': '101', 'playStatus': 'PLAY', 'progress': 0,
               'clientSeq': 6, 'serverSeq': 6, 'commandType': 'GOTO'}

    async def call(path, **kwargs):
        if path == 'listentogether/status':
            return {'data': {'inRoom': True, 'roomInfo': {
                'roomId': '123', 'roomUsers': [{'userId': '55'}]}}}
        if path == 'listentogether/sync/playlist/get':
            return {'data': {'playCommand': dict(command)}}
        return {'code': 200}

    async def detail(sid):
        return {**SONG, 'id': sid, 'duration_ms': 240000}

    async def play(url, seconds, progress, offset=0):
        await progress(1)
        await asyncio.Event().wait()

    api.call.side_effect = call
    api.detail.side_effect = detail
    svc.player.play.side_effect = play
    return store, api, svc, command, clock


@pytest.mark.asyncio
async def test_repeated_zero_command_never_restarts_running_audio(room):
    store, api, svc, command, clock = room
    try:
        await svc.tick_room()
        await asyncio.sleep(0)
        task = svc.play_task
        for elapsed in (35, 70, 110):
            clock.now = 100 + elapsed
            svc.current['played_seconds'] = elapsed
            await svc.tick_room()
            assert svc.play_task is task and not task.cancelled()
            assert not store.data['observations']
            assert svc.room_snapshot['progress_ms'] == elapsed * 1000
        assert api.audio.await_count == 1
        heartbeats = [c.kwargs for c in api.call.await_args_list
                      if c.args[0] == 'listentogether/heatbeat']
        assert heartbeats[-1]['progress'] == 110000
    finally:
        await svc.stop_audio(reason='room_ended')


@pytest.mark.asyncio
async def test_first_poll_does_not_seek_existing_same_song_to_zero(room):
    store, api, svc, command, clock = room
    svc.start_audio({**SONG, 'duration_ms': 240000}, 'fixture', 'together')
    await asyncio.sleep(0)
    task = svc.play_task
    svc.current['played_seconds'] = 50
    try:
        await svc.tick_room()
        assert svc.play_task is task and not store.data['observations']
    finally:
        await svc.stop_audio(reason='room_ended')


@pytest.mark.asyncio
async def test_new_seek_resyncs_once_and_repeated_command_does_not(room):
    store, api, svc, command, clock = room
    try:
        await svc.tick_room()
        await asyncio.sleep(0)
        svc.current['played_seconds'] = 40
        command.update(progress=120000, clientSeq=7, serverSeq=7)
        clock.now += 40
        await svc.tick_room()
        await asyncio.sleep(0)
        task = svc.play_task
        assert svc.player.play.await_args.kwargs['offset'] == 120
        assert store.data['observations'][-1]['status'] == 'resynced'
        assert store.data['observations'][-1]['played_seconds'] == 40
        clock.now += 40
        svc.current['played_seconds'] = 160
        await svc.tick_room()
        assert svc.play_task is task and len(store.data['observations']) == 1
    finally:
        await svc.stop_audio(reason='room_ended')


@pytest.mark.asyncio
async def test_pause_resume_and_switch_are_not_interruptions(room):
    store, api, svc, command, clock = room
    try:
        await svc.tick_room()
        await asyncio.sleep(0)
        svc.current['played_seconds'] = 40
        command.update(playStatus='PAUSE', progress=40000, clientSeq=7)
        await svc.tick_room()
        assert svc.current is None
        assert store.data['observations'][-1]['status'] == 'paused'
        clock.now += 50
        await svc.tick_room()
        assert svc.room_snapshot['progress_ms'] == 40000
        command.update(playStatus='PLAY', clientSeq=8)
        await svc.tick_room()
        await asyncio.sleep(0)
        assert svc.current['id'] == '101'
        assert svc.player.play.await_args.kwargs['offset'] == 40
        command.update(targetSongId='202', progress=0, clientSeq=9)
        await svc.tick_room()
        await asyncio.sleep(0)
        assert svc.current['id'] == '202'
        assert store.data['observations'][-1]['status'] == 'switched'
    finally:
        await svc.stop_audio(reason='room_ended')


@pytest.mark.asyncio
async def test_natural_completion_is_not_replayed_by_old_command(room):
    store, api, svc, command, clock = room
    svc.player.play.side_effect = None
    svc.player.play.return_value = {'played_seconds': 240, 'complete': True}
    await svc.tick_room()
    await svc.play_task
    clock.now += 245
    await svc.tick_room()
    assert api.audio.await_count == 1
    assert [r['status'] for r in store.data['observations']] == ['completed']
    assert svc.room_snapshot['progress_ms'] == 240000


@pytest.mark.asyncio
async def test_real_decode_failure_is_still_recorded_as_failure(room):
    store, api, svc, command, clock = room
    svc.player.play.side_effect = RuntimeError('audio_decode_failed')
    await svc.tick_room()
    await svc.play_task
    row = store.data['observations'][-1]
    assert row['status'] == 'failed' and row['stop_reason'] == 'audio_error'
    assert row['complete'] is False


@pytest.mark.asyncio
async def test_new_sequence_can_replay_same_song_from_zero(room):
    store, api, svc, command, clock = room
    try:
        await svc.tick_room()
        await asyncio.sleep(0)
        svc.current['played_seconds'] = 50
        command.update(clientSeq=7, serverSeq=7)
        await svc.tick_room()
        await asyncio.sleep(0)
        assert api.audio.await_count == 2
        assert svc.player.play.await_args.kwargs['offset'] == 0
        assert store.data['observations'][-1]['status'] == 'resynced'
    finally:
        await svc.stop_audio(reason='room_ended')


@pytest.mark.asyncio
async def test_concurrent_polls_start_only_one_decoder(room):
    store, api, svc, command, clock = room
    try:
        await asyncio.gather(svc.tick_room(), svc.tick_room())
        await asyncio.sleep(0)
        assert api.audio.await_count == 1
        assert svc.player.play.await_count == 1
        assert not store.data['observations']
    finally:
        await svc.stop_audio(reason='room_ended')


@pytest.mark.asyncio
async def test_leaving_room_records_reason_without_claiming_completion(room):
    store, api, svc, command, clock = room
    await svc.tick_room()
    await asyncio.sleep(0)
    svc.current['played_seconds'] = 25
    api.call.side_effect = None
    api.call.return_value = {'data': {'inRoom': False}}
    await svc.tick_room()
    assert store.data['room'] is None and svc.room_clock is None
    row = store.data['observations'][-1]
    assert row['status'] == 'room_left' and row['complete'] is False
