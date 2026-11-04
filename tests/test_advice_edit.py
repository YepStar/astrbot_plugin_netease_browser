import json
from unittest.mock import AsyncMock
import pytest
from test_preferences import prefs
from test_adapter import plugin,web_request
from music.storage import Store
from music.preferences import MusicPreferences

async def seed(prefs):
    prefs.capture('多听民谣','message')
    await prefs.refresh()
    return prefs.snapshot()['items'][0]

@pytest.mark.asyncio
async def test_edit_is_durable_and_auto_refresh_cannot_overwrite_it(prefs):
    row=await seed(prefs)
    saved=prefs.edit(row['entry_id'],'多听民谣和爵士','优先听现场版本',row['revision'],prefs.scope())
    assert saved['manual'] and saved['original_quote']=='多听民谣'
    assert saved['context_quotes']==[{'source_id':'manual','quote':'优先听现场版本'}]
    # New source ID causes a fresh extraction of the original text.
    prefs.capture('多听民谣','new-message')
    await prefs.refresh()
    items=prefs.snapshot()['items']
    assert len(items)==1 and items[0]['quote']=='多听民谣和爵士'
    recovered=MusicPreferences(prefs.cfg,Store(prefs.store.root),prefs.context,prefs.generate)
    assert recovered.snapshot()['items']==items
    assert items[0]['entry_id']==row['entry_id']

@pytest.mark.asyncio
async def test_stale_edit_cannot_overwrite_newer_manual_edit(prefs):
    row=await seed(prefs)
    prefs.edit(row['entry_id'],'多听爵士','',row['revision'],prefs.scope())
    with pytest.raises(ValueError,match='已更新'):
        prefs.edit(row['entry_id'],'多听摇滚','',row['revision'],prefs.scope())
    assert prefs.snapshot()['items'][0]['quote']=='多听爵士'

@pytest.mark.asyncio
async def test_other_scope_and_hidden_memory_cannot_be_edited(prefs):
    row=await seed(prefs)
    with pytest.raises(ValueError,match='会话或人格'):
        prefs.edit(row['entry_id'],'x','',row['revision'],'wrong-scope')
    state=prefs.state();state['items']=[{'kind':'memory','plugin':'astrbot_plugin_livingmemory','quote':'爵士','id':'memory:1','at':1}]
    hidden=state['items'][0]
    with pytest.raises(ValueError,match='不可见'):
        prefs.edit(prefs.entry_id(hidden),'x','',prefs.revision(hidden),prefs.scope())

@pytest.mark.asyncio
@pytest.mark.parametrize('quote,context',[('', ''),('x'*1001,''),('abc','x'*1001),(None,'')])
async def test_invalid_edit_changes_nothing(prefs,quote,context):
    row=await seed(prefs)
    with pytest.raises(ValueError):prefs.edit(row['entry_id'],quote,context,row['revision'],prefs.scope())
    assert prefs.snapshot()['items'][0]['quote']=='多听民谣'

@pytest.mark.asyncio
async def test_edit_one_item_preserves_other_items(prefs):
    row=await seed(prefs)
    prefs.state()['items'].append({'kind':'dialogue','quote':'纯音乐','id':'other','at':1})
    prefs.edit(row['entry_id'],'多听现场民谣','',row['revision'],prefs.scope())
    assert {r['quote'] for r in prefs.snapshot()['items']}=={'多听现场民谣','纯音乐'}

@pytest.mark.asyncio
async def test_http_edit_returns_saved_item(plugin,web_request):
    prefs=plugin.preferences
    prefs.state()['items']=[{'id':'source','kind':'dialogue','quote':'民谣','at':1,'recorded_at':1}]
    row=prefs.snapshot()['items'][0]
    body={'entry_id':row['entry_id'],'revision':row['revision'],'scope':prefs.scope(),'quote':'民谣与爵士','context':'先听热门歌'}
    with web_request(body):response=await plugin.panel.edit_preference()
    assert response.status_code==200
    assert json.loads(response.body)['item']['quote']=='民谣与爵士'
    assert prefs.snapshot()['items'][0]['manual']

@pytest.mark.asyncio
@pytest.mark.parametrize('body',[{}, {'confirmed':False}, {'confirmed':'true'}, {'confirmed':True,'scope':'old-scope'}])
async def test_clear_rejects_missing_or_invalid_confirmation(plugin,web_request,body):
    plugin.preferences.state()['items']=[{'id':'x','kind':'dialogue','quote':'民谣','at':1}]
    with web_request(body):response=await plugin.panel.clear_preferences()
    assert response.status_code==400
    assert len(plugin.preferences.state()['items'])==1

@pytest.mark.asyncio
async def test_clear_accepts_only_confirmed_current_scope(plugin,web_request):
    plugin.preferences.state()['items']=[{'id':'x','kind':'dialogue','quote':'民谣','at':1}]
    with web_request({'confirmed':True,'scope':plugin.preferences.scope()}):response=await plugin.panel.clear_preferences()
    assert response.status_code==200
    assert not plugin.preferences.snapshot()['items']
