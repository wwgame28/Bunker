import json
import sqlite3
import pytest
from bunker.database.repository import Repository
from bunker.engine.game import GameError
from bunker.states import Phase
from bunker.services.game_service import GameService
from bunker.services.views import chunks


def started(s,n=4):
    s.register(1,'Один')
    r=s.create(1,'Один','create',-100)
    for i in range(2,n+1): s.join(r['code'],i,f'Игрок {i}')
    s.action(r['code'],1,'start','',r['epoch'],'start')
    return s.get(r['code'])


def test_restart_deadline_outbox_and_idempotency(service,content):
    s=service; r=started(s)
    s.action(r['code'],1,'ready','',r['epoch'],'same-callback')
    old=s.get(r['code'])
    s.action(r['code'],1,'ready','',r['epoch'],'same-callback')
    assert s.get(r['code'])==old
    path=s.repo.db.execute('PRAGMA database_list').fetchone()[2]
    second=Repository(path)
    recovered=GameService(second,content,'test_bunker_bot',clock=lambda:r['deadline']+2000)
    recovered.tick()
    new=second.get(r['code'])
    assert new['act']==2
    assert new['deadline']>r['deadline']+2000
    assert second.db.execute('SELECT count(*) FROM outbox').fetchone()[0]>0
    second.close()


def test_atomic_rollback(service):
    s=service; r=started(s)
    before=s.repo.db.execute('SELECT count(*) FROM outbox').fetchone()[0]
    with pytest.raises(GameError): s.action(r['code'],1,'reveal','secret',r['epoch'],'invalid')
    assert s.get(r['code'])==r
    assert s.repo.db.execute('SELECT count(*) FROM outbox').fetchone()[0]==before
    assert not s.repo.seen('invalid')


def test_secret_never_queued_to_group(service):
    s=service; r=started(s)
    r['players']['1']['card']['secret']['text']='SECRET-OWNER-ONLY'
    s.repo.save(r)
    s.read(r['code'],1,'card'); s.read(r['code'],2,'history'); s.read(r['code'],1,'refresh')
    for row in s.repo.db.execute('SELECT chat_id,payload FROM outbox'):
        if row[0]!=1: assert 'SECRET-OWNER-ONLY' not in row[1]
    with pytest.raises(GameError): s.read(r['code'],444,'card')


def test_off_timer_does_not_advance(service):
    s=service; r=started(s)
    r['timer']='off'; r['deadline']=None; s.repo.save(r)
    s.test_clock[0]+=999999; s.tick()
    assert s.get(r['code'])['act']==1


def test_blocked_host_transfers_and_reconnect_spectator(service):
    s=service; r=started(s)
    s.disconnected(1); r=s.get(r['code'])
    assert r['host']=='2' and r['players']['1']['status']=='left'
    s.register(1,'Вернулся'); s.join(r['code'],1,'Вернулся')
    assert s.get(r['code'])['players']['1']['status']=='left'


def test_lobby_start_requires_private_start(service):
    s=service; r=s.create(1,'Host','create',-100)
    for i in range(2,5): s.join(r['code'],i,str(i))
    with pytest.raises(GameError): s.action(r['code'],1,'start','',0,'start')
    s.join(r['code'],1,'Host'); s.action(r['code'],1,'start','',0,'start')
    assert s.get(r['code'])['act']==1


def test_admin_permissions_and_pack_snapshot(service):
    s=service; r=started(s)
    with pytest.raises(GameError): s.admin(1,'end',r['code'])
    with pytest.raises(GameError): s.admin(99,'pack','core')
    s.admin(99,'pack','two_rivers')
    assert s.repo.setting('packs',[])==['core']
    assert 'two_rivers' in s.get(r['code'])['packs']
    s.admin(99,'end',r['code'])
    assert s.get(r['code'])['phase']==Phase.FINISHED


def test_group_and_membership_limits(service):
    s=service; r=started(s)
    with pytest.raises(GameError): s.create(1,'Host','other')
    with pytest.raises(GameError): s.create(20,'Other','other',-100)
    with pytest.raises(GameError): s.join(r['code'],20,'Late')


def test_group_migration(service):
    s=service; r=started(s)
    s.migrate_group(-100,-100222)
    assert s.get(r['code'])['chat_id']==-100222
    assert not s.repo.db.execute('SELECT 1 FROM outbox WHERE chat_id=-100').fetchone()


def test_utf16_chunking():
    text='🎉'*10000+'\n'+ 'а'*6000
    parts=chunks(text)
    assert ''.join(parts)==text
    assert all(len(p.encode('utf-16-le'))//2<=3500 for p in parts)


def test_late_callback_cannot_race_expired_timer(service):
    s=service; r=started(s)
    s.test_clock[0]=r['deadline']+1
    with pytest.raises(GameError): s.action(r['code'],1,'ready','',r['epoch'],'late')
    assert s.get(r['code'])['act']==2


def test_old_room_creation_update_returns_same_room(service):
    s=service
    r=s.create(1,'User','repeat')
    assert s.create(1,'User','repeat')['code']==r['code']
    assert len(s.repo.rooms())==1


def test_vote_recovered_after_new_repository(service,content):
    from bunker.engine import game
    s=service; r=started(s)
    r['act']=5; game.begin_vote(r,s.clock()); s.repo.save(r)
    s.action(r['code'],1,'vote','2',r['epoch'],'vote-before-restart')
    path=s.repo.db.execute('PRAGMA database_list').fetchone()[2]
    other=Repository(path)
    restored=GameService(other,content,'test_bot',clock=s.clock)
    assert restored.get(r['code'])['votes']=={'1':'2'}
    with pytest.raises(GameError): restored.action(r['code'],1,'vote','3',r['epoch'],'vote-after-restart')
    assert restored.get(r['code'])['votes']=={'1':'2'}
    other.close()
