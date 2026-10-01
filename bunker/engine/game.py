"""Pure game domain: no Telegram objects, network or database access."""
from copy import deepcopy
import math
import random
from bunker.content import CATEGORIES, RESOURCES
from bunker.states import ACTS, GATES, Phase, TIMERS, FIELD_LABELS

class GameError(ValueError):
    pass

def require(ok, text):
    if not ok: raise GameError(text)

def active(r):
    return [p for p in r['players'].values() if p['status'] == 'active']

def pick(r, seq):
    require(bool(seq), 'Недостаточно контента для игры.')
    rng=random.Random(r['seed']+r['roll'])
    r['roll']+=1
    return deepcopy(rng.choice(list(seq)))

def name(r, uid):
    return r['players'].get(str(uid),{}).get('name','незнакомый человек')

def revealed_tags(p):
    return {tag for f in p['revealed'] for tag in p['card'].get(f,{}).get('tags',[])}

def public_tags(r):
    return {t for p in active(r) for t in revealed_tags(p)}

def record(r, text):
    r['history'].append({'act':r['act'], 'text':text})

def effect(r, changes):
    for key,delta in changes.items():
        r['resources'][key]=max(0,min(100,r['resources'][key]+delta))

def new_room(code, host, display_name, chat_id, now, seed, enabled, max_players=16):
    r=dict(schema=1, code=code, host=str(host), chat_id=chat_id, phase=Phase.LOBBY,
           act=0, epoch=0, deadline=None, timer='standard', players={},
           created_at=now, seed=seed, roll=0, packs=list(enabled), max_players=max_players,
           history=[], resources={x:65 for x in sorted(RESOURCES)}, ready=[], votes={},
           choices={}, turn=None, queue=[], done=[], runoff=[], vote_round=1,
           removed=0, initial=0, capacity=0, events_used=[], event=None,
           catastrophe=None, features=[], ending=None, epilogue='', rounds=0)
    join(r,host,display_name,False)
    return r

def join(r, uid, display_name, reachable=True):
    uid=str(uid)
    if uid in r['players']:
        r['players'][uid]['reachable']=reachable
        return
    require(r['phase']==Phase.LOBBY,'Партия уже идёт. Новые игроки не допускаются.')
    require(len(active(r))<r['max_players'],'Комната заполнена.')
    r['players'][uid]=dict(id=uid,name=display_name[:40],status='active',reachable=reachable,
        card={},revealed=[],relations=[],goal=None,special=None,special_used=False,goal_success=False)

def transition(r, phase, now, multiplier=1):
    r['phase']=phase
    r['epoch']+=1
    r['ready']=[]
    sec=TIMERS[r['timer']]
    r['deadline']=now+sec*multiplier if sec is not None else None
    if phase in (Phase.LOBBY,Phase.FINISHED): r['deadline']=None

def assign(r, content):
    pools={field:content.pool(cat,r['packs']) for field,cat in CATEGORIES.items()}
    # Avoid duplicate professions and biographies inside a party.
    for p in active(r):
        for field,pool in pools.items():
            p['card'][field]=pick(r,pool)
            if field in ('profession','biography'): pool.remove(p['card'][field])
        p['card']['age']={'text':str(pick(r,list(range(18,76)))),'tags':[]}
        p['card']['sex']={'text':pick(r,['Женщина','Мужчина']),'tags':[]}
        p['revealed']=['age','sex']
        p['special']=pick(r,content.pool('specials',r['packs']))
    people=active(r)
    # Directed ring: every participant knows at least one relation. Mutual edges
    # are duplicated explicitly; private projections never expose incoming edges.
    for i,p in enumerate(people):
        target=people[(i+1)%len(people)]
        rel=pick(r,content.pool('relations',r['packs']))
        p['relations'].append(dict(target=target['id'],text=rel['text'],mutual=rel['mutual']))
        if rel['mutual']:
            target['relations'].append(dict(target=p['id'],text=rel['text'],mutual=True))
        goal=pick(r,content.pool('goals',r['packs']))
        goal['target']=target['id']
        goal['text']=goal['text'].format(target=target['name'],threshold=goal['threshold'])
        p['goal']=goal
    for p in people:
        p['card']['relation']={'text':'; '.join(f"{x['text']} → {name(r,x['target'])}" for x in p['relations']),'tags':[]}
    r['catastrophe']=pick(r,content.pool('catastrophes',r['packs']))
    pool=content.pool('bunkers',r['packs'])
    for _ in range(3):
        feature=pick(r,pool); pool.remove(feature); r['features'].append(feature)
        effect(r,feature['effects'])
    r['initial']=len(people)
    r['capacity']=math.ceil(len(people)/2)

