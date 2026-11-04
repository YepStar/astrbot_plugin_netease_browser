"""Contract tests for delivery, binding, real-time player and autonomous decisions."""
import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from music.api import ApiError, NcmApi
from music.autonomy import Autonomy, parse_json
from music.config import DEFAULTS, validate
from music.player import AudioPlayer
from music.service import MusicService, numeric
from music.storage import Store

SONG={'id':'101','name':'Test','artists':'Artist','album':'Album','duration_ms':2000}

@pytest.fixture
def setup(tmp_path):
    cfg=validate({**DEFAULTS,'owner_uid':'55','owner_umo':'qq_bot:FriendMessage:12'})
    store=Store(tmp_path);store.save_cookie('private_test_cookie')
    api=MagicMock()
    api.detail=AsyncMock(return_value=SONG)
    api.audio=AsyncMock(return_value='https://m701.music.126.net/test.mp3')
    api.call=AsyncMock(return_value={'code':200})
    player=MagicMock();player.play=AsyncMock(return_value={'played_seconds':2,'complete':True});player.stop=AsyncMock()
    companion=MagicMock()
    service=MusicService(cfg,store,api,player,companion,AsyncMock(return_value='sent'))
    service.own_uid='99'
    return cfg,store,api,service

@pytest.mark.parametrize('update',[{'owner_uid':'evil'},{'owner_umo':'qq:GroupMessage:1'},{'enabled':'yes'}, {'poll_seconds':1},{'end_hour':2,'start_hour':5},{'api_base':'http://user:pass@host'},{'unknown':1},{'autonomous_enabled':True}])
def test_config_rejects(update):
    with pytest.raises(ValueError):validate(update)

@pytest.mark.parametrize('value',['0','-1','1 OR 1','https://x',''])
def test_numeric_rejects(value):
    with pytest.raises(ValueError):numeric(value)

def test_ledger_survives_restart(tmp_path):
    s=Store(tmp_path);s.reserve('msg1','share');s2=Store(tmp_path)
    assert s2.receipt('msg1')['previous_status']=='unknown'
    assert not s2.reserve('msg1','share')
    assert s2.path.stat().st_mode & 0o777==0o600

@pytest.mark.asyncio
async def test_share_and_duplicate(setup):
    cfg,s,api,svc=setup
    out=await svc.share('101','a song','message')
    assert out['status']=='sent'
    assert api.call.await_args.args==('send/song',)
    assert api.call.await_args.kwargs['user_ids']=='55'
    assert (await svc.share('101','again','message'))['status']=='duplicate'
    assert api.call.await_count==1
    svc.notice.assert_not_awaited()

@pytest.mark.asyncio
async def test_share_uncertain_never_retries(setup):
    cfg,s,api,svc=setup;api.call.side_effect=ApiError()
    with pytest.raises(ApiError):await svc.share('101','x','key')
    assert s.receipt('key')['previous_status']=='unknown'
    await svc.share('101','x','key')
    assert api.call.await_count==1
    svc.notice.assert_not_awaited()

@pytest.mark.asyncio
async def test_qq_failure_does_not_resend_ncm(setup):
    _,s,api,svc=setup;svc.notice.return_value='unknown'
    assert (await svc.share('101','x','key'))['status']=='sent'
    await svc.share('101','x','key');assert api.call.await_count==1

@pytest.mark.asyncio
@pytest.mark.parametrize('change',[{'share_enabled':False},{'enabled':False},{'owner_uid':''},{'owner_uid':'99'}])
async def test_no_write_without_gate_or_recipient(setup,change):
    cfg,s,api,svc=setup;cfg.update(change)
    with pytest.raises(ValueError):await svc.share('101','x','key')
    api.call.assert_not_awaited()

