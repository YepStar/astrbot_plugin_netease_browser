import json,time
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock
import pytest
from test_music import setup, SONG
from music.api import ApiError,NcmApi
from music.together import TogetherFlow

@pytest.mark.asyncio
async def test_preflight_failure_keeps_consent_for_new_explicit_retry(setup):
    cfg,store,api,svc=setup;flow=TogetherFlow(cfg,store,svc)
    offer=(await flow.propose('101','一起来听？','proposal',source_event='proposal_turn'))['offer_id']
    api.audio.side_effect=ApiError('-460')
    with pytest.raises(ApiError):await flow.reply(offer,True,'accepted',source_event='accept_turn')
    assert flow.retryable()['id']==offer
    assert flow.replyable()['queue']==['101']
    assert not store.receipt('consented_invite:'+offer)
    assert all(c.args[0]!='listentogether/room/create' for c in api.call.await_args_list)
    assert (await flow.reply(offer,True,'same_turn',source_event='accept_turn'))['status']=='needs_new_user_reply'
    api.audio.side_effect=None
    async def call(path,**kwargs):
        return {'code':200,'data':{'roomInfo':{'roomId':'123'}}} if path=='listentogether/room/create' else {'code':200}
    api.call.side_effect=call
    out=await flow.reply(offer,True,'explicit_retry',source_event='new_retry_turn')
    assert out['channel']=='netease_native_invite'
    assert [c.args[0] for c in api.call.await_args_list].count('api')==1
    assert not flow.retryable()
    svc.notice.assert_awaited_once() # original proposal only, no second confirmation.

@pytest.mark.asyncio
async def test_uncertain_invite_is_never_eligible_for_user_retry(setup):
    cfg,store,api,svc=setup;flow=TogetherFlow(cfg,store,svc)
    oid=(await flow.propose('101','一起听？','p',source_event='p'))['offer_id']
    async def call(path,**kwargs):
        if path=='listentogether/room/create':return {'code':200,'data':{'roomInfo':{'roomId':'123'}}}
        if path=='api':raise ApiError('network')
        return {'code':200}
    api.call.side_effect=call
    with pytest.raises(ApiError):await flow.reply(oid,True,'r',source_event='r')
    assert not flow.retryable()
    assert store.data['together_offer']['status']=='unknown'
    before=api.call.await_count
    assert (await flow.reply(oid,True,'later',source_event='later'))['status']=='no_pending_offer'
    assert api.call.await_count==before

@pytest.mark.asyncio
async def test_proposal_does_not_claim_invitation_or_click_to_connect(setup):
    cfg,store,api,svc=setup;flow=TogetherFlow(cfg,store,svc)
    out=await flow.propose('101','那我再发一次邀请，点一下就能连上了哦～','p')
    svc.notice.assert_awaited_once_with('要不要一起听《Test》？')
    assert out['qq_notice']=='sent'
    assert out['user_message']=='要不要一起听《Test》？'
    api.call.assert_not_awaited()

@pytest.mark.asyncio
async def test_audio_risk_uses_one_authorized_fallback_and_reuses_unexpired_url():
    api=NcmApi({},None)
    api.call=AsyncMock(side_effect=[ApiError('-460'),{'data':[{'url':'https://example.test/a','expi':1200}]}])
    assert await api.audio('101')=='https://example.test/a'
    assert await api.audio('101')=='https://example.test/a'
    assert [c.args[0] for c in api.call.await_args_list]==['song/url/v1','song/url']
    assert api.call.await_args.kwargs=={'id':'101','br':128000}

@pytest.mark.asyncio
@pytest.mark.parametrize('code',['network','301','403'])
async def test_other_audio_errors_do_not_trigger_fallback(code):
    api=NcmApi({},None);api.call=AsyncMock(side_effect=ApiError(code))
    with pytest.raises(ApiError):await api.audio('101')
    assert api.call.await_count==1

@pytest.mark.asyncio
async def test_fallback_trial_and_expired_url_are_not_reused():
    api=NcmApi({},None);api.call=AsyncMock(side_effect=[ApiError('-460'),{'data':[{'url':'https://example.test/trial','freeTrialInfo':{ 'start':1}}]}])
    with pytest.raises(ApiError,match='audio_unavailable'):await api.audio('101')
    assert not api._audio_cache
    api._audio_cache['101']={'url':'old','expires_at':time.monotonic()-1}
    api.call=AsyncMock(return_value={'data':[{'url':'new','expi':1200}]})
    assert await api.audio('101')=='new'

@pytest.mark.asyncio
async def test_api_preserves_safe_risk_code_from_http_error():
    class Response:
        status=400
        async def __aenter__(self):return self
        async def __aexit__(self,*args):pass
        async def json(self,**kwargs):return {'code':-460,'message':'arbitrary private upstream text'}
    api=NcmApi({'api_base':'http://ncm.test'},NS(cookie=lambda:'private-cookie'))
    api.session=NS(closed=False,post=lambda *a,**kw:Response())
    with pytest.raises(ApiError) as caught:await api.call('song/url/v1',id='101')
    assert caught.value.code=='-460' and caught.value.path=='song/url/v1'
    assert 'arbitrary' not in str(caught.value) and 'cookie' not in str(caught.value)
