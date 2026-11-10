import asyncio
import json
import time
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock
import pytest
import music.service as service_module
from music.expression import ExpressionPolicy
from music.storage import Store
from test_music import setup, SONG
from test_expression import behavior
from test_room_progress import room
from test_room_queue import queued_room
from test_adapter import plugin

@pytest.mark.asyncio
async def test_remote_expressions_without_operation_key_are_remembered(tmp_path,behavior):
    store=Store(tmp_path)
    generate=AsyncMock(return_value={'mode':'brief','text':'先把音乐停下，听你说。','rationale':'paused'})
    policy=ExpressionPolicy(AsyncMock(return_value=behavior),generate,AsyncMock(return_value='sent'),store)
    await policy.decide('remote_playback_changed',{'action':'pause','song':SONG,'change_origin':'remote_unclassified'})
    row=Store(tmp_path).data['expression_history'][-1]
    assert row['event']=='remote_playback_changed' and row['delivery']=='sent'
    assert row['text']=='先把音乐停下，听你说。'
    assert not store.data['operations']
    instruction=generate.await_args.args[1]['instruction']
    assert '自然续播不是新的邀请' in instruction and '暂停已生效' in instruction

@pytest.mark.asyncio
async def test_behavior_context_includes_unkeyed_remote_expressions(plugin):
    plugin.store.data['expression_history']=[{'at':time.time(),'event':'remote_song_changed','text':'上一首的实际文案','delivery':'sent'}]
    plugin.context.conversation_manager.get_curr_conversation_id=AsyncMock(return_value=None)
    context=await plugin.behavior_context('remote_song_changed',{})
    assert context['recent_expressions'][-1]['text']=='上一首的实际文案'

@pytest.mark.asyncio
async def test_reload_does_not_end_remote_room(plugin):
    plugin.store.data['room']={'id':'123','joined_at':1}
    plugin.service.stop_audio=AsyncMock()
    plugin.service.end_room=AsyncMock()
    plugin.api.close=AsyncMock()
    await plugin.terminate()
    plugin.service.end_room.assert_not_awaited()
    assert plugin.store.data['room']['id']=='123'

@pytest.mark.asyncio
async def test_remote_pause_resume_model_events_are_factual_and_not_repeated(room):
    store,api,svc,command,clock=room
    svc.report=AsyncMock(return_value={'mode':'silent','delivery':'silent'})
    try:
        await svc.tick_room();await asyncio.sleep(0)
        command.update(playStatus='PAUSE',progress=45000,clientSeq=9)
        await svc.tick_room()
        assert svc.report.await_args.args[0]=='remote_playback_changed'
        facts=svc.report.await_args.args[1]
        assert facts['action']=='pause' and facts['listening_confirmed'] is False
        count=svc.report.await_count
        await svc.tick_room();assert svc.report.await_count==count
        command.update(playStatus='PLAY',clientSeq=10)
        await svc.tick_room()
        assert svc.report.await_args.args[1]['action']=='resume'
    finally:await svc.stop_audio(reason='room_ended')

@pytest.mark.asyncio
async def test_remote_natural_next_is_not_claimed_as_user_or_bot_choice(room):
    store,api,svc,command,clock=room
    svc.report=AsyncMock(return_value={'mode':'silent','delivery':'silent'})
    try:
        await svc.tick_room();await asyncio.sleep(0)
        store.data['observations'].append({'song':{'id':'101'},'origin':'together','complete':True,'at':time.time()})
        command.update(targetSongId='202',clientSeq=9)
        await svc.tick_room()
        event,facts=svc.report.await_args.args
        assert event=='remote_song_changed' and facts['change_origin']=='natural_next'
        assert facts['actor']=='remote_unknown' and facts['previous_song']['id']=='101'
        count=svc.report.await_count
        await svc.tick_room();assert svc.report.await_count==count
    finally:await svc.stop_audio(reason='room_ended')

@pytest.mark.asyncio
async def test_unknown_remote_switch_does_not_invent_completion(room):
    store,api,svc,command,clock=room
    svc.report=AsyncMock(return_value={'mode':'silent','delivery':'silent'})
    try:
        await svc.tick_room();await asyncio.sleep(0)
        command.update(targetSongId='202',clientSeq=9)
        await svc.tick_room()
        assert svc.report.await_args.args[1]['change_origin']=='remote_unclassified'
    finally:await svc.stop_audio(reason='room_ended')

