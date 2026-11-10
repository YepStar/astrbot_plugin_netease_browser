import asyncio
from pathlib import Path
import importlib.util
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock
import pytest
spec=importlib.util.spec_from_file_location('scheduler_control',Path(__file__).parents[1]/'music/scheduler_control.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

def plugin():return NS(settings={'enabled':True,'autonomous_enabled':True},store=NS(cookie=lambda:'present',data={'room':None}),service=NS(current=None),autonomy=NS(tick=AsyncMock()))

def test_takeover_suppresses_local_and_runs_once(tmp_path):
 async def run():
  ctl=m.SchedulerControl(tmp_path);p=plugin()
  assert await ctl.acquire(m.OWNER)
  await ctl.local(p);p.autonomy.tick.assert_not_awaited()
  assert (await ctl.run(p,m.OWNER,'key'))['code']=='decision_processed'
  await ctl.run(p,m.OWNER,'key');p.autonomy.tick.assert_awaited_once()
  await ctl.release(m.OWNER);await ctl.local(p);assert p.autonomy.tick.await_count==2
 asyncio.run(run())

def test_expired_lease_and_restart_receipt(tmp_path):
 async def run():
  now=[100];ctl=m.SchedulerControl(tmp_path,clock=lambda:now[0]);p=plugin()
  await ctl.acquire(m.OWNER,30);await ctl.run(p,m.OWNER,'key')
  ctl=m.SchedulerControl(tmp_path,clock=lambda:now[0]);await ctl.run(p,m.OWNER,'key');p.autonomy.tick.assert_awaited_once()
  now[0]=131;assert (await ctl.run(p,m.OWNER,'new'))['state']=='failed'
  await ctl.local(p);assert p.autonomy.tick.await_count==2
 asyncio.run(run())

def test_existing_room_keeps_music_autonomy(tmp_path):
 async def run():
  ctl=m.SchedulerControl(tmp_path);p=plugin();p.store.data['room']={'id':'room'}
  await ctl.acquire(m.OWNER);await ctl.local(p);p.autonomy.tick.assert_awaited_once()
  assert (await ctl.run(p,m.OWNER,'key'))['code']=='already_listening'
 asyncio.run(run())

def test_cancelled_external_run_is_not_replayed(tmp_path):
 async def run():
  ctl=m.SchedulerControl(tmp_path);p=plugin();p.autonomy.tick=AsyncMock(side_effect=asyncio.CancelledError)
  await ctl.acquire(m.OWNER)
  with pytest.raises(asyncio.CancelledError):await ctl.run(p,m.OWNER,'key')
  assert (await ctl.run(p,m.OWNER,'key'))['state']=='unknown'
  p.autonomy.tick.assert_awaited_once()
 asyncio.run(run())

def test_heartbeat_can_renew_while_external_decision_is_running(tmp_path):
 async def run():
  stamp=[100];ctl=m.SchedulerControl(tmp_path,clock=lambda:stamp[0]);p=plugin()
  entered=asyncio.Event();release=asyncio.Event()
  async def slow():entered.set();await release.wait()
  p.autonomy.tick=slow
  await ctl.acquire(m.OWNER,30)
  task=asyncio.create_task(ctl.run(p,m.OWNER,'slow'))
  await entered.wait();stamp[0]=120
  assert await asyncio.wait_for(ctl.acquire(m.OWNER,30),.5)
  stamp[0]=135;assert ctl.lease()['owner']==m.OWNER
  release.set();await task
 asyncio.run(run())


def test_publication_filter_is_scoped_to_external_decision_and_reset(tmp_path):
 async def run():
  ctl=m.SchedulerControl(tmp_path);p=plugin();seen=[]
  async def tick():
   gate=m.PUBLICATION_GATE.get();seen.append(gate)
   if gate is not None:assert await gate('share',{'id':1},{}) is False
  p.autonomy.tick=tick;gate=AsyncMock(return_value=False)
  await ctl.acquire(m.OWNER)
  await ctl.run(p,m.OWNER,'filtered',publication_gate=gate)
  gate.assert_awaited_once();assert m.PUBLICATION_GATE.get() is None
  await ctl.release(m.OWNER);await ctl.local(p)
  assert seen==[gate,None]
 asyncio.run(run())