@pytest.mark.asyncio
async def test_invite_sequence_and_native_invitation(setup):
    cfg,s,api,svc=setup
    s.data['together_offer']={'id':'consent','status':'accepted','song':SONG,'recipient':'55','owner_umo':'qq_bot:FriendMessage:12'}
    async def call(path,**kw):
        if path=='listentogether/room/create':return {'code':200,'data':{'roomInfo':{'roomId':'123'}}}
        return {'code':200}
    api.call.side_effect=call
    result=await svc.invite('101','join me','msg1',consent_id='consent')
    assert result['status']=='sent'
    calls=api.call.await_args_list
    paths=[c.args[0] for c in calls]
    assert paths.index('listentogether/room/create')<paths.index('api')
    native=next(c for c in calls if c.args[0]=='api')
    assert native.kwargs['uri']=='/api/listen/together/invite/message/send'
    assert json.loads(native.kwargs['data'])=={'roomId':'123','acceptorId':'55'}
    assert 'send/text' not in paths
    assert result['channel']=='netease_native_invite'
    await svc.play_task
    assert svc.notice.await_count==0

@pytest.mark.asyncio
async def test_invite_timeout_preserves_unknown_and_closes_owned(setup):
    cfg,s,api,svc=setup
    s.data['together_offer']={'id':'consent','status':'accepted','song':SONG,'recipient':'55','owner_umo':'qq_bot:FriendMessage:12'}
    async def call(path,**kw):
        if path=='listentogether/room/create':return {'data':{'roomInfo':{'roomId':'123'}}}
        if path=='api':raise ApiError()
        return {'code':200}
    api.call.side_effect=call
    with pytest.raises(ApiError):await svc.invite('101','x','key',consent_id='consent')
    assert s.receipt('key')['previous_status']=='unknown'
    assert s.data['room'] is None
    svc.notice.assert_not_awaited()

@pytest.mark.asyncio
async def test_no_invite_when_already_in_room(setup):
    _,s,api,svc=setup;api.call.return_value={'data':{'inRoom':True}}
    s.data['together_offer']={'id':'consent','status':'accepted','song':SONG,'recipient':'55','owner_umo':'qq_bot:FriendMessage:12'}
    assert (await svc.invite('101','x','key',consent_id='consent'))['status']=='room_busy'
    assert 'key' not in s.data['operations']

@pytest.mark.asyncio
async def test_only_owner_invitation_accepted_once(setup):
    _,s,api,svc=setup
    def invite(uid,rid):
        msg={'generalMsg':{'nativeUrl':f'orpheus://listenTogether?roomId={rid}&inviterId={uid}'}}
        return {'user':{'fromUserId':uid,'toUserId':'99','lastMsg':json.dumps({'msg':json.dumps(msg)})}}
    async def call(path,**kw):
        if path=='msg/private':return {'msgs':[invite('77','100'),invite('55','200')]}
        return {'code':200,'data':{'success':True}}
    api.call.side_effect=call
    out=await svc.accept('message1');assert out=={'status':'accepted','room_id':'200'}
    s.data['room']=None
    assert (await svc.accept('message2'))['status']=='already_processed'
    assert sum(c.args[0]=='listentogether/accept' for c in api.call.await_args_list)==1

@pytest.mark.asyncio
async def test_real_playback_receipt_after_player_finishes(setup):
    _,s,api,svc=setup
    assert (await svc.listen('101','play'))['status']=='started'
    assert s.data['operations']['play']['status']=='pending'
    await svc.play_task
    assert s.data['operations']['play']['status']=='completed'
    assert s.data['observations'][0]['played_seconds']==2
    # Short playback does not fabricate a full listening record.
    assert not any(c.args[0]=='scrobble' for c in api.call.await_args_list)

@pytest.mark.asyncio
async def test_failed_audio_not_claimed_completed(setup):
    _,s,api,svc=setup;svc.player.play.side_effect=RuntimeError('decode')
    await svc.listen('101','play');await svc.play_task
    assert s.data['operations']['play']['status']=='failed'
    assert s.data['observations'][-1]['status']=='failed'
    assert s.data['observations'][-1]['complete'] is False
    assert svc.companion.activity.call_args.args[0] == 'ended'

