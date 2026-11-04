"""Music advice must be grounded, scoped and optional for memory reads."""
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, MagicMock
import pytest
from test_music import setup
from test_adapter import plugin, event, web_request, Config
from music.preferences import MusicPreferences
from music.memory import MemoryPort
from music.storage import Store
from music.autonomy import Autonomy
from music.config import validate

@pytest.fixture
def prefs(tmp_path):
    cfg=validate({'owner_umo':'qq_bot:FriendMessage:12','persona_id':'persona'})
    context=NS(conversation_manager=NS(get_curr_conversation_id=AsyncMock(return_value='cid'), get_conversation=AsyncMock(return_value=NS(history=[]))),get_all_stars=lambda:[])
    async def extract(phase,data):
        assert phase=='music_preferences'
        return {'items':[{'source_id':r['id'],'quote':'多听民谣'} for r in data['sources'] if '多听民谣' in r['content']]}
    return MusicPreferences(cfg,Store(tmp_path),context,AsyncMock(side_effect=extract))

@pytest.mark.asyncio
async def test_dialogue_captured_filtered_and_persisted(prefs):
    prefs.capture('多听民谣，别管我今天在哪儿','m1')
    prefs.capture('今天在公司上班','m2')
    assert len(prefs.state()['pending'])==1
    out=await prefs.refresh()
    assert [r['quote'] for r in out['items']]==['多听民谣']
    assert '公司' not in str(prefs.store.data)
    assert '今天在哪儿' not in str(prefs.state()['items'])
    recovered=MusicPreferences(prefs.cfg,Store(prefs.store.root),prefs.context,prefs.generate)
    assert recovered.snapshot()['items']==out['items']
    await prefs.refresh();assert prefs.generate.await_count==1

@pytest.mark.asyncio
async def test_recent_user_dialogue_without_music_keyword_is_also_considered(prefs):
    prefs.context.conversation_manager.get_conversation.return_value=NS(history=[{'role':'assistant','content':'我会多听民谣'},{'role':'user','content':'[系统事件：多听民谣]'},{'role':'user','content':'以后多听民谣'}])
    out=await prefs.refresh()
    assert len(out['items'])==1
    sources=prefs.generate.await_args.args[1]['sources']
    assert len(sources)==1 and sources[0]['content']=='以后多听民谣'

@pytest.mark.asyncio
async def test_memory_disabled_never_called_or_reused(prefs):
    prefs.memory.recall=AsyncMock()
    prefs.state()['items']=[{'id':'m1','kind':'memory','quote':'多听民谣','plugin':'astrbot_plugin_livingmemory','at':1}]
    assert (await prefs.refresh())['items']==[]
    prefs.memory.recall.assert_not_awaited()
    assert prefs.snapshot()['status']['memory']=='disabled'

@pytest.mark.asyncio
async def test_selected_memory_is_scoped_and_records_only_music_excerpt(prefs):
    prefs.cfg.update(memory_read_enabled=True,memory_plugin='other_memory')
    prefs.memory.recall=AsyncMock(return_value={'status':'ok','memories':[{'id':'m42','content':'多听民谣。家庭地址是私人信息。'},{'id':'m43','content':'用户喜欢喝茶。'}]})
    out=await prefs.refresh()
    prefs.memory.recall.assert_awaited_once()
    args=prefs.memory.recall.await_args
    assert args.args[:2]==('qq_bot:FriendMessage:12','persona')
    assert args.kwargs=={'plugin_name':'other_memory'}
    assert len(out['items'])==1 and out['items'][0]['source_id']=='m42'
    assert out['items'][0]['plugin']=='other_memory'
    assert '家庭地址' not in str(prefs.store.data)
    assert '喝茶' not in str(prefs.store.data)
    prefs.cfg['memory_plugin']='another_memory'
    assert prefs.snapshot()['items']==[]

@pytest.mark.asyncio
async def test_no_fallback_to_different_memory_provider():
    method=AsyncMock(return_value={'status':'ok','memories':[]})
    ctx=NS(get_all_stars=lambda:[NS(name='astrbot_plugin_livingmemory',activated=True,star_cls=NS(recall_behavior_context=method)),NS(name='unsupported_memory',activated=True,star_cls=object())])
    port=MemoryPort(ctx)
    assert (await port.recall('qq:FriendMessage:1','p','q',plugin_name='missing_memory'))['status']=='unavailable'
    assert (await port.recall('qq:FriendMessage:1','p','q',plugin_name='unsupported_memory'))['status']=='unsupported'
    method.assert_not_awaited()
    assert len(port.providers())==2

