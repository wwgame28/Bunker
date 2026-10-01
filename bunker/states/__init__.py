from enum import StrEnum

class Phase(StrEnum):
    LOBBY = 'lobby'
    STORY = 'story'
    REVEAL = 'reveal'
    EVENT = 'event'
    DISCUSS = 'discuss'
    VOTE = 'vote'
    DEFENSE = 'defense'
    FINAL = 'final'
    FINISHED = 'finished'

ACTS = ['Последний обычный день', 'Сирены над городом', 'Первое раскрытие',
        'Амур молчит', 'Огни Хэйхэ', 'Первая ночь', 'Раскол',
        'Последнее голосование', 'Дверь закрывается', 'После Бункера']
# Seconds per phase; turn time is individual, not divided by player count.
TIMERS = {'fast': 40, 'standard': 90, 'long': 180, 'off': None}
FIELD_LABELS = dict(profession='Профессия', sex='Пол', age='Возраст', health='Здоровье',
    hobby='Хобби', baggage='Багаж', skill='Навык', biography='Биография',
    personality='Характер', fear='Страх', secret='Секрет', achievement='Достижение',
    morality='Поступок из прошлого', relation='Связь', goal='Тайная цель')
GATES = dict(profession=3, health=3, hobby=3, baggage=3, skill=3, biography=4,
             personality=3, fear=4, achievement=4, morality=5, relation=6, secret=7)
