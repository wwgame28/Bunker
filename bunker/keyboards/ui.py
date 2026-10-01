from urllib.parse import quote
from bunker.states import Phase, TIMERS, FIELD_LABELS
from bunker.engine.game import active, available_fields, candidates, ready_eligible

TIMER_NAMES={'fast':'Быстро · 40 с', 'standard':'Обычно · 90 с','long':'Долго · 180 с','off':'Без таймера'}

def button(text, data=None, url=None):
    return {'text':text, **({'callback_data':data} if data else {'url':url})}

def cb(r,action,arg=''):
    return f"g:{r['code']}:{r['epoch']}:{action}:{arg}"

def menu():
    return {'inline_keyboard':[[button('Создать комнату','new')],[button('Мои комнаты','rooms')],[button('Правила','rules')]]}

def public_keyboard(r,username):
    rows=[[button('Мой персонаж / действие',cb(r,'open'))],
          [button('История партии',cb(r,'history')),button('Обновить панель',cb(r,'refresh'))]]
    if r['phase']==Phase.LOBBY:
        rows.insert(0,[button('Присоединиться в ЛС',url=f"https://t.me/{username}?start=j_{r['code']}")])
    if r['phase']==Phase.FINISHED: rows.insert(0,[button('Эпилог',cb(r,'epilogue'))])
    return {'inline_keyboard':rows}

def private_keyboard(r,uid,username):
    uid=str(uid); p=r['players'][uid]; rows=[]
    if r['phase']==Phase.LOBBY:
        invite=f"https://t.me/{username}?start=j_{r['code']}"
        rows.append([button('Пригласить друзей',url='https://t.me/share/url?url='+quote(invite,safe='')+'&text='+quote('Бункер: Благовещенск. Заходи в нашу комнату!',safe=''))])
    if p['status']=='active':
        if r['phase']==Phase.LOBBY and uid==r['host']:
            rows.extend([[button(TIMER_NAMES[k],cb(r,'timer',k))] for k in TIMERS])
            rows.append([button('Запустить партию',cb(r,'start'))])
            if not r['chat_id']:
                rows.append([button('Добавить в игровую группу',url=f"https://t.me/{username}?startgroup=b_{r['code']}")])
        elif r['phase']==Phase.REVEAL and r['turn']==uid:
            rows.extend([[button('Открыть: '+FIELD_LABELS[f],cb(r,'reveal',f))] for f in available_fields(r,p)])
        elif r['phase']==Phase.EVENT and uid not in r['choices']:
            rows.extend([[button(f'{i+1}. '+o['text'],cb(r,'choose',str(i))) ] for i,o in enumerate(r['event']['options'])])
        elif r['phase']==Phase.VOTE and uid not in r['votes']:
            rows.extend([[button('Исключить: '+r['players'][x]['name'],cb(r,'vote',x))] for x in candidates(r) if x!=uid])
        elif r['phase'] in (Phase.STORY,Phase.DISCUSS,Phase.FINAL,Phase.DEFENSE) and uid in ready_eligible(r) and uid not in r['ready']:
            rows.append([button('Защита закончена' if r['phase']==Phase.DEFENSE else 'Готов продолжить',cb(r,'ready'))])
        if 3<=r['act']<=9 and not p['special_used'] and r['phase']!=Phase.FINISHED:
            rows.append([button('Использовать особое условие',cb(r,'special'))])
    rows.extend([[button('Персонаж',cb(r,'card')),button('Тайная цель',cb(r,'goal'))],
                 [button('Обновить мои действия',cb(r,'open')),button('История',cb(r,'history'))]])
    if r['phase']==Phase.FINISHED: rows.append([button('Эпилог',cb(r,'epilogue'))])
    else: rows.append([button('Покинуть партию',cb(r,'askleave'))])
    return {'inline_keyboard':rows}
