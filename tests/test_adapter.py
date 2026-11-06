"""Exercise native registration and event gates against the real AstrBot runtime."""
import importlib
import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT.parent))
module=importlib.import_module(ROOT.name+'.main')

@pytest.fixture
def plugin(tmp_path,monkeypatch):
    monkeypatch.setattr(module.StarTools,'get_data_dir',lambda name:tmp_path)
    cfg={'owner_umo':'qq_bot:FriendMessage:12','owner_uid':'55'}
    p=module.NeteaseBrowser(MagicMock(),cfg)
    p.music_request_actions=AsyncMock(return_value=frozenset({'listen','share','together','browse'}))
    p.store.save_cookie('test')
    p.service.own_uid='99'
    return p

def event(umo='qq_bot:FriendMessage:12'):
    return SimpleNamespace(unified_msg_origin=umo,message_obj=SimpleNamespace(message_id='abc'))

@pytest.mark.asyncio
async def test_adapter_rejects_other_user(plugin):
    plugin.service.search=AsyncMock()
    result=json.loads(await plugin.ncm_search(event('qq_bot:FriendMessage:88'),'song'))
    assert result['status']=='denied'
    plugin.service.search.assert_not_awaited()

@pytest.mark.asyncio
async def test_adapter_requires_current_search_before_send(plugin):
    plugin.service.share=AsyncMock()
    result=json.loads(await plugin.ncm_share(event(),'101','a song'))
    assert result['status']=='unavailable'
    plugin.service.share.assert_not_awaited()

@pytest.mark.asyncio
async def test_adapter_routes_search_result_into_share(plugin):
    e=event();plugin.service.search=AsyncMock(return_value={'songs':[{'id':'101'}]})
    plugin.service.share=AsyncMock(return_value={'status':'sent'})
    await plugin.ncm_search(e,'current intent')
    assert json.loads(await plugin.ncm_share(e,'101','a reason'))['status']=='sent'
    plugin.service.share.assert_awaited_once()

@pytest.mark.asyncio
async def test_comment_requires_current_read(plugin):
    plugin.service.comment=AsyncMock()
    assert json.loads(await plugin.ncm_comment(event(),'101','hi'))['status']=='unavailable'
    plugin.service.comment.assert_not_awaited()

def test_ready_binding_and_switches(plugin):
    assert plugin.intent_bridge_tool_ready('ncm_search')
    assert plugin.intent_bridge_tool_ready('ncm_share')
    assert not plugin.intent_bridge_tool_ready('ncm_comment')
    plugin.settings['owner_uid']=''
    assert not plugin.intent_bridge_tool_ready('ncm_share')
    assert not plugin.intent_bridge_tool_ready('ncm_join')
    assert plugin.intent_bridge_tool_ready('ncm_search')

def test_schemas_have_real_arguments():
    from astrbot.core.provider.register import llm_tools
    for name,expected in {'ncm_search':{'query'},'ncm_share':{'song_id','message'},
                          'ncm_invite':{'song_id','message'},'ncm_listen':{'song_id'},
                          'ncm_comment':{'song_id','content','reply_id'}}.items():
        tool=next(t for t in llm_tools.func_list if t.name==name)
        assert set(tool.parameters['properties'])==expected

class Config(dict):
    def save_config(self):
        self.saved=True

@pytest.fixture
def web_request():
    from astrbot.api.web import PluginRequest,bind_request_context
    from starlette.requests import Request
    def make(body):
        content=json.dumps(body).encode()
        async def receive():return {'type':'http.request','body':content,'more_body':False}
        req=Request({'type':'http','method':'POST','path':'/test','headers':[(b'content-type',b'application/json')],'query_string':b''},receive)
        return bind_request_context(PluginRequest(req,plugin_name='astrbot_plugin_netease_browser',username='test'))
    return make

@pytest.mark.asyncio
async def test_native_web_request_search(plugin,web_request):
    plugin.service.search=AsyncMock(return_value={'status':'ok','songs':[]})
    with web_request({'query':'song'}):response=await plugin.panel.search()
    assert response.status_code==200
    plugin.service.search.assert_awaited_once_with('song')

@pytest.mark.asyncio
async def test_web_settings_save_and_ready(plugin,web_request):
    plugin.config=Config(plugin.config)
    with web_request({'share_enabled':False,'owner_uid':'777'}):response=await plugin.panel.settings()
    assert response.status_code==200
    assert plugin.config.saved
    assert plugin.settings['owner_uid']=='777'
    assert not plugin.intent_bridge_tool_ready('ncm_share')

@pytest.mark.asyncio
async def test_web_rejects_invalid_uid_without_saving(plugin,web_request):
    plugin.config=Config(plugin.config)
    with web_request({'owner_uid':'abc'}):response=await plugin.panel.settings()
    assert response.status_code==400
    assert plugin.settings['owner_uid']=='55'
    assert not hasattr(plugin.config,'saved')

@pytest.mark.asyncio
async def test_web_qr_has_no_credential_output(plugin):
    plugin.api.call=AsyncMock(side_effect=[{'data':{'unikey':'qrkey'}},{'data':{'qrimg':'data:image/png;base64,AA'}}])
    response=await plugin.panel.qr()
    assert response.status_code==200
    assert 'cookie' not in response.body.decode()
    assert 'qrkey' not in response.body.decode()

@pytest.mark.asyncio
async def test_web_status_never_exposes_cookie(plugin):
    response=await plugin.panel.status()
    assert 'private_test_cookie' not in response.body.decode()
    assert '"cookie"' not in response.body.decode()

