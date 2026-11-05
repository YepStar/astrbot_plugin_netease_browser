import asyncio
from unittest.mock import AsyncMock

import pytest
from test_music import SONG, setup  # noqa: F401
from music.api import ApiError
from music.together import TogetherFlow


@pytest.mark.asyncio
async def test_real_search_queue_is_bounded_deduplicated_and_starts_with_selected(setup):
    _, store, api, svc = setup
    api.search.return_value = [{**SONG, 'id': str(n)} for n in range(101, 115)]
    result = await TogetherFlow(svc.cfg, store, svc).propose('101', '要不要一起听这首？', 'offer')
    assert result['status'] == 'awaiting_confirmation'
    assert store.data['together_offer']['queue'] == [str(n) for n in range(101, 109)]
    svc.notice.assert_awaited_once_with('要不要一起听《Test》？')
    api.call.assert_not_awaited()  # Consent has not been given; no room or platform invite.


@pytest.mark.asyncio
async def test_generic_invitation_stays_generic_and_no_daily_recommendation_api(setup):
    _, store, api, svc = setup
    await TogetherFlow(svc.cfg, store, svc).propose('101', '想一起听会儿歌，要来吗？', 'offer')
    svc.notice.assert_awaited_once_with('想一起听会儿歌，要来吗？')
    api.call.assert_not_awaited()


@pytest.mark.asyncio
async def test_search_disabled_does_not_bypass_switch_for_queue(setup):
    cfg, store, api, svc = setup
    cfg['browse_enabled'] = False
    assert await svc.prepare_room_queue(SONG) == ['101']
    api.search.assert_not_awaited()


@pytest.mark.asyncio
async def test_native_invite_publishes_the_consented_multi_track_queue(setup):
    cfg, store, api, svc = setup
    store.data['together_offer'] = {'id': 'consent', 'status': 'accepted', 'song': SONG,
        'recipient': '55', 'owner_umo': cfg['owner_umo'], 'queue': ['101', '202', '303']}
    async def call(path, **kw):
        if path == 'listentogether/status': return {'data': {'inRoom': False}}
        if path == 'listentogether/room/create':
            return {'data': {'roomInfo': {'roomId': '123'}}}
        return {'code': 200}
    api.call.side_effect = call
    await svc.invite('101', '', 'invite', consent_id='consent')
    await svc.play_task
    change = next(c.kwargs for c in api.call.await_args_list if c.args[0] == 'listentogether/sync/list/command')
    assert change['displayList'] == change['randomList'] == '101,202,303'
    assert store.data['room']['queue'] == ['101', '202', '303']


@pytest.fixture
def queued_room(setup):
    cfg, store, api, svc = setup
    store.data['room'] = {'id': '123', 'owned': True, 'joined_at': 1, 'seq': 1,
                          'queue': ['101', '202', '303']}
    command = {'targetSongId': '101', 'playStatus': 'PLAY', 'progress': 0, 'clientSeq': 1}
    async def call(path, **kw):
        if path == 'listentogether/status':
            return {'data': {'inRoom': True, 'roomInfo': {'roomId': '123', 'roomUsers': [{'userId': '55'}]}}}
        if path == 'listentogether/sync/playlist/get': return {'data': {'playCommand': dict(command)}}
        if path == 'listentogether/play/command':
            command.update(targetSongId=kw['targetSongId'], playStatus=kw['playStatus'], progress=kw['progress'], clientSeq=kw['clientSeq'])
        return {'code': 200}
    api.call.side_effect = call
    api.detail.side_effect = lambda sid: {**SONG, 'id': sid}
    svc.room_progress('123', command)
    store.data['queue_advance'] = {'room_id': '123', 'song_id': '101',
                                  'command': svc.room_clock['command'], 'token': 'completed-1'}
    return cfg, store, api, svc, command


@pytest.mark.asyncio
async def test_automatic_next_preserves_queue_and_sends_no_qq_message(queued_room):
    cfg, store, api, svc, command = queued_room
    svc.report = AsyncMock()
    await svc.advance_room_queue()
    await svc.play_task
    assert command['targetSongId'] == '202'
    change = next(c.kwargs for c in api.call.await_args_list if c.args[0] == 'listentogether/sync/list/command')
    assert change['displayList'] == '101,202,303'
    svc.report.assert_not_awaited()
    assert store.data['room']['queue'] == ['101', '202', '303']


@pytest.mark.asyncio
async def test_queue_does_not_override_remote_pause_or_song_change(queued_room):
    cfg, store, api, svc, command = queued_room
    command['playStatus'] = 'PAUSE'
    await svc.advance_room_queue()
    assert not any(c.args[0] == 'listentogether/play/command' for c in api.call.await_args_list)
    command.update(playStatus='PLAY', targetSongId='303')
    await svc.advance_room_queue()
    assert 'queue_advance' not in store.data
    assert not any(c.args[0] == 'listentogether/play/command' for c in api.call.await_args_list)


@pytest.mark.asyncio
async def test_queue_unknown_write_is_not_repeated(queued_room):
    cfg, store, api, svc, command = queued_room
    prior = api.call.side_effect
    async def fail(path, **kw):
        if path == 'listentogether/play/command': raise ApiError('network')
        return await prior(path, **kw)
    api.call.side_effect = fail
    with pytest.raises(ApiError): await svc.advance_room_queue()
    await svc.advance_room_queue()
    assert sum(c.args[0] == 'listentogether/play/command' for c in api.call.await_args_list) == 1


@pytest.mark.asyncio
async def test_segment_cap_is_not_full_completion_or_permission_to_advance(setup):
    cfg, store, api, svc = setup
    cfg['max_listen_seconds'] = 600
    svc.player.play.return_value = {'played_seconds': 600, 'complete': True}
    svc.start_audio({**SONG, 'duration_ms': 1200000}, 'fixture', 'together')
    await svc.play_task
    assert store.data['observations'][-1]['status'] == 'partial'
    assert 'queue_advance' not in store.data