def enter_act(r, now, content):
    r['act']+=1
    a=r['act']
    record(r,f'Акт {a}. {ACTS[a-1]}')
    if a in (1,2,5,7):
        stage={1:0,2:1,5:2,7:3}[a]
        record(r,r['catastrophe']['stages'][stage])
    if a in (1,2):
        transition(r,Phase.STORY,now)
    elif a <= 8:
        r['queue']=[p['id'] for p in active(r)]
        r['done']=[]
        next_turn(r,now,content)
    elif a == 9:
        transition(r,Phase.FINAL,now)
        record(r,'Дверь закрывается. Проверьте запасы и примените оставшиеся особые условия. Обсудите последний план.')
    else:
        finish(r,now)

def available_fields(r,p):
    return [f for f,gate in GATES.items() if r['act']>=gate and f not in p['revealed']]

def next_turn(r,now,content):
    remaining=[uid for uid in r['queue'] if uid not in r['done'] and r['players'][uid]['status']=='active']
    if remaining:
        r['turn']=remaining[0]
        transition(r,Phase.REVEAL,now)
    else:
        r['turn']=None
        pool=[e for e in content.pool('events',r['packs']) if e['id'] not in r['events_used']]
        # Prefer relevant scenes without using hidden information.
        useful=[e for e in pool if set(e['needs']) & public_tags(r)]
        event=pick(r,useful if useful and r['act']%2==1 else pool)
        r['event']=event; r['events_used'].append(event['id']); r['choices']={}
        record(r,event['text'])
        transition(r,Phase.EVENT,now)

def resolve_event(r,now):
    counts=[sum(v==i for v in r['choices'].values()) for i in range(2)]
    # A tied/no-response group follows the declared conservative alternative.
    choice=0 if counts[0]>counts[1] else 1
    e=r['event']; opt=e['options'][choice]
    providers=[p for p in active(r) if set(e['needs']) & revealed_tags(p)]
    roll=None
    if opt['check']:
        roll=pick(r,range(1,7))
        bonus=min(3,len(providers)*2)
        success=roll+bonus>=5
    else:
        bonus=0; success=True
    changes=opt['effects'] if success else opt['failure']
    effect(r,changes)
    details=f' Проверка: d6={roll}, опыт +{bonus}, нужно 5.' if roll is not None else ''
    record(r,f"Решение: {opt['text']} ({counts[0]} / {counts[1]}). "
             +opt['success' if success else 'fail']+details+' '+str(changes))
    transition(r,Phase.DISCUSS,now,2)

def exclusions_due(r):
    planned=math.floor((r['initial']-r['capacity'])*(r['act']-2)/6)
    gone=r['initial']-len(active(r))
    return max(0,min(planned-gone,len(active(r))-r['capacity']))

def begin_vote(r,now,runoff=False):
    r['votes']={}
    if not runoff:
        r['runoff']=[]; r['vote_round']=1; r['rounds']+=1
    else:
        r['vote_round']=2
    transition(r,Phase.VOTE,now)

def candidates(r):
    ids=[p['id'] for p in active(r)]
    return [x for x in (r['runoff'] or ids) if x in ids]

def resolve_vote(r,now,content):
    eligible=candidates(r)
    if len(active(r))<=r['capacity'] or not eligible:
        enter_act(r,now,content); return
    counts={x:sum(v==x for v in r['votes'].values()) for x in eligible}
    high=max(counts.values())
    tied=[x for x,v in counts.items() if v==high]
    record(r,'Завершённое голосование: '+', '.join(f'{name(r,k)} — {v}' for k,v in counts.items()))
    if len(tied)>1 and r['vote_round']==1:
        r['runoff']=tied
        record(r,'Ничья. Право защиты: '+', '.join(name(r,x) for x in tied)+'. После защиты — повторное тайное голосование.')
        transition(r,Phase.DEFENSE,now)
        return
    loser=pick(r,tied)
    if len(tied)>1: record(r,'Повторная ничья: жребий аварийных жетонов выбрал '+name(r,loser)+'.')
    r['players'][loser]['status']='excluded'
    r['removed']+=1
    record(r,name(r,loser)+' покидает список жителей Бункера и переходит в наружный лагерь.')
    transfer_host(r)
    if exclusions_due(r)>0: begin_vote(r,now)
    else: enter_act(r,now,content)

def transfer_host(r):
    if r['players'][r['host']]['status']!='active' and active(r):
        r['host']=active(r)[0]['id']
        record(r,'Права организатора переданы: '+name(r,r['host']))

