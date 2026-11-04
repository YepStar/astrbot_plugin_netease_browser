import json
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock
import pytest
from test_adapter import plugin, event
from music.requests import request_actions, validate_actions
from music.expression import ExpressionPolicy
from music.storage import Store

@pytest.mark.asyncio
async def test_exact_incident_cannot_send_share_and_can_play(plugin):
    del plugin.music_request_actions
    e=event();e.message_str='这种天很适合听民谣呢，推荐你先听《安和桥》'
    e.get_extra=lambda key,default=None: {'music_actions':['listen']} if key=='_intent_bridge_route' else default
    plugin.generate=AsyncMock()
    plugin.service.search=AsyncMock(return_value={'songs':[{'id':'27646205','name':'安和桥','artists':'宋冬野'}]})
    plugin.service.share=AsyncMock()
    plugin.service.listen=AsyncMock(return_value={'status':'started'})
    search=json.loads(await plugin.ncm_search(e,'安和桥'))
    assert search['next_tools']==['ncm_listen']
    wrong=json.loads(await plugin.ncm_share(e,'27646205','我也听着呢'))
    assert wrong['status']=='intent_mismatch' and wrong['next_tools']==['ncm_listen']
    plugin.service.share.assert_not_awaited()
    assert json.loads(await plugin.ncm_listen(e,'27646205'))['status']=='started'
    plugin.service.listen.assert_awaited_once()
    plugin.generate.assert_not_awaited()  # Reuse unified semantic classification.

@pytest.mark.asyncio
async def test_request_to_share_does_not_authorize_self_listen(plugin):
    plugin.music_request_actions=AsyncMock(return_value=frozenset({'share'}))
    e=event();e._ncm_candidates={'101'}
    plugin.service.listen=AsyncMock();plugin.service.share=AsyncMock(return_value={'status':'sent'})
    assert json.loads(await plugin.ncm_listen(e,'101'))['status']=='intent_mismatch'
    plugin.service.listen.assert_not_awaited()
    assert json.loads(await plugin.ncm_share(e,'101'))['status']=='sent'

@pytest.mark.asyncio
@pytest.mark.parametrize('actions',[[],['preference'],['browse']])
async def test_no_share_or_play_for_negation_knowledge_or_longterm_advice(plugin,actions):
    plugin.music_request_actions=AsyncMock(return_value=frozenset(actions))
    e=event();e._ncm_candidates={'101'}
    plugin.service.share=AsyncMock();plugin.service.listen=AsyncMock()
    assert json.loads(await plugin.ncm_share(e,'101'))['status']=='intent_mismatch'
    assert json.loads(await plugin.ncm_listen(e,'101'))['status']=='intent_mismatch'
    plugin.service.share.assert_not_awaited();plugin.service.listen.assert_not_awaited()

@pytest.mark.asyncio
async def test_semantic_fallback_uses_current_text_and_caches_per_event():
    e=NS(message_str='给你推荐《安和桥》，你先去听听')
    generate=AsyncMock(return_value={'music_actions':['listen']});recent=AsyncMock(return_value=[])
    assert await request_actions(e,generate,recent)=={'listen'}
    assert await request_actions(e,generate,recent)=={'listen'}
    generate.assert_awaited_once()
    assert generate.await_args.args[1]['current']==e.message_str
    e.message_str='还是只分享给我吧'
    generate.return_value={'music_actions':['share']}
    assert await request_actions(e,generate,recent)=={'share'}
    assert generate.await_count==2

@pytest.mark.asyncio
async def test_unavailable_semantic_classifier_does_not_authorize_side_effects():
    e=NS(message_str='推荐你先听安和桥')
    assert await request_actions(e,AsyncMock(side_effect=TimeoutError()),AsyncMock(return_value=[]))==set()

@pytest.mark.asyncio
async def test_combined_explicit_actions_preserved():
    e=NS(message_str='你先听，再分享给我',get_extra=lambda key,default=None:{'music_actions':['listen','share']})
    generate=AsyncMock()
    assert await request_actions(e,generate,AsyncMock())=={'listen','share'}
    generate.assert_not_awaited()

@pytest.mark.parametrize('value',['listen',['unknown'],[{}],None])
def test_invalid_semantic_actions_rejected(value):
    with pytest.raises(ValueError):validate_actions(value)

@pytest.mark.asyncio
async def test_expression_cannot_claim_current_listening_without_playback(tmp_path):
    context={'sources':{'companion':'ok','memory':'disabled'}}
    generate=AsyncMock(return_value={'mode':'brief','text':'我也正听着呢','claims_listening':True})
    deliver=AsyncMock()
    policy=ExpressionPolicy(AsyncMock(return_value=context),generate,deliver,Store(tmp_path))
    result=await policy.decide('song_shared',{'listening_confirmed':False})
    assert result['mode']=='silent'
    deliver.assert_not_awaited()

@pytest.mark.asyncio
async def test_followup_switch_can_use_saved_real_candidate_without_new_search(plugin):
    e=event();e._ncm_candidates=set()
    plugin.service.pending_switch=lambda:{'song':{'id':'202'}}
    plugin.service.listen=__import__('unittest.mock',fromlist=['AsyncMock']).AsyncMock(return_value={'status':'started','user_reply':'好，那我换成《借我》啦。'})
    out=await plugin.ncm_listen(e,'202')
    import json
    assert json.loads(out)['status']=='started'
    assert e._ncm_listen_outcome['status']=='started'
