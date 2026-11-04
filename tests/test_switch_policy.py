import asyncio
from unittest.mock import AsyncMock
import pytest
from test_music import setup
from music.api import ApiError

async def active_player(svc,api):
    async def detail(sid):return {'id':str(sid),'name':'旧歌' if str(sid)=='101' else '借我','artists':'Artist','duration_ms':180000}
    api.detail.side_effect=detail
    api.call.return_value={'details':{'startplay':{'code':200},'play':{'code':200}}}
    started=asyncio.Queue();finish=asyncio.Queue()
    async def play(url,seconds,progress,offset=0):
        await progress(45)
        await started.put(True)
        await finish.get()
        return {'played_seconds':seconds,'complete':True}
    svc.player.play=AsyncMock(side_effect=play)
    await svc.listen('101','original')
    await started.get()
    return started,finish

@pytest.mark.asyncio
async def test_first_new_song_waits_retries_dont_count_second_message_switches(setup):
    _,store,api,svc=setup
    started,finish=await active_player(svc,api)
    original=svc.play_task
    first=await svc.listen('202','message-1')
    assert first['status']=='switch_deferred' and '还没放完' in first['user_reply']
    assert svc.play_task is original and not original.done() and svc.current['id']=='101'
    assert (await svc.listen('202','message-1'))['duplicate'] is True
    assert svc.play_task is original and not original.done()
    second=await svc.listen('202','message-2')
    await started.get()
    assert second['status']=='started' and second['switched'] is True
    assert svc.current['id']=='202' and original.cancelled()
    old=store.data['operations']['original']
    assert old['status']=='interrupted' and old['played_seconds']==45 and old['complete'] is False
    assert old['scrobble']['status']=='accepted'
    api.call.assert_any_await('scrobble',id='101',sourceid=0,time=45)
    assert svc.pending_switch() is None
    await svc.stop_audio()

@pytest.mark.asyncio
async def test_same_song_does_not_create_switch_request(setup):
    _,_,api,svc=setup;await active_player(svc,api)
    assert (await svc.listen('101','same'))['status']=='already_playing'
    assert svc.pending_switch() is None
    await svc.stop_audio()

@pytest.mark.asyncio
async def test_unplayable_second_target_does_not_interrupt_old_song(setup):
    _,_,api,svc=setup;await active_player(svc,api)
    await svc.listen('202','first')
    original=svc.play_task
    api.audio.side_effect=ApiError('audio_unavailable_or_trial')
    with pytest.raises(ApiError):await svc.listen('202','second')
    assert svc.play_task is original and not original.done()
    assert svc.current['id']=='101' and svc.pending_switch()
    await svc.stop_audio()

@pytest.mark.asyncio
async def test_current_song_finishing_resets_need_for_confirmation(setup):
    _,store,api,svc=setup;started,finish=await active_player(svc,api)
    await svc.listen('202','first')
    await finish.put(True);await svc.play_task
    assert svc.pending_switch() is None
    result=await svc.listen('202','later')
    await started.get()
    assert result['status']=='started' and result['switched'] is False
    assert store.data['operations']['original']['status']=='completed'
    await svc.stop_audio()

@pytest.mark.asyncio
async def test_autonomy_and_together_do_not_trigger_second_request_policy(setup):
    _,_,api,svc=setup;await active_player(svc,api)
    assert (await svc.listen('202','auto',origin='autonomous'))['status']=='player_busy'
    assert svc.pending_switch() is None
    svc.current['origin']='together'
    assert (await svc.listen('202','room-request'))['status']=='room_busy'
    assert svc.pending_switch() is None
    await svc.stop_audio()

@pytest.mark.asyncio
async def test_changed_persona_does_not_reuse_previous_switch_confirmation(setup):
    cfg,_,api,svc=setup;await active_player(svc,api)
    await svc.listen('202','first')
    cfg['persona_id']='changed-persona'
    assert (await svc.listen('202','other-persona'))['status']=='switch_deferred'
    assert svc.current['id']=='101'
    await svc.stop_audio()