def finish(r,now):
    pressure=r['catastrophe']['pressure']
    effect(r,{pressure:-12})
    tags=public_tags(r)
    competency=min(12,len(tags)*2)
    roll=pick(r,range(1,21))
    weakest=min(r['resources'].values())
    score=sum(r['resources'].values())/6+competency+roll-10
    if weakest==0: score-=20
    ending='Новый берег' if score>=65 else 'Трудная весна' if score>=40 else 'Исход'
    r['ending']=ending
    days=pick(r,range(360,731))
    residents=active(r)
    for p in r['players'].values():
        p['survived']=p['status']=='active' and (ending!='Исход' or pick(r,range(1,7))>=3)
    for p in r['players'].values():
        g=p['goal']; k=g['kind']; target=r['players'][g['target']]
        ok=(k=='together' and target.get('survived',False)) or (k=='apart' and target['status']!='active')
        if k in RESOURCES: ok=r['resources'][k]>=g['threshold']
        if k=='medical': ok=any(q.get('survived') and 'medical' in revealed_tags(q) for q in residents)
        if k=='ending': ok=ending=='Новый берег'
        p['goal_success']=bool(p['survived'] and ok)
    descriptions={
      'Новый берег':'В укрытии сохранились запасы и мастерская. Выжившие закладывают новое поселение выше поймы.',
      'Трудная весна':'Группа пережила изоляцию, но запасы истощены. Теперь придётся объединяться с наружными лагерями.',
      'Исход':'Убежище перестало обеспечивать жизнь. Последняя экспедиция ищет безопасное место в пригороде.'}
    text=[f'Прошло {days} дней. Концовка: «{ending}».',r['catastrophe']['stages'][-1],
          descriptions[ending],f'Из {len(residents)} оставшихся дверь пересекли {sum(p["survived"] for p in residents)}.',
          f'Испытание: средний запас + опыт {competency} + d20 ({roll}) − 10; итог {score:.1f}. Критический ресурс: {pressure} −12.']
    for p in r['players'].values():
        if p['status']=='excluded': fate='Ушёл в наружный лагерь после голосования. Позднее его имя появилось в журнале обмена; дальнейшая судьба неизвестна.'
        elif p['status']=='left': fate='Покинул группу до закрытия двери. Связь с ним прервалась.'
        elif p['survived']:
            f=next((x for x in ('skill','biography','profession') if x in p['revealed']),None)
            fate='Выжил. '+('Пригодилось: '+p['card'][f]['text']+'.' if f else 'Помогал общими дежурствами.')
        else: fate='Не вернулся из последней экспедиции. Группа сохранила его имя в своём архиве.'
        text.append(p['name']+': '+fate)
    decisions=[x['text'] for x in r['history'] if x['text'].startswith('Решение:')]
    text+=['Решения, изменившие судьбу группы:']+decisions
    if 'radio' in tags or 'chinese' in tags:
        text.append('В 23:14 станция поймала сообщение из Хэйхэ. На противоположном берегу Амура снова появились огни.')
    else:
        text.append('За Амуром видны редкие огни. Их смысл ещё предстоит узнать новой экспедиции.')
    r['epilogue']='\n\n'.join(text)
    record(r,f'Финал: {ending}. Полный эпилог доступен кнопкой.')
    transition(r,Phase.FINISHED,now)

def leave(r,uid,now,content):
    p=r['players'][uid]
    if p['status']!='active': return
    if r['phase']==Phase.LOBBY:
        del r['players'][uid]
        if not r['players']:
            r['phase']=Phase.FINISHED; r['deadline']=None; return
        if r['host']==uid: r['host']=active(r)[0]['id']
        return
    p['status']='left'
    record(r,p['name']+' покидает партию. Его обычный голос отозван.')
    r['votes']={k:v for k,v in r['votes'].items() if k!=uid and v!=uid}
    r['choices'].pop(uid,None)
    r['ready']=[x for x in r['ready'] if x!=uid]
    r['runoff']=[x for x in r['runoff'] if x!=uid]
    if not active(r):
        transition(r,Phase.FINISHED,now); r['epilogue']='Все участники покинули партию. Убежище осталось пустым.'; return
    transfer_host(r)
    if r['phase'] in (Phase.VOTE,Phase.DEFENSE) and exclusions_due(r)==0:
        enter_act(r,now,content); return
    if r['phase']==Phase.REVEAL and r['turn']==uid: next_turn(r,now,content)
    elif r['phase']==Phase.EVENT and len(r['choices'])==len(active(r)): resolve_event(r,now)
    elif r['phase']==Phase.VOTE and (len(active(r))<=r['capacity'] or len(r['votes'])==len(active(r)) or (r['vote_round']==2 and len(r['runoff'])<=1)):
        if r['vote_round']==2 and not r['runoff'] and len(active(r))>r['capacity']:
            begin_vote(r,now)
        else: resolve_vote(r,now,content)
    elif r['phase']==Phase.DEFENSE and len(r['runoff'])<=1:
        if len(active(r))<=r['capacity']: enter_act(r,now,content)
        elif r['runoff']:
            r['vote_round']=2; resolve_vote(r,now,content)
        else: begin_vote(r,now)
    elif r['phase'] in (Phase.STORY,Phase.DISCUSS,Phase.FINAL,Phase.DEFENSE) and all(x in r['ready'] for x in ready_eligible(r)):
        advance(r,now,content)

