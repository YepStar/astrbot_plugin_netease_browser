import json
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock
import pytest
from test_music import setup,SONG
from music.api import ApiError,NcmApi
from music.together import TogetherFlow

@pytest.mark.asyncio
async def test_proposal_uses_only_natural_message_without_duplicate_process_text(setup):
    cfg,store,api,svc=setup
    natural='这首歌安静得像把时间放慢了，要不要一起来听一会儿？'
    result=await TogetherFlow(cfg,store,svc).propose('101',natural,'proposal')
    assert result['status']=='awaiting_confirmation'
    svc.notice.assert_awaited_once_with(natural)
    assert '你答应后' not in svc.notice.await_args.args[0]
    api.call.assert_not_awaited()

@pytest.mark.asyncio
async def test_empty_message_has_one_natural_invitation(setup):
    cfg,store,api,svc=setup
    await TogetherFlow(cfg,store,svc).propose('101','','proposal')
    svc.notice.assert_awaited_once_with('刚听到《Test》，想和你一起听会儿。')
    assert svc.notice.await_args.args[0].count('Test')==1

@pytest.mark.asyncio
async def test_native_invite_failure_never_falls_back_to_text_or_retries(setup):
    cfg,store,api,svc=setup
    store.data['together_offer']={'id':'consent','status':'accepted','song':SONG,'recipient':'55','owner_umo':cfg['owner_umo']}
    async def call(path,**kwargs):
        if path=='listentogether/room/create':return {'code':200,'data':{'roomInfo':{'roomId':'123'}}}
        if path=='api':raise ApiError('488')
        return {'code':200}
    api.call.side_effect=call
    with pytest.raises(ApiError):await svc.invite('101','一起听会儿','invite',consent_id='consent')
    assert store.data['operations']['invite']['status']=='unknown'
    assert store.data['room'] is None
    before=api.call.await_count
    assert (await svc.invite('101','一起听会儿','invite',consent_id='consent'))['status']=='duplicate'
    assert api.call.await_count==before
    assert all(c.args[0] not in ['send/text','send/song'] for c in api.call.await_args_list)
    svc.notice.assert_not_awaited()

@pytest.mark.asyncio
async def test_generic_api_gateway_preserves_native_fields_and_private_cookie(tmp_path):
    from music.storage import Store
    store=Store(tmp_path);store.save_cookie('private_cookie')
    calls=[]
    class Response:
        status=200
        async def __aenter__(self):return self
        async def __aexit__(self,*args):pass
        async def json(self,**kwargs):return {'code':200}
    def post(url,**kwargs):calls.append((url,kwargs));return Response()
    api=NcmApi({'api_base':'http://ncm-api:3000'},store)
    api.session=NS(closed=False,post=post)
    await api.call('api',uri='/api/listen/together/invite/message/send',data=json.dumps({'roomId':'123','acceptorId':'55'}))
    url,request=calls[0]
    assert url=='http://ncm-api:3000/api' and 'private_cookie' not in url
    body=request['data']
    assert body['uri']=='/api/listen/together/invite/message/send'
    assert json.loads(body['data'])=={'roomId':'123','acceptorId':'55'}
    assert body['cookie']=='private_cookie'
    assert request['params']['timestamp']
