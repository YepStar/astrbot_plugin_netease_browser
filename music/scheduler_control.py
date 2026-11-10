"""Public scheduler facade v1: durable lease + serialized autonomy, not playback ownership."""
import asyncio
import sqlite3
import time
from pathlib import Path
from contextlib import contextmanager

OWNER = 'astrbot_plugin_third_party_platforms'

class SchedulerControl:
    def __init__(self,root,*,clock=time.time):
        self.path=Path(root)/'scheduler-control.sqlite3';self.clock=clock;self.lock=asyncio.Lock()
        with self.connect() as db:
            db.executescript('''CREATE TABLE IF NOT EXISTS lease(id INTEGER PRIMARY KEY CHECK(id=1),owner TEXT NOT NULL,expires REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS runs(key TEXT PRIMARY KEY,state TEXT NOT NULL,at REAL NOT NULL,code TEXT NOT NULL);''')
            db.execute("UPDATE runs SET state='unknown',code='process_interrupted' WHERE state='executing'")
        self.path.chmod(0o600)
    @contextmanager
    def connect(self):
        self.path.parent.mkdir(parents=True,exist_ok=True)
        db=sqlite3.connect(self.path,timeout=10)
        try:
            with db:yield db
        finally:db.close()
    def lease(self):
        with self.connect() as db:row=db.execute('SELECT owner,expires FROM lease WHERE id=1').fetchone()
        return {'owner':row[0],'expires':row[1]} if row and row[1]>self.clock() else {'owner':'music','expires':0}
    async def acquire(self,owner,ttl=90):
        if owner!=OWNER or not 15<=ttl<=300:raise ValueError('invalid_scheduler_lease')
        # Renewal is a DB transaction, independent of the long-running autonomy lock.
        # Otherwise a slow model call could prevent heartbeats and release ownership accidentally.
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE');row=db.execute('SELECT owner,expires FROM lease WHERE id=1').fetchone()
            if row and row[0]!=owner and row[1]>self.clock():return False
            db.execute('INSERT OR REPLACE INTO lease VALUES(1,?,?)',(owner,self.clock()+ttl))
        return True
    async def release(self,owner):
        if owner!=OWNER:raise ValueError('invalid_scheduler_owner')
        async with self.lock:
            with self.connect() as db:db.execute('DELETE FROM lease WHERE id=1 AND owner=?',(owner,))
    async def local(self,plugin):
        async with self.lock:
            # Room lifecycle and already-confirmed together-listening remain with music.
            if plugin.store.data.get('room') or self.lease()['owner']=='music':
                await plugin.autonomy.tick()
    async def run(self,plugin,owner,key):
        if owner!=OWNER or not isinstance(key,str) or not 1<=len(key)<=200:raise ValueError('invalid_scheduled_run')
        async with self.lock:
            if self.lease()['owner']!=owner:return {'state':'failed','code':'lease_expired'}
            with self.connect() as db:
                db.execute('BEGIN IMMEDIATE');row=db.execute('SELECT state,code FROM runs WHERE key=?',(key,)).fetchone()
                if row:return {'state':row[0] if row[0]!='executing' else 'unknown','code':row[1]}
                if not plugin.settings['enabled'] or not plugin.settings['autonomous_enabled'] or not plugin.store.cookie():
                    return {'state':'failed','code':'music_not_ready'}
                if plugin.store.data.get('room') or plugin.service.current:
                    return {'state':'failed','code':'already_listening'}
                db.execute("INSERT INTO runs VALUES(?,'executing',?,'')",(key,self.clock()))
            state,code='unknown','interrupted'
            try:
                await plugin.autonomy.tick()
                state,code='succeeded','decision_processed' # Not a claim that audio playback started.
            except asyncio.CancelledError:raise
            except Exception as exc:code=type(exc).__name__
            finally:
                with self.connect() as db:db.execute('UPDATE runs SET state=?,code=? WHERE key=?',(state,code,key))
            return {'state':state,'code':code}