def ready_eligible(r):
    return candidates(r) if r['phase']==Phase.DEFENSE else [p['id'] for p in active(r)]

def advance(r,now,content):
    phase=r['phase']
    if phase in (Phase.STORY,Phase.FINAL): enter_act(r,now,content)
    elif phase==Phase.REVEAL:
        p=r['players'][r['turn']]
        fields=available_fields(r,p)
        if fields:
            # Never auto-reveal late secrets or relations; explicit player choice only.
            safe=[f for f in fields if f not in ('secret','relation')]
            if safe: reveal(r,p,safe[0])
        r['done'].append(p['id']); next_turn(r,now,content)
    elif phase==Phase.EVENT: resolve_event(r,now)
    elif phase==Phase.DISCUSS:
        if exclusions_due(r)>0: begin_vote(r,now)
        else: enter_act(r,now,content)
    elif phase==Phase.VOTE: resolve_vote(r,now,content)
    elif phase==Phase.DEFENSE: begin_vote(r,now,runoff=True)

def reveal(r,p,field):
    p['revealed'].append(field)
    record(r,f"{p['name']} раскрывает «{FIELD_LABELS[field]}»: {p['card'][field]['text']}")

def apply(r,uid,action,arg,epoch,now,content):
    """Mutate an aggregate inside a repository transaction, or raise GameError."""
    uid=str(uid)
    require(uid in r['players'],'Вы не участник этой комнаты.')
    p=r['players'][uid]
    require(r['phase']!=Phase.FINISHED,'Партия завершена. История и персонаж доступны в меню.')
    if action=='leave': leave(r,uid,now,content); return
    require(p['status']=='active','Вы наблюдатель: раскрытие и голосование недоступны.')
    require(epoch==r['epoch'],'Эта кнопка устарела. Откройте актуальную панель.')
    if action=='timer':
        require(r['phase']==Phase.LOBBY and uid==r['host'],'Настройка доступна организатору до старта.')
        require(arg in TIMERS,'Неизвестный таймер.')
        r['timer']=arg; return
    if action=='start':
        require(uid==r['host'] and r['phase']==Phase.LOBBY,'Только организатор может начать новую партию.')
        require(r['chat_id'] is not None,'Сначала добавьте бота в игровую группу по ссылке.')
        require(4<=len(active(r))<=r['max_players'],'Для старта нужно 4–16 игроков.')
        require(all(p['reachable'] for p in active(r)),'Все игроки должны открыть бота в ЛС и нажать Start.')
        assign(r,content); enter_act(r,now,content); return
    if action=='special':
        require(r['act']>=3 and r['act']<=9,'Особое условие доступно в актах 3–9.')
        require(not p['special_used'],'Особое условие уже использовано.')
        p['special_used']=True
        effect(r,p['special']['effects']); record(r,p['name']+' использует: '+p['special']['text']); return
    if action=='reveal':
        require(r['phase']==Phase.REVEAL and r['turn']==uid,'Сейчас не ваш ход раскрытия.')
        require(arg in available_fields(r,p),'Эта характеристика пока недоступна или уже открыта.')
        reveal(r,p,arg); r['done'].append(uid); next_turn(r,now,content); return
    if action=='choose':
        require(r['phase']==Phase.EVENT,'Сейчас нет сюжетного выбора.')
        require(arg in ('0','1'),'Неизвестный вариант.')
        require(uid not in r['choices'],'Ваш выбор уже принят и не меняется.')
        r['choices'][uid]=int(arg)
        if len(r['choices'])==len(active(r)): resolve_event(r,now)
        return
    if action=='vote':
        require(r['phase']==Phase.VOTE,'Сейчас голосование закрыто.')
        require(arg in candidates(r) and arg!=uid,'Нельзя голосовать за себя или этого кандидата.')
        require(uid not in r['votes'],'Ваш тайный голос уже принят и не меняется.')
        r['votes'][uid]=arg
        if len(r['votes'])==len(active(r)): resolve_vote(r,now,content)
        return
    if action=='ready':
        require(r['phase'] in (Phase.STORY,Phase.DISCUSS,Phase.FINAL,Phase.DEFENSE),'В этой фазе требуется другое действие.')
        require(uid in ready_eligible(r),'Сейчас слово у кандидатов на исключение.')
        require(uid not in r['ready'],'Готовность уже отмечена.')
        r['ready'].append(uid)
        if all(x in r['ready'] for x in ready_eligible(r)): advance(r,now,content)
        return
    raise GameError('Неизвестное действие.')
