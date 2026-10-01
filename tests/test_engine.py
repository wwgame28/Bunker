import copy
import json
import random
import pytest
from bunker.engine import game
from bunker.engine.game import GameError
from bunker.states import Phase
from bunker.content import MINIMUMS
from bunker.services.views import public_text,roster_text,private_text
from bunker.keyboards.ui import private_keyboard, public_keyboard

def step(r,content,now=0):
    phase=r['phase']; epoch=r['epoch']
    if phase in (Phase.STORY,Phase.DISCUSS,Phase.FINAL,Phase.DEFENSE):
        for uid in list(game.ready_eligible(r)):
            if r['epoch']!=epoch: break
            game.apply(r,uid,'ready','',epoch,now,content)
    elif phase==Phase.REVEAL:
        uid=r['turn']; fields=game.available_fields(r,r['players'][uid])
        game.apply(r,uid,'reveal',fields[0],epoch,now,content)
    elif phase==Phase.EVENT:
        for p in list(game.active(r)):
            game.apply(r,p['id'],'choose','0',epoch,now,content)
    elif phase==Phase.VOTE:
        for p in list(game.active(r)):
            options=[x for x in game.candidates(r) if x!=p['id']]
            game.apply(r,p['id'],'vote',options[0],epoch,now,content)

@pytest.mark.parametrize('n',[4,5,6,7,8,9,10,11,12,13,14,15,16])
@pytest.mark.parametrize('seed',[1,47,831])
def test_complete_party_all_sizes(n,seed,room_factory,content):
    r=room_factory(n,seed)
    steps=0
    while r['phase']!=Phase.FINISHED:
        step(r,content); steps+=1
        assert steps<250
        # Every intermediate state is persistable without custom Python types.
        r=json.loads(json.dumps(r))
    assert len(game.active(r))==r['capacity']
    assert r['act']==10 and r['ending']
    assert len(r['events_used'])==6 and len(set(r['events_used']))==6
    assert all(p['name'] in r['epilogue'] for p in r['players'].values())
    assert all(isinstance(p['goal_success'],bool) for p in r['players'].values())

@pytest.mark.parametrize('n',[4,16])
def test_whole_party_timers_no_responses(n,room_factory,content):
    r=room_factory(n,timer='fast')
    for _ in range(250):
        if r['phase']==Phase.FINISHED: break
        assert r['deadline'] is not None
        game.advance(r,r['deadline']+10000,content)
    assert r['phase']==Phase.FINISHED
    assert len(game.active(r))==r['capacity']
    assert all('secret' not in p['revealed'] and 'relation' not in p['revealed'] for p in r['players'].values())


def to_reveal(r,content):
    while r['phase']!=Phase.REVEAL: step(r,content)


def test_wrong_turn_late_secret_and_stale_button(room_factory,content):
    r=room_factory(); to_reveal(r,content)
    with pytest.raises(GameError): game.apply(r,2,'reveal','profession',r['epoch'],0,content)
    with pytest.raises(GameError): game.apply(r,1,'reveal','secret',r['epoch'],0,content)
    old=r['epoch']; game.apply(r,1,'reveal','profession',old,0,content)
    with pytest.raises(GameError): game.apply(r,1,'reveal','profession',old,0,content)


def test_vote_private_double_vote_and_ties(room_factory,content):
    r=room_factory(4); r['act']=5; game.begin_vote(r,0)
    game.apply(r,1,'vote','2',r['epoch'],0,content)
    assert '2 — 1' not in public_text(r)
    assert 'votes' not in public_text(r)
    with pytest.raises(GameError): game.apply(r,1,'vote','3',r['epoch'],0,content)
    with pytest.raises(GameError): game.apply(r,2,'vote','2',r['epoch'],0,content)
    for uid,target in [('2','1'),('3','1'),('4','2')]: game.apply(r,uid,'vote',target,r['epoch'],0,content)
    assert r['phase']==Phase.DEFENSE and set(r['runoff'])=={'1','2'}
    step(r,content)
    assert r['vote_round']==2
    for uid,target in [('1','2'),('2','1'),('3','1'),('4','2')]: game.apply(r,uid,'vote',target,r['epoch'],0,content)
    assert any('жребий' in x['text'] for x in r['history'])
    assert sum(p['status']=='excluded' for p in r['players'].values())==1


