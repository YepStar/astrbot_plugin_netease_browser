import json
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, MagicMock
import pytest
from test_music import setup  # noqa: F401
from music.expression import ExpressionPolicy
from music.memory import MemoryPort
from music.storage import Store

@pytest.fixture
def behavior():
    return {'sources':{'companion':'ok','memory':'ok'},
        'companion':{'mood':'relaxed','relationship':'close'},
        'long_term_memory':[{'id':'m1','content':'Often enjoys quiet companionship'}],
        'current_user_turn':{'text':'换这首吧'},'delivery_scope':{'owner_umo':'qq_bot:FriendMessage:12','owner_uid':'55','persona_id':'persona'}}

@pytest.mark.asyncio
@pytest.mark.parametrize('mode',['silent','brief','explain'])
async def test_persona_decision_controls_expression(tmp_path,behavior,mode):
    store=Store(tmp_path);store.reserve('action','room_control');store.finish('action','applied')
    generated={'mode':mode,'text':'' if mode=='silent' else '一起安静待会儿吧','rationale':'based on mood and recalled preference'}
    load=AsyncMock(return_value=behavior);generate=AsyncMock(return_value=generated);deliver=AsyncMock(return_value='sent')
    policy=ExpressionPolicy(load,generate,deliver,store)
    result=await policy.decide('room_control_applied',{'action':'pause','status':'applied'},'action')
    assert result['mode']==mode
    prompt=generate.await_args.args[1]
    assert prompt['behavior_context']['long_term_memory'][0]['id']=='m1'
    assert prompt['behavior_context']['companion']['mood']=='relaxed'
    if mode=='silent':deliver.assert_not_awaited()
    else:deliver.assert_awaited_once_with(generated['text'],behavior['delivery_scope'])
    assert Store(tmp_path).data['operations']['action']['expression']['mode']==mode

@pytest.mark.asyncio
async def test_same_event_uses_changed_memory_instead_of_probability(tmp_path,behavior):
    generate=AsyncMock(side_effect=lambda phase,data:{'mode':'silent' if 'quiet' in data['behavior_context']['long_term_memory'][0]['content'] else 'brief','text':'想和你说一句','rationale':'context'})
    deliver=AsyncMock(return_value='sent');load=AsyncMock(return_value=behavior)
    policy=ExpressionPolicy(load,generate,deliver,Store(tmp_path))
    assert (await policy.decide('song_shared',{'song':{'id':'1'}}))['mode']=='silent'
    behavior['long_term_memory'][0]['content']='Likes a natural short message when something is shared'
    assert (await policy.decide('song_shared',{'song':{'id':'1'}}))['mode']=='brief'
    assert generate.await_count==2 and deliver.await_count==1

@pytest.mark.asyncio
@pytest.mark.parametrize('source',['companion','memory'])
async def test_missing_context_does_not_fabricate_personality(tmp_path,behavior,source):
    behavior['sources'][source]='unavailable'
    generate=AsyncMock();deliver=AsyncMock()
    policy=ExpressionPolicy(AsyncMock(return_value=behavior),generate,deliver,Store(tmp_path))
    assert (await policy.decide('song_shared',{}))['mode']=='silent'
    generate.assert_not_awaited();deliver.assert_not_awaited()

@pytest.mark.asyncio
async def test_decision_failure_does_not_change_action_success(tmp_path,behavior):
    store=Store(tmp_path);store.reserve('share','share');store.finish('share','sent')
    policy=ExpressionPolicy(AsyncMock(return_value=behavior),AsyncMock(side_effect=TimeoutError()),AsyncMock(),store)
    assert (await policy.decide('song_shared',{},'share'))['mode']=='silent'
    assert store.data['operations']['share']['status']=='sent'

@pytest.mark.asyncio
async def test_active_memory_facade_receives_exact_scope():
    method=AsyncMock(return_value={'status':'ok','memories':[]})
    context=NS(get_all_stars=lambda:[NS(name='astrbot_plugin_livingmemory',activated=True,star_cls=NS(recall_behavior_context=method))])
    assert (await MemoryPort(context).recall('qq_bot:FriendMessage:12','persona','music'))['status']=='ok'
    method.assert_awaited_once_with(umo='qq_bot:FriendMessage:12',persona_id='persona',query='music')

@pytest.mark.asyncio
async def test_disabled_memory_is_not_called():
    method=AsyncMock()
    context=NS(get_all_stars=lambda:[NS(name='astrbot_plugin_livingmemory',activated=False,star_cls=NS(recall_behavior_context=method))])
    assert (await MemoryPort(context).recall('qq_bot:FriendMessage:12','persona','music'))['status']=='unavailable'
    method.assert_not_awaited()

@pytest.mark.asyncio
async def test_shared_song_can_be_silent_and_keeps_delivery_receipt(setup):
    _,store,api,svc=setup
    svc.expression=AsyncMock(return_value={'mode':'silent','delivery':'silent'})
    result=await svc.share('101','','share')
    assert result['status']=='sent' and result['expression']['mode']=='silent'
    assert store.data['operations']['share']['status']=='sent'
    svc.notice.assert_not_awaited()
    svc.expression.assert_awaited_once()
    assert api.call.await_args.kwargs['msg']==''

@pytest.mark.asyncio
@pytest.mark.parametrize('reported_direction',['user_to_bot',''])
async def test_inverted_or_unconfirmed_expression_never_delivered(tmp_path,behavior,reported_direction):
    facts={'actor':'bot','direction':'bot_to_user','song':{'id':'101'}}
    generate=AsyncMock(return_value={'mode':'brief','text':'谢谢你分享给我','action_actor':'user','action_direction':reported_direction})
    deliver=AsyncMock()
    policy=ExpressionPolicy(AsyncMock(return_value=behavior),generate,deliver,Store(tmp_path))
    result=await policy.decide('song_shared',facts)
    assert result['mode']=='silent'
    deliver.assert_not_awaited()

@pytest.mark.asyncio
async def test_outbound_expression_with_confirmed_direction_can_be_delivered(tmp_path,behavior):
    facts={'actor':'bot','direction':'bot_to_user','song':{'id':'101'}}
    generate=AsyncMock(return_value={'mode':'brief','text':'挑了首歌给你','action_actor':'bot','action_direction':'bot_to_user'})
    deliver=AsyncMock(return_value='sent')
    policy=ExpressionPolicy(AsyncMock(return_value=behavior),generate,deliver,Store(tmp_path))
    assert (await policy.decide('song_shared',facts))['delivery']=='sent'
    deliver.assert_awaited_once()