@pytest.mark.asyncio
@pytest.mark.parametrize('action',['pause','resume','switch'])
async def test_user_actions_report_exact_state_to_model(queued_room,action):
    cfg,store,api,svc,command=queued_room
    svc.report=AsyncMock(return_value={'mode':'brief','delivery':'sent'})
    try:
        await svc.control(action,'用户的本轮操作','requested:'+action,song_id='202')
        facts=svc.report.await_args.args[1]
        assert facts['change_origin']=='user_requested'
        assert facts['play_status']==('PAUSE' if action=='pause' else 'PLAY')
        if action=='pause':assert facts['listening_confirmed'] is False
    finally:await svc.stop_audio(reason='room_ended')

@pytest.mark.asyncio
async def test_queue_advance_allows_model_specific_text(queued_room):
    cfg,store,api,svc,command=queued_room
    svc.expression=AsyncMock(return_value={'mode':'brief','delivery':'sent'})
    try:
        await svc.advance_room_queue()
        assert svc.expression.await_args.args[0]=='queue_song_advanced'
        assert svc.expression.await_args.args[1]['change_origin']=='natural_next'
        assert store.data['operations']['queue_next:completed-1:202']['status']=='applied'
    finally:await svc.stop_audio(reason='room_ended')

@pytest.fixture
def lifecycle(setup,monkeypatch):
    cfg,store,api,svc=setup
    clock=NS(now=10000.0,present=True)
    monkeypatch.setattr(service_module,'time',NS(time=lambda:clock.now,time_ns=time.time_ns,monotonic=time.monotonic))
    store.data['room']={'id':'123','owned':True,'joined_at':9000,'expires':9999}
    async def call(path,**kw):
        if path=='listentogether/status':return {'data':{'inRoom':True,'roomInfo':{'roomId':'123','roomUsers':[{'userId':'55'}] if clock.present else []}}}
        return {'data':{}}
    api.call.side_effect=call
    return cfg,store,api,svc,clock

@pytest.mark.asyncio
async def test_active_room_survives_legacy_expiry_and_multiple_hours(lifecycle):
    cfg,store,api,svc,clock=lifecycle
    await svc.tick_room()
    assert 'expires' not in store.data['room']
    clock.now+=8*3600
    await svc.tick_room()
    assert store.data['room']['id']=='123'
    assert not any(c.args[0]=='listentogether/end' for c in api.call.await_args_list)

@pytest.mark.asyncio
async def test_absence_timeout_cleans_room_with_audited_reason(lifecycle):
    cfg,store,api,svc,clock=lifecycle
    clock.present=False
    await svc.tick_room()
    assert store.data['room']['owner_absent_since']==10000
    clock.now+=cfg['room_session_minutes']*60-1
    await svc.tick_room();assert store.data['room'] is not None
    clock.now+=2
    await svc.tick_room();assert store.data['room'] is None
    ends=[x for x in store.data['operations'].values() if x['kind']=='room_end']
    assert len(ends)==1 and ends[0]['reason']=='owner_absent_timeout' and ends[0]['status']=='ended'

@pytest.mark.asyncio
async def test_return_cancels_absence_deadline(lifecycle):
    cfg,store,api,svc,clock=lifecycle
    clock.present=False;await svc.tick_room()
    clock.now+=3500;clock.present=True;await svc.tick_room()
    assert 'owner_absent_since' not in store.data['room']
    clock.now+=3600;await svc.tick_room()
    assert store.data['room'] is not None

@pytest.mark.asyncio
async def test_waiting_timeout_still_closes_with_reason(lifecycle):
    cfg,store,api,svc,clock=lifecycle
    clock.present=False
    store.data['room'].pop('joined_at')
    await svc.tick_room()
    assert store.data['room'] is None
    assert next(x for x in store.data['operations'].values() if x['kind']=='room_end')['reason']=='waiting_timeout'

@pytest.mark.asyncio
async def test_failed_close_keeps_room_and_records_unknown(lifecycle):
    cfg,store,api,svc,clock=lifecycle
    api.call.side_effect=RuntimeError('network')
    with pytest.raises(RuntimeError):await svc.end_room()
    assert store.data['room']['id']=='123'
    assert next(x for x in store.data['operations'].values() if x['kind']=='room_end')['status']=='unknown'

@pytest.mark.asyncio
@pytest.mark.parametrize('origin,expected',[('together',1200),('autonomous',600)])
async def test_long_room_song_is_not_truncated_by_standalone_cap(setup,origin,expected):
    cfg,store,api,svc=setup
    cfg['max_listen_seconds']=600
    svc.start_audio({**SONG,'duration_ms':1200000},'fixture',origin)
    await svc.play_task
    assert svc.player.play.await_args.args[1]==expected