def test_privacy_and_directed_relationship(room_factory):
    r=room_factory(8)
    r['players']['1']['card']['secret']['text']='CANARY-PRIVATE-SECRET'
    r['players']['1']['goal']['text']='CANARY-PRIVATE-GOAL'
    r['players']['1']['relations']=[{'target':'2','text':'CANARY-PRIVATE-RELATION','mutual':False}]
    r['players']['1']['card']['relation']['text']='CANARY-PRIVATE-RELATION'
    for text in [public_text(r),roster_text(r),private_text(r,2,True)]: assert 'CANARY-' not in text
    assert 'CANARY-PRIVATE-SECRET' in private_text(r,1,True)


def test_hidden_tags_do_not_help(room_factory,content):
    r=room_factory()
    for p in game.active(r):
        p['card']['skill']={'text':'радио','tags':['radio']}
        p['revealed']=['age']
    assert not game.public_tags(r)
    r['players']['1']['revealed'].append('skill')
    assert game.public_tags(r)=={'radio'}
    r['players']['1']['status']='excluded'
    assert not game.public_tags(r)


def test_special_single_use_and_spectator_rejected(room_factory,content):
    r=room_factory(); r['act']=3
    game.apply(r,1,'special','',r['epoch'],0,content)
    with pytest.raises(GameError): game.apply(r,1,'special','',r['epoch'],0,content)
    r['players']['2']['status']='excluded'
    with pytest.raises(GameError): game.apply(r,2,'special','',r['epoch'],0,content)


def test_host_leave_turn_and_rejoin(room_factory,content):
    r=room_factory(); to_reveal(r,content)
    game.apply(r,1,'leave','',r['epoch'],0,content)
    assert r['host']=='2' and r['turn']=='2'
    game.join(r,1,'Вернулся')
    assert r['players']['1']['status']=='left'
    while r['phase']!=Phase.FINISHED: step(r,content)
    assert len(game.active(r))==2


def test_everybody_leaves(room_factory,content):
    r=room_factory()
    for uid in list(r['players']): game.leave(r,uid,0,content)
    assert r['phase']==Phase.FINISHED and r['deadline'] is None


def test_mobile_button_limits(room_factory,content):
    r=room_factory(16)
    while r['phase']!=Phase.FINISHED:
        for uid in r['players']:
            keyboard=private_keyboard(r,uid,'test_bot')
            assert len(keyboard['inline_keyboard'])<=25
            for row in keyboard['inline_keyboard']:
                assert len(row)<=2
                for b in row:
                    if 'callback_data' in b: assert len(b['callback_data'].encode())<=64
        step(r,content)


def test_content_minima_and_effect_schema(content):
    counts=content.validate()
    for key,n in MINIMUMS.items(): assert len(content.pool(key,['core']))>=n
    assert counts['events']==101

@pytest.mark.parametrize('phase',[Phase.REVEAL,Phase.EVENT,Phase.DISCUSS,Phase.VOTE,Phase.DEFENSE])
def test_departures_at_each_phase(phase,room_factory,content):
    r=room_factory(6)
    for _ in range(100):
        if r['phase']==phase: break
        if phase==Phase.DEFENSE and r['phase']==Phase.VOTE:
            game.advance(r,0,content)
        else: step(r,content)
    assert r['phase']==phase
    game.leave(r,'1',0,content)
    for _ in range(150):
        if r['phase']==Phase.FINISHED: break
        step(r,content)
    assert r['phase']==Phase.FINISHED


def test_departure_satisfies_planned_exclusion(room_factory,content):
    r=room_factory(6); r['act']=4; game.begin_vote(r,0)
    assert game.exclusions_due(r)==1
    game.leave(r,'1',0,content)
    assert r['act']==5 and len(game.active(r))==5
    assert not any(p['status']=='excluded' for p in r['players'].values())


def test_single_remaining_runoff_candidate_never_stalls(room_factory,content):
    r=room_factory(8); r['act']=8; r['runoff']=['1','2']; r['vote_round']=2
    game.transition(r,Phase.VOTE,0)
    game.leave(r,'1',0,content)
    assert r['players']['2']['status']=='excluded'
    assert r['phase']==Phase.VOTE and r['vote_round']==1


def test_single_remaining_defense_candidate_never_stalls(room_factory,content):
    r=room_factory(8); r['act']=8; r['runoff']=['1','2']
    game.transition(r,Phase.DEFENSE,0)
    game.leave(r,'1',0,content)
    assert r['players']['2']['status']=='excluded'
    assert r['phase']==Phase.VOTE
