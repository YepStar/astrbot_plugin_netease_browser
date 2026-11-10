"""Exercise the durable consent lifecycle, reminders and authoritative room controls."""
import time
from unittest.mock import AsyncMock

import pytest
from test_music import SONG, setup  # noqa: F401
from music.api import ApiError
from music.storage import Store
from music.together import TogetherFlow

@pytest.mark.asyncio
async def test_proposal_only_qq_then_accept_invites(setup):
    cfg,store,api,svc=setup
    flow=TogetherFlow(cfg,store,svc)
    proposal=await flow.propose('101','今天想和你安静待一会儿','proposal')
    assert proposal['status']=='awaiting_confirmation'
    api.call.assert_not_awaited()
    svc.invite=AsyncMock(return_value={'status':'sent','room_id':'123'})
    response=await flow.reply(proposal['offer_id'],True,'reply',source_event='later_message')
    assert response['status']=='sent'
    svc.invite.assert_awaited_once_with('101','今天想和你安静待一会儿','consented_invite:'+proposal['offer_id'],consent_id=proposal['offer_id'])
    await flow.reply(proposal['offer_id'],True,'reply2',source_event='later_message')
    assert svc.invite.await_count==1

@pytest.mark.asyncio
async def test_proposal_survives_restart(setup):
    cfg,store,api,svc=setup
    flow=TogetherFlow(cfg,store,svc);out=await flow.propose('101','a reason','offer')
    recovered=Store(store.root)
    assert TogetherFlow(cfg,recovered,svc).pending()['id']==out['offer_id']

@pytest.mark.asyncio
@pytest.mark.parametrize('case',['decline','expired','other_offer','new_recipient','new_qq','delivery_unknown'])
async def test_no_invite_without_current_accepted_offer(setup,case):
    cfg,store,api,svc=setup
    flow=TogetherFlow(cfg,store,svc);out=await flow.propose('101','a reason','offer')
    oid=out['offer_id'];accept=True
    if case=='decline':accept=False
    if case=='expired':store.data['together_offer']['expires_at']=0
    if case=='other_offer':oid='fake'
    if case=='new_recipient':cfg['owner_uid']='77'
    if case=='new_qq':cfg['owner_umo']='qq_bot:FriendMessage:77'
    if case=='delivery_unknown':store.data['together_offer']['qq_status']='unknown'
    await flow.reply(oid,accept,'reply',source_event='later_message')
    api.call.assert_not_awaited()

@pytest.mark.asyncio
async def test_direct_invite_cannot_bypass_consent(setup):
    _,_,api,svc=setup
    with pytest.raises(ValueError):await svc.invite('101','x','bypass')
    api.call.assert_not_awaited()

@pytest.mark.asyncio
async def test_reminder_once_only_before_join_and_after_delay(setup):
    cfg,store,_,svc=setup;flow=TogetherFlow(cfg,store,svc)
    store.data['room']={'id':'123','owned':True,'invited_at':time.time()}
    await flow.tick();svc.notice.assert_not_awaited()
    store.data['room']['invited_at']=time.time()-cfg['join_reminder_seconds']-1
    await flow.tick();await flow.tick()
    svc.notice.assert_awaited_once()
    assert store.data['operations']['join_reminder:123']['status']=='sent'

@pytest.mark.asyncio
async def test_no_reminder_after_actual_join(setup):
    cfg,store,_,svc=setup;flow=TogetherFlow(cfg,store,svc)
    store.data['room']={'id':'123','owned':True,'invited_at':1,'joined_at':time.time()}
    await flow.tick();svc.notice.assert_not_awaited()

@pytest.mark.asyncio
async def test_unknown_reminder_delivery_not_retried_after_restart(setup):
    cfg,store,_,svc=setup;flow=TogetherFlow(cfg,store,svc)
    store.data['room']={'id':'123','owned':True,'invited_at':1}
    svc.notice.return_value='unknown'
    await flow.tick()
    recovered=Store(store.root)
    await TogetherFlow(cfg,recovered,svc).tick()
    assert svc.notice.await_count==1

