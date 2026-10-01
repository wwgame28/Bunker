from unittest.mock import AsyncMock
import json
import time
import pytest
from aiogram import Bot, Dispatcher
from aiogram.types import Update
from aiogram.exceptions import TelegramForbiddenError,TelegramNetworkError,TelegramRetryAfter
from aiogram.methods import SendMessage
from bunker.handlers.telegram import make_router
from bunker.services.delivery import deliver_once
from test_persistence import started

@pytest.mark.asyncio
async def test_dispatcher_private_start_create_bind_join(service):
    s=service; bot=Bot('123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi')
    bot.session=AsyncMock()
    dp=Dispatcher(disable_fsm=True); dp.include_router(make_router(s))
    async def message(uid,text,chat=None):
        update=Update.model_validate({'update_id':uid+int(time.time()),'message':{
            'message_id':int(time.time())+uid,'date':int(time.time()),'text':text,
            'from':{'id':uid,'is_bot':False,'first_name':f'User {uid}'},
            'chat':{'id':chat or uid,'type':'supergroup' if chat else 'private'},
            'entities':[{'type':'bot_command','offset':0,'length':len(text.split()[0])}]}})
        await dp.feed_update(bot,update)
    await message(1,'/start')
    await message(1,'/new')
    r=s.repo.rooms()[0]
    await message(1,'/start b_'+r['code'],-100)
    for uid in (2,3,4): await message(uid,'/start j_'+r['code'])
    r=s.get(r['code'])
    assert r['chat_id']==-100 and len(r['players'])==4
    assert all(p['reachable'] for p in r['players'].values())
    await bot.session.close()

@pytest.mark.asyncio
async def test_callback_rejects_group_vote_and_outsider(service):
    s=service; r=started(s); bot=Bot('123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi'); bot.session=AsyncMock()
    dp=Dispatcher(disable_fsm=True); dp.include_router(make_router(s))
    update=Update.model_validate({'update_id':99,'callback_query':{'id':'q99','from':{'id':999,'is_bot':False,'first_name':'Other'},'chat_instance':'test',
        'data':f"g:{r['code']}:{r['epoch']}:card:",
        'message':{'message_id':1,'date':int(time.time()),'chat':{'id':-100,'type':'supergroup'},'text':'panel'}}})
    await dp.feed_update(bot,update)
    rows=s.repo.db.execute('SELECT payload FROM outbox WHERE chat_id=999').fetchall()
    assert rows and all('🔒' not in row[0] for row in rows)
    await bot.session.close()

@pytest.mark.asyncio
@pytest.mark.parametrize('error',[TelegramNetworkError(method=SendMessage(chat_id=10,text='x'),message='offline'),TelegramRetryAfter(method=SendMessage(chat_id=10,text='x'),message='retry',retry_after=5)])
async def test_delivery_retry_survives(service,error):
    s=service; s.repo.enqueue(10,'test')
    bot=AsyncMock(); bot.send_message.side_effect=error
    await deliver_once(bot,s,100)
    row=s.repo.db.execute('SELECT * FROM outbox').fetchone()
    assert row['status']=='pending' and row['not_before']>100
    bot.send_message.side_effect=None
    await deliver_once(bot,s,200)
    assert s.repo.db.execute('SELECT count(*) FROM outbox').fetchone()[0]==0

@pytest.mark.asyncio
async def test_delivery_blocked_user_not_infinite_retry(service):
    s=service; r=started(s)
    s.repo.db.execute('DELETE FROM outbox'); s.repo.enqueue(1,'test',room=r['code'])
    bot=AsyncMock(); bot.send_message.side_effect=TelegramForbiddenError(method=SendMessage(chat_id=1,text='x'),message='blocked')
    await deliver_once(bot,s,100)
    assert s.get(r['code'])['players']['1']['status']=='left'
    assert s.repo.db.execute("SELECT count(*) FROM outbox WHERE status='dead'").fetchone()[0]==1

@pytest.mark.asyncio
async def test_entire_party_through_real_callback_router(service):
    from bunker.engine import game
    from bunker.states import Phase
    s=service; s.register(1,'Player 1'); room=s.create(1,'Player 1','e2e',-100)
    for i in (2,3,4): s.join(room['code'],i,f'Player {i}')
    bot=Bot('123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi'); bot.session=AsyncMock()
    dp=Dispatcher(disable_fsm=True); dp.include_router(make_router(s))
    seq=0
    async def click(uid,action,arg=''):
        nonlocal seq
        seq+=1; r=s.get(room['code'])
        u=Update.model_validate({'update_id':seq,'callback_query':{
            'id':f'e2e-{seq}','from':{'id':int(uid),'is_bot':False,'first_name':f'Player {uid}'},'chat_instance':'private',
            'data':f"g:{r['code']}:{r['epoch']}:{action}:{arg}",
            'message':{'message_id':seq,'date':int(time.time()),'chat':{'id':int(uid),'type':'private'},'text':'Panel'}}})
        await dp.feed_update(bot,u)
    await click(1,'timer','off'); await click(1,'start')
    for _ in range(150):
        r=s.get(room['code']); phase=r['phase']
        if phase==Phase.FINISHED: break
        if phase in (Phase.STORY,Phase.DISCUSS,Phase.FINAL,Phase.DEFENSE):
            for uid in game.ready_eligible(r): await click(uid,'ready')
        elif phase==Phase.REVEAL:
            uid=r['turn']; await click(uid,'reveal',game.available_fields(r,r['players'][uid])[0])
        elif phase==Phase.EVENT:
            for p in game.active(r): await click(p['id'],'choose','0')
        elif phase==Phase.VOTE:
            for p in game.active(r): await click(p['id'],'vote',next(x for x in game.candidates(r) if x!=p['id']))
    r=s.get(room['code'])
    assert r['phase']==Phase.FINISHED and r['act']==10
    assert len(game.active(r))==2
    out=s.repo.db.execute('SELECT payload FROM outbox WHERE chat_id=-100').fetchall()
    assert any('Прошло' in row[0] for row in out)
    await bot.session.close()
