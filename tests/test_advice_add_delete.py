import json
import pytest
from test_preferences import prefs
from test_advice_edit import seed
from test_adapter import plugin,web_request
from music.storage import Store
from music.preferences import MusicPreferences

@pytest.mark.asyncio
async def test_manual_add_is_visible_without_memory_and_survives_restart_refresh(prefs):
    row=prefs.add('多听独立民谣','优先现场版本',prefs.scope())
    assert row['kind']=='manual' and row['manual']
    assert prefs.snapshot()['items'][0]['quote']=='多听独立民谣'
    await prefs.refresh()
    recovered=MusicPreferences(prefs.cfg,Store(prefs.store.root),prefs.context,prefs.generate)
    assert recovered.snapshot()['items'][0]['entry_id']==row['entry_id']
    assert recovered.snapshot()['items'][0]['context_quotes'][0]['quote']=='优先现场版本'

@pytest.mark.asyncio
async def test_added_row_can_be_edited_and_deleted_individually(prefs):
    row=prefs.add('爵士','',prefs.scope())
    prefs.add('民谣','',prefs.scope())
    row=prefs.edit(row['entry_id'],'爵士现场','',row['revision'],prefs.scope())
    prefs.delete(row['entry_id'],row['revision'],prefs.scope())
    assert [r['quote'] for r in prefs.snapshot()['items']]==['民谣']

@pytest.mark.asyncio
async def test_deleted_extracted_advice_is_not_restored_by_later_filter(prefs):
    row=await seed(prefs)
    prefs.delete(row['entry_id'],row['revision'],prefs.scope())
    prefs.capture('多听民谣','another-source')
    await prefs.refresh()
    assert not prefs.snapshot()['items']
    recovered=MusicPreferences(prefs.cfg,Store(prefs.store.root),prefs.context,prefs.generate)
    assert recovered.state()['deleted_entries']
    manual=recovered.add('多听民谣','我手动重新添加',recovered.scope())
    await recovered.refresh()
    assert recovered.snapshot()['items'][0]['entry_id']==manual['entry_id']

@pytest.mark.asyncio
async def test_delete_edited_auto_item_suppresses_original_too(prefs):
    row=await seed(prefs)
    row=prefs.edit(row['entry_id'],'多听民谣现场','',row['revision'],prefs.scope())
    prefs.delete(row['entry_id'],row['revision'],prefs.scope())
    prefs.capture('多听民谣','fresh-source')
    await prefs.refresh()
    assert not prefs.snapshot()['items']

@pytest.mark.asyncio
async def test_stale_or_wrong_scope_delete_preserves_item(prefs):
    row=prefs.add('民谣','',prefs.scope())
    with pytest.raises(ValueError):prefs.delete(row['entry_id'],row['revision'],'wrong')
    prefs.edit(row['entry_id'],'纯音乐','',row['revision'],prefs.scope())
    with pytest.raises(ValueError,match='已更新'):prefs.delete(row['entry_id'],row['revision'],prefs.scope())
    assert prefs.snapshot()['items'][0]['quote']=='纯音乐'

@pytest.mark.asyncio
@pytest.mark.parametrize('quote,context,scope',[('', '',None),('x'*1001,'',None),('abc','x'*1001,None),('abc','','bad')])
async def test_invalid_manual_add(prefs,quote,context,scope):
    with pytest.raises(ValueError):prefs.add(quote,context,prefs.scope() if scope is None else scope)
    assert not prefs.snapshot()['items']

@pytest.mark.asyncio
async def test_http_add_delete_without_any_confirmation_field(plugin,web_request):
    p=plugin.preferences
    with web_request({'quote':'多听民谣','context':'先听热门歌','scope':p.scope()}):response=await plugin.panel.add_preference()
    assert response.status_code==200
    row=json.loads(response.body)['item']
    with web_request({'entry_id':row['entry_id'],'revision':row['revision'],'scope':p.scope()}):response=await plugin.panel.delete_preference()
    assert response.status_code==200 and not p.snapshot()['items']

@pytest.mark.asyncio
async def test_manual_kind_participates_in_selection_context(prefs):
    prefs.add('每周听一些摇滚','',prefs.scope())
    result=await prefs.refresh()
    assert result['items'][0]['quote']=='每周听一些摇滚'
    assert result['status']['memory']=='disabled'
