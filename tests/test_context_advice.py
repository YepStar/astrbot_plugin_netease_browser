import json,time
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock
import pytest
from test_preferences import prefs

NAMES='赵雷、宋冬野、陈粒、房东的猫、谢春花、王贰浪、马頔金玟岐、许巍'
REQUEST='我给你一些歌手名，你去听听他们的热门歌好不好'

def contextual_extract(phase,data):
    sources=data['sources']
    targets=[row for row in sources if row['content']==NAMES]
    requests=[row for row in sources if REQUEST in row['content']]
    return {'items':[{'source_id':targets[0]['id'],'quote':NAMES,'context_quotes':[{'source_id':requests[0]['id'],'quote':REQUEST}]}]} if targets and requests else {'items':[]}

@pytest.mark.asyncio
async def test_bare_names_capture_keeps_previously_processed_request(prefs):
    prefs.generate=AsyncMock(side_effect=contextual_extract)
    prefs.capture(REQUEST,'first')
    await prefs.refresh()
    prefs.capture(NAMES,'second')
    assert prefs.state()['pending'][0]['content']==NAMES
    out=await prefs.refresh()
    assert out['items'][0]['quote']==NAMES
    assert out['items'][0]['context_quotes'][0]['quote']==REQUEST

@pytest.mark.asyncio
async def test_changed_dialogue_reconsiders_sources_already_marked_processed(prefs):
    prefs.generate=AsyncMock(side_effect=contextual_extract)
    manager=prefs.context.conversation_manager
    manager.get_conversation.return_value=NS(history=[{'role':'user','content':REQUEST}])
    await prefs.refresh()
    assert prefs.state()['processed']
    manager.get_conversation.return_value=NS(history=[{'role':'user','content':REQUEST},{'role':'assistant','content':'好呀，把名字发来。'},{'role':'user','content':NAMES}])
    out=await prefs.refresh()
    assert len(out['items'])==1 and out['items'][0]['quote']==NAMES
    assert all(row['kind']=='dialogue' for row in prefs.generate.await_args.args[1]['sources'])
    calls=prefs.generate.await_count
    await prefs.refresh();assert prefs.generate.await_count==calls

@pytest.mark.asyncio
async def test_upgrade_reprocesses_old_orphan_and_preserves_other_preferences(prefs):
    prefs.generate=AsyncMock(side_effect=contextual_extract)
    state=prefs.state();state.pop('extractor_version')
    state['items']=[{'id':'old','kind':'dialogue','quote':'听听他们的热门歌','at':1},{'id':'folk','kind':'dialogue','quote':'多听听民谣','at':2}]
    prefs.context.conversation_manager.get_conversation.return_value=NS(history=[{'role':'user','content':REQUEST},{'role':'user','content':NAMES}])
    state['processed']=[r['id'] for r in await prefs.dialogue()]
    out=await prefs.refresh()
    assert [r['quote'] for r in out['items']]==['多听听民谣',NAMES]
    assert state['extractor_version']==2

@pytest.mark.asyncio
async def test_platform_metadata_is_removed_and_rich_text_is_read(prefs):
    prefs.generate=AsyncMock(side_effect=contextual_extract)
    prefs.context.conversation_manager.get_conversation.return_value=NS(history=[{'role':'user','content':REQUEST+'\n<system_reminder>User ID: 12345</system_reminder>'},{'role':'user','content':[{'type':'text','text':NAMES}]}])
    out=await prefs.refresh()
    assert out['items'][0]['quote']==NAMES
    assert 'User ID' not in json.dumps(prefs.generate.await_args.args[1],ensure_ascii=False)

@pytest.mark.asyncio
async def test_hallucinated_context_is_not_stored_or_marked_processed(prefs):
    prefs.capture(REQUEST,'first');prefs.capture(NAMES,'second')
    sid=prefs.state()['pending'][-1]['id']
    prefs.generate=AsyncMock(return_value={'items':[{'source_id':sid,'quote':NAMES,'context_quotes':[{'source_id':'invented','quote':REQUEST}]}]})
    out=await prefs.refresh()
    assert out['status']['extraction']=='unavailable' and not out['items']
    assert not prefs.state()['processed']

@pytest.mark.asyncio
async def test_nonmusic_list_without_music_context_is_not_captured(prefs):
    prefs.capture('北京、上海、广州','unrelated')
    assert not prefs.state()['pending']

@pytest.mark.asyncio
async def test_clear_keeps_old_full_context_from_reimporting(prefs):
    prefs.generate=AsyncMock(side_effect=contextual_extract)
    prefs.context.conversation_manager.get_conversation.return_value=NS(history=[{'role':'user','content':REQUEST},{'role':'user','content':NAMES}])
    await prefs.refresh();prefs.clear()
    assert not (await prefs.refresh())['items']