@pytest.mark.asyncio
async def test_room_expiry_closes(setup):
    _,s,api,svc=setup
    s.data['room']={'id':'123','owned':True,'expires':1}
    api.call.return_value={'data':{'inRoom':True,'roomInfo':{'roomId':'123','roomUsers':[]}}}
    await svc.tick_room();assert s.data['room'] is None
    api.call.assert_any_await('listentogether/end',roomId='123')

@pytest.mark.asyncio
async def test_comment_disabled_no_publish(setup):
    _,s,api,svc=setup
    with pytest.raises(ValueError):await svc.comment('101','x','','key')
    api.call.assert_not_awaited()

@pytest.mark.asyncio
async def test_comment_duplicate(setup):
    cfg,s,api,svc=setup;cfg['comments_enabled']=True
    api.call.return_value={'comment':{'commentId':'345'}}
    assert (await svc.comment('101','hello','','key'))['status']=='posted'
    saved=Store(s.root).data['operations']['key']
    assert saved['song']['name']=='Test' and saved['content']=='hello'
    assert saved['posted_at']>=saved['at']
    await svc.comment('101','hello','','key');assert api.call.await_count==1

@pytest.mark.asyncio
async def test_autonomy_skips_without_companion(setup):
    cfg,s,api,svc=setup;cfg.update(autonomous_enabled=True,start_hour=0,end_hour=24)
    companion=MagicMock();companion.scene.return_value=None
    generate=AsyncMock();a=Autonomy(cfg,s,svc,companion,generate)
    await a.tick();generate.assert_not_awaited()

@pytest.mark.asyncio
async def test_autonomy_searches_no_daily_endpoints(setup):
    cfg,s,api,svc=setup;cfg.update(autonomous_enabled=True,start_hour=0,end_hour=24)
    api.search=AsyncMock(return_value=[SONG])
    api.call.return_value={'code':200}
    generate=AsyncMock(side_effect=[{'action':'listen','query':'persona choice'}, {'song_id':'101'}, {'action':'none','note':'a note'}])
    a=Autonomy(cfg,s,svc,MagicMock(),generate)
    await a.tick()
    api.search.assert_awaited_once_with('persona choice')
    assert s.data['observations'][0]['note']=='a note'
    assert not any('recommend' in c.args[0] or 'personal_fm' in c.args[0] for c in api.call.await_args_list)
    await a.tick();assert generate.await_count==3

@pytest.mark.asyncio
async def test_player_rejects_arbitrary_host():
    with pytest.raises(ValueError):await AudioPlayer().play('https://evil.test/audio',2,AsyncMock())

@pytest.mark.parametrize('raw',['[]','bad','```json\n[]\n```'])
def test_invalid_model_output(raw):
    with pytest.raises((ValueError,json.JSONDecodeError)):parse_json(raw)

@pytest.mark.asyncio
async def test_share_passes_authoritative_direction_to_expression(setup):
    _, store, api, service = setup
    service.expression = AsyncMock(return_value={'mode':'silent','delivery':'silent'})
    result = await service.share('101','给你听','direction-case')
    facts = service.expression.await_args.args[1]
    assert facts['actor'] == 'bot' and facts['direction'] == 'bot_to_user'
    assert facts['sender_uid'] == '99' and facts['recipient_uid'] == '55'
    assert facts['occurred_at_local'].endswith('+08:00')
    assert result['action_facts'] == {k:v for k,v in facts.items() if k not in ('status','private_message')}
    assert store.data['operations']['direction-case']['song']['name'] == SONG['name']


def test_context_recovers_legacy_shares_without_inventing_inbound_events():
    from music.facts import recent_share_context
    rows = {
        'legacy':{'kind':'share','status':'sent','at':1793416068,'song_id':'533221259','recipient':'55'},
        'uncertain':{'kind':'share','status':'unknown','at':1793495253,'recipient':'55'},
        'other':{'kind':'share','status':'sent','at':1793495253,'recipient':'999'},
    }
    text = recent_share_context({'operations':rows},'55',now=1793495253)
    assert '533221259' in text and 'bot_to_user' in text and '机器人自己选歌' in text
    assert '999' not in text
    assert recent_share_context({'operations':rows},'different') == ''