@pytest.mark.asyncio
async def test_comment_records_exclude_uncertain_and_keep_content(plugin,web_request):
    plugin.store.reserve('ok','comment',song_id='101',song={'id':'101','name':'A song'},content='First line\nSecond line')
    plugin.store.finish('ok','posted',posted_at=1234,comment_id='345')
    plugin.store.reserve('unknown','comment',song_id='102',content='Uncertain')
    plugin.store.finish('unknown','unknown')
    with web_request({}):response=await plugin.panel.comments()
    data=json.loads(response.body)
    assert data['total']==1
    assert data['items'][0]['song']['name']=='A song'
    assert data['items'][0]['content']=='First line\nSecond line'
    assert data['items'][0]['posted_at']==1234
    assert 'Uncertain' not in response.body.decode()

@pytest.mark.asyncio
async def test_comment_history_paginates_newest_first_with_legacy_records(plugin,web_request):
    plugin.store.data['operations']={str(i):{'kind':'comment','status':'posted','song_id':str(i+1),'at':i} for i in range(55)}
    with web_request({}):response=await plugin.panel.comments()
    data=json.loads(response.body)
    assert data['total']==55 and len(data['items'])==50
    assert data['items'][0]['song_id']=='55'
    assert data['items'][0]['content'] is None

@pytest.mark.asyncio
async def test_pending_offer_context_and_reply_stay_in_bound_session(plugin):
    import time
    plugin.store.data['together_offer']={'id':'offer1','status':'pending','qq_status':'sent','expires_at':time.time()+60,'owner_umo':plugin.settings['owner_umo'],'recipient':'55','song':{'id':'101','name':'Test'}}
    assert plugin.intent_bridge_context(event())['pending_offer']['offer_id']=='offer1'
    assert plugin.intent_bridge_context(event('qq_bot:FriendMessage:88'))=={}
    plugin.flow.reply=AsyncMock(return_value={'status':'sent'})
    out=json.loads(await plugin.ncm_reply_together(event(),'offer1',True))
    assert out['status']=='sent'
    await plugin.ncm_reply_together(event('qq_bot:FriendMessage:88'),'offer1',True)
    assert plugin.flow.reply.await_count==1

@pytest.mark.asyncio
async def test_room_pause_adapter_passes_action_without_argument_collision(plugin):
    plugin.service.control=AsyncMock(return_value={'status':'applied'})
    out=json.loads(await plugin.ncm_room_control(event(),'pause','先聊两句'))
    assert out['status']=='applied'
    assert plugin.service.control.await_args.kwargs['action']=='pause'
    assert plugin.service.control.await_args.kwargs['reason']=='先聊两句'

@pytest.mark.asyncio
async def test_song_direction_is_restored_in_next_turn_and_scoped(plugin):
    plugin.store.reserve('outgoing','share',song_id='101',recipient='55')
    plugin.store.finish('outgoing','sent')
    req=SimpleNamespace(system_prompt='persona')
    await plugin.inject_music_action_facts(event(),req)
    assert 'bot_to_user' in req.system_prompt and '101' in req.system_prompt
    other=SimpleNamespace(system_prompt='other persona')
    await plugin.inject_music_action_facts(event('qq_bot:FriendMessage:88'),other)
    assert other.system_prompt == 'other persona'

class DeliveryEvent(SimpleNamespace):
    def get_extra(self,key,default=None):return self.extras.get(key,default)
    def set_extra(self,key,value):self.extras[key]=value

@pytest.mark.asyncio
async def test_tool_notice_is_delivered_once_and_model_echo_is_empty_before_tts(plugin):
    from astrbot.core.provider.entities import LLMResponse
    e=DeliveryEvent(unified_msg_origin=plugin.settings['owner_umo'],message_obj=SimpleNamespace(message_id='dedup'),extras={})
    plugin.context.send_message=AsyncMock(return_value=True)
    plugin.context.conversation_manager.get_curr_conversation_id=AsyncMock(return_value=None)
    token=plugin.interaction.set({'text':'再邀请一次','event':e})
    try:assert await plugin.notice('一起听《Test》？')=='sent'
    finally:plugin.interaction.reset(token)
    response=LLMResponse(role='assistant',completion_text='一起听《Test》？')
    await plugin.suppress_delivered_notice_echo(e,response)
    assert response.completion_text==''
    plugin.context.send_message.assert_awaited_once()
    assert e.get_extra('_send_message_to_user_current_session_plain_texts')==['一起听《Test》？']
    response=LLMResponse(role='assistant',completion_text='这是另外一个问题的回答')
    await plugin.suppress_delivered_notice_echo(e,response)
    assert response.completion_text=='这是另外一个问题的回答'

@pytest.mark.asyncio
async def test_new_invite_tool_reuses_exact_accepted_offer_only_after_preflight_failure(plugin):
    e=event();e.message_str='再邀请我一次';e._ncm_candidates={'101'}
    plugin.store.data['together_offer']={'id':'accepted','status':'failed','retry_safe':True,'accepted_at':1,'expires_at':time.time()+60,'owner_umo':plugin.settings['owner_umo'],'recipient':'55','song':{'id':'101'},'reply_source_event':'previous'}
    plugin.flow.reply=AsyncMock(return_value={'status':'sent','channel':'netease_native_invite'})
    plugin.flow.propose=AsyncMock()
    out=json.loads(await plugin.run_action(e,'propose',song_id='101',message='再邀请一次'))
    assert out['status']=='sent'
    assert plugin.flow.reply.await_args.args[:2]==('accepted',True)
    plugin.flow.propose.assert_not_awaited()