@pytest.mark.asyncio
async def test_join_detects_bound_uid_and_extends_pending_expiry(setup):
    cfg,store,api,svc=setup
    store.data['room']={'id':'123','owned':True,'expires':1}
    async def call(path,**params):
        if path=='listentogether/status':return {'data':{'inRoom':True,'roomInfo':{'roomId':'123','roomUsers':[{'userId':'55'}]}}}
        return {'data':{}}
    api.call.side_effect=call
    await svc.tick_room()
    assert store.data['room']['joined_at']>0
    assert 'expires' not in store.data['room']
    await svc.tick_room();assert svc.notice.await_count==0

@pytest.mark.asyncio
@pytest.mark.parametrize('action',['pause','resume','switch'])
async def test_control_verified_and_reason_sent_after_success(setup,action):
    cfg,store,api,svc=setup
    store.data['room']={'id':'123','owned':True,'joined_at':1,'seq':1}
    command={'targetSongId':'101','playStatus':'PLAY','progress':0}
    async def call(path,**params):
        if path=='listentogether/status':return {'data':{'inRoom':True,'roomInfo':{'roomId':'123','roomUsers':[{'userId':'55'}]}}}
        if path=='listentogether/play/command':command.update(targetSongId=params['targetSongId'],playStatus=params['playStatus'])
        if path=='listentogether/sync/playlist/get':return {'data':{'playCommand':dict(command)}}
        return {'code':200}
    api.call.side_effect=call
    out=await svc.control(action,'想停一停和你聊两句','control',song_id='101')
    assert out['status']=='applied' and out['reason']=='想停一停和你聊两句'
    assert store.data['operations']['control']['reason']==out['reason']
    svc.notice.assert_not_awaited()
    await svc.control(action,'same','control',song_id='101')
    assert svc.notice.await_count==0
    if svc.play_task:await svc.play_task

@pytest.mark.asyncio
async def test_no_controls_before_owner_joins(setup):
    _,store,api,svc=setup;store.data['room']={'id':'123','seq':1}
    api.call.return_value={'data':{'inRoom':True,'roomInfo':{'roomId':'123','roomUsers':[{'userId':'77'}]}}}
    assert (await svc.control('pause','想聊两句','pause'))['status']=='owner_not_in_room'
    svc.notice.assert_not_awaited()
    assert all(c.args[0]!='listentogether/play/command' for c in api.call.await_args_list)

@pytest.mark.asyncio
async def test_failed_control_never_claims_success(setup):
    _,store,api,svc=setup;store.data['room']={'id':'123','seq':1}
    async def call(path,**params):
        if path=='listentogether/status':return {'data':{'inRoom':True,'roomInfo':{'roomId':'123','roomUsers':[{'userId':'55'}]}}}
        if path=='listentogether/sync/playlist/get':return {'data':{'playCommand':{'targetSongId':'101','playStatus':'PLAY'}}}
        if path=='listentogether/play/command':raise ApiError()
        return {}
    api.call.side_effect=call
    with pytest.raises(ApiError):await svc.control('pause','想聊两句','pause')
    assert store.data['operations']['pause']['status']=='unknown'
    svc.notice.assert_not_awaited()

@pytest.mark.asyncio
async def test_bot_does_not_override_user_pause(setup):
    _,store,api,svc=setup;store.data['room']={'id':'123','seq':1,'last_control_actor':'bot'}
    async def call(path,**params):
        if path=='listentogether/status':return {'data':{'inRoom':True,'roomInfo':{'roomId':'123','roomUsers':[{'userId':'55'}]}}}
        return {'data':{'playCommand':{'targetSongId':'101','playStatus':'PAUSE'}}}
    api.call.side_effect=call
    assert (await svc.control('resume','change my mind','auto',actor='bot'))['status']=='user_paused'
    assert all(c.args[0]!='listentogether/play/command' for c in api.call.await_args_list)

@pytest.mark.asyncio
async def test_same_turn_cannot_self_confirm(setup):
    cfg,store,api,svc=setup;flow=TogetherFlow(cfg,store,svc)
    proposal=await flow.propose('101','reason','offer',source_event='same-message')
    out=await flow.reply(proposal['offer_id'],True,'reply',source_event='same-message')
    assert out['status']=='needs_new_user_reply'
    api.call.assert_not_awaited()
    assert flow.pending()
