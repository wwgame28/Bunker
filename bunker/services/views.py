"""Explicit privacy projections. Never serialize the aggregate into a message."""
import math
import time
from bunker.states import ACTS, FIELD_LABELS, Phase
from bunker.engine.game import active, name, public_tags
from bunker.keyboards.ui import TIMER_NAMES

RESOURCE_NAMES=dict(water='Вода',food='Еда',power='Энергия',medicine='Медицина',morale='Мораль',structure='Прочность')
PHASE_NAMES=dict(lobby='Сбор игроков',story='История',reveal='Раскрытие',event='Сюжетный выбор',
                discuss='Обсуждение',vote='Тайное голосование',defense='Право защиты',final='Последние приготовления',finished='Партия завершена')

def public_text(r,now=None):
    now=now if now is not None else time.time()
    parts=[f"БУНКЕР: БЛАГОВЕЩЕНСК · {r['code']}"]
    if r['act']: parts.append(f"Акт {r['act']}/10 · {ACTS[r['act']-1]}")
    parts.append(PHASE_NAMES[r['phase']])
    if r['phase']==Phase.LOBBY:
        parts.extend([f"Организатор: {name(r,r['host'])}",f"Игроки: {len(active(r))}/16 · нужно минимум 4",
                      'Таймер: '+TIMER_NAMES[r['timer']],
                      '\n'.join(('✅ ' if p['reachable'] else '⏳ ')+p['name'] for p in active(r)),
                      'Каждому нужно открыть приглашение в ЛС и нажать Start. Запуск и настройка — в личной панели организатора.'])
        return '\n\n'.join(parts)
    parts.append(f"Активны: {len(active(r))} · мест в укрытии: {r['capacity']}")
    parts.append(' · '.join(f'{RESOURCE_NAMES[k]} {v}' for k,v in r['resources'].items()))
    parts.append('Укрытие: '+', '.join(x['text'] for x in r['features']))
    if r['deadline']:
        parts.append(f"Осталось около {max(0,math.ceil(r['deadline']-now))} с на момент обновления. Кнопка «Обновить панель» уточнит время.")
    elif r['phase']!=Phase.FINISHED:
        parts.append('Без таймера: каждый завершает свой ход кнопкой. В обсуждении требуется готовность всех активных.')
    if r['phase']==Phase.REVEAL:
        parts.append(f"Ход: {name(r,r['turn'])}. Откройте одну доступную характеристику в ЛС.")
    if r['phase']==Phase.EVENT:
        e=r['event']; parts.append('Сцена: '+e['text'])
        parts.extend(f"{i+1}. {o['text']}" for i,o in enumerate(e['options']))
        parts.append('Каждый выбирает в ЛС. Большинство определит решение; при равенстве — вариант 2.')
        if set(e['needs']) & public_tags(r): parts.append('Дополнительная информация: '+e['clue'])
        parts.append('Вариант 1: d6 +2 за каждого подходящего участника (максимум +3), успех от 5. Учитываются только раскрытые навыки. Вариант 2 — без проверки.')
    if r['phase']==Phase.VOTE:
        parts.append('Тайное голосование в ЛС. Один неизменяемый голос, за себя нельзя. Итоги появятся после закрытия.')
    if r['phase']==Phase.DEFENSE:
        parts.append('Защищаются: '+', '.join(name(r,x) for x in r['runoff'])+'. Объясните группе свою ценность и нажмите «Защита закончена» в ЛС.')
    if r['phase'] in (Phase.STORY,Phase.DISCUSS,Phase.FINAL):
        parts.append('Обсудите ситуацию в группе. После обсуждения каждый нажимает «Готов продолжить» в ЛС.')
    parts.append('Последние события:\n'+'\n'.join(x['text'] for x in r['history'][-4:]))
    roster=[]
    for p in r['players'].values():
        known=[FIELD_LABELS[f]+': '+p['card'][f]['text'] for f in p['revealed'] if f not in ('age','sex')]
        roster.append(p['name']+' ['+{'active':'в игре','left':'ушёл','excluded':'исключён'}[p['status']]+']'+
                      (' — '+'; '.join(known) if known else ' — пока без раскрытых характеристик'))
    # Roster is provided in a separate read-only view to keep mobile phase panels short.
    return '\n\n'.join(parts)