@pytest.mark.asyncio
async def test_extractor_cannot_invent_quote_or_source(prefs):
    prefs.capture('多听民谣','m1')
    prefs.generate=AsyncMock(return_value={'items':[{'source_id':'made-up','quote':'多听民谣'},{'source_id':prefs.state()['pending'][0]['id'],'quote':'喜欢摇滚'}]})
    assert (await prefs.refresh())['items']==[]

@pytest.mark.asyncio
async def test_failed_extraction_retains_pending_for_retry(prefs):
    prefs.capture('多听民谣','m1')
    prefs.generate=AsyncMock(side_effect=TimeoutError())
    assert (await prefs.refresh())['status']['extraction']=='unavailable'
    assert prefs.state()['pending'] and not prefs.state()['processed']

@pytest.mark.asyncio
async def test_scope_and_permission_change_during_model_call_discards_result(prefs):
    prefs.capture('多听民谣','m1')
    async def generate(phase,data):
        prefs.cfg['memory_read_enabled']=True
        return {'items':[{'source_id':data['sources'][0]['id'],'quote':'多听民谣'}]}
    prefs.generate=generate
    assert (await prefs.refresh())['items']==[]
    assert not prefs.state()['processed']

@pytest.mark.asyncio
async def test_dialogue_records_are_isolated_by_qq_and_persona(prefs):
    prefs.capture('多听民谣','m1');await prefs.refresh()
    prefs.cfg['owner_umo']='qq_bot:FriendMessage:88'
    assert prefs.snapshot()['items']==[]
    prefs.cfg['owner_umo']='qq_bot:FriendMessage:12';prefs.cfg['persona_id']='other'
    assert prefs.snapshot()['items']==[]
    prefs.cfg['persona_id']='persona'
    assert len(prefs.snapshot()['items'])==1

@pytest.mark.asyncio
async def test_clear_does_not_immediately_reimport_processed_sources(prefs):
    prefs.capture('多听民谣','m1');await prefs.refresh()
    prefs.clear();prefs.capture('多听民谣','m1')
    assert (await prefs.refresh())['items']==[]
    prefs.capture('多听民谣','m2')
    assert (await prefs.refresh())['items']

@pytest.mark.asyncio
async def test_plan_and_selection_both_receive_advice(setup):
    cfg,store,api,svc=setup
    cfg.update(autonomous_enabled=True,persona_id='persona',start_hour=0,end_hour=24)
    companion=MagicMock();companion.scene.return_value={'mood':'calm'}
    svc.search=AsyncMock(return_value={'songs':[{'id':'101'}]})
    svc.listen=AsyncMock(return_value={'status':'player_busy'})
    music={'items':[{'kind':'dialogue','quote':'多听民谣'}],'status':{'memory':'disabled'}}
    preferences=NS(refresh=AsyncMock(return_value=music))
    generate=AsyncMock(side_effect=[{'action':'listen','query':'民谣'},{'song_id':'101'}])
    auto=Autonomy(cfg,store,svc,companion,generate,preferences=preferences)
    await auto.tick()
    assert generate.await_count==2
    for call in generate.await_args_list:assert call.args[1]['music_context']==music
    svc.search.assert_awaited_once_with('民谣')

@pytest.mark.asyncio
async def test_hook_collects_only_bound_users_music(plugin):
    e=event();e.message_str='多听民谣'
    req=NS(system_prompt='')
    await plugin.inject_music_action_facts(e,req)
    assert len(plugin.preferences.state()['pending'])==1
    e=event('qq_bot:FriendMessage:88');e.message_str='多听摇滚'
    await plugin.inject_music_action_facts(e,req)
    assert len(plugin.preferences.state()['pending'])==1

@pytest.mark.asyncio
async def test_panel_memory_fields_save_and_read_opt_in(plugin,web_request):
    plugin.config=Config(plugin.config)
    with web_request({'memory_read_enabled':True,'memory_plugin':'other_memory'}):response=await plugin.panel.settings()
    assert response.status_code==200 and plugin.settings['memory_plugin']=='other_memory'
    plugin.preferences.refresh=AsyncMock(return_value={'items':[]})
    with web_request({}):response=await plugin.panel.refresh_preferences()
    assert response.status_code==200
    plugin.preferences.refresh.assert_awaited_once()

@pytest.mark.parametrize('change',[{'memory_read_enabled':'true'},{'memory_plugin':'../../private'},{'memory_plugin':''}])
def test_memory_config_rejects_invalid_values(change):
    with pytest.raises(ValueError):validate(change)