def roster_text(r):
    return '\n\n'.join(p['name']+' — '+p['status']+'\n'+ '\n'.join(FIELD_LABELS[f]+': '+p['card'][f]['text'] for f in p['revealed']) for p in r['players'].values())

def private_text(r,uid,full=False):
    p=r['players'][str(uid)]
    parts=[f"Личная панель · {r['code']} · {p['name']}", PHASE_NAMES[r['phase']]]
    if not p['card']:
        return '\n\n'.join(parts+['Персонаж появится после старта. Приглашение: код '+r['code'], 'Выберите действие кнопкой.'])
    if full:
        parts.extend(('👁 ' if f in p['revealed'] else '🔒 ')+FIELD_LABELS[f]+': '+v['text'] for f,v in p['card'].items())
        parts.append('🔒 Тайная цель: '+p['goal']['text'])
        parts.append('🔒 Особое условие: '+p['special']['text']+(' (использовано)' if p['special_used'] else ''))
        parts.append('👁 — уже известно группе; 🔒 — видите только вы. Биография доступна для раскрытия с акта 4, связь с 6, секрет с 7. Цель автоматически группе не раскрывается.')
    else:
        parts.append('Сведения о персонаже доступны отдельной кнопкой. В общей группе публикуются только ваши раскрытия.')
        if r['phase']==Phase.EVENT: parts.append(r['event']['text'])
        if r['phase']==Phase.REVEAL: parts.append('Сейчас ход: '+name(r,r['turn']))
        if str(uid) in r['votes'] and r['phase']==Phase.VOTE: parts.append('Ваш тайный голос принят.')
        if str(uid) in r['choices'] and r['phase']==Phase.EVENT: parts.append('Ваш сюжетный выбор принят.')
    if r['phase']==Phase.FINISHED and r['ending']:
        parts.append('Ваша скрытая цель: '+('выполнена' if p['goal_success'] else 'не выполнена'))
    return '\n\n'.join(parts)

def chunks(text,limit=3500):
    """Bound Telegram payload by UTF-16 code units, including emoji names."""
    out=[]; current=''; units=0
    for c in text:
        n=2 if ord(c)>0xffff else 1
        if units+n>limit: out.append(current); current=''; units=0
        current+=c; units+=n
    if current: out.append(current)
    return out or ['—']

RULES='''БУНКЕР: БЛАГОВЕЩЕНСК
4–16 игроков, 10 актов. Внутрь попадёт примерно половина.

1. Создайте комнату и добавьте бота в группу по кнопке. Пригласите друзей личной ссылкой. Каждый обязан нажать Start в ЛС бота.
2. Организатор выбирает таймер и запускает партию. Персонаж, его цель и односторонние связи приходят лично.
3. В актах 3–8 каждый по очереди открывает одну характеристику. Пол и возраст открыты с начала. Секреты и отношения открываются только добровольно в поздних актах.
4. После раскрытий — сцена и выбор группы. Раскрытый опыт влияет на проверку d6. Тайные способности бонуса не дают.
5. Обсудите ценность персонажей. Счётчик времени обновляется по кнопке. «Готов продолжить» завершает обсуждение, когда готовы все.
6. Голосование тайное, один голос, без изменения, только активные игроки. При ничьей — защита и повтор. Повторная ничья решается жребием. Не ответивший до таймера воздерживается.
7. Исключённые остаются наблюдателями и не голосуют. Выход игрока освобождает плановое место; организатор сменяется автоматически.
8. Особое условие можно применить один раз в актах 3–9. В финале учитываются ресурсы, раскрытые знания, давление катастрофы и бросок d20. Цель — личное дополнительное достижение, она не меняет правила.

Обсуждение проходит текстом, голосом или лично. «Без таймера» требует участия всех: при уходе используйте кнопку выхода. Бот не оценивает убедительность речи. Все катастрофы, адресные истории и персонажи вымышлены. Карточки здоровья не являются медицинскими советами и не дают автоматического штрафа к ценности человека.'''
