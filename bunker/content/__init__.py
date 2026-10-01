import json
from pathlib import Path

MINIMUMS = dict(professions=100, biographies=150, health=100, hobbies=100,
                baggage=120, skills=100, secrets=150, goals=50, events=100,
                relations=50, catastrophes=30, bunkers=50, specials=50)
CATEGORIES = dict(profession='professions', health='health', hobby='hobbies',
                  baggage='baggage', skill='skills', biography='biographies',
                  personality='personalities', fear='fears', secret='secrets',
                  achievement='achievements', morality='morality')
RESOURCES = {'water', 'food', 'power', 'medicine', 'morale', 'structure'}
TAGS = {'medical','engineering','radio','chinese','water','food','rescue',
        'navigation','negotiation','security','science','craft','winter'}

class Content:
    def __init__(self, path=None):
        self.path = Path(path or Path(__file__).parent / 'packs')
        self.packs = {p.stem: json.loads(p.read_text()) for p in sorted(self.path.glob('*.json'))}
        self.validate()

    def pool(self, category, enabled=None):
        return [x for k,p in self.packs.items() if enabled is None or k in enabled
                for x in p.get(category, [])]

    def validate(self):
        for cat,n in MINIMUMS.items():
            items = self.pool(cat)
            assert len(items) >= n, f'{cat}: {len(items)} < {n}'
            assert len({x['id'] for x in items}) == len(items), f'duplicate id: {cat}'
            assert len({x['text'] for x in items}) == len(items), f'duplicate text: {cat}'
        for pack in self.packs.values():
            for cat,items in pack.items():
                if cat.startswith('_'): continue
                for x in items:
                    assert set(x.get('tags',[])) <= TAGS
                    assert set(x.get('effects',{})) <= RESOURCES
                    assert isinstance(x['id'],str) and x['id']
                    assert isinstance(x['text'],str) and x['text']
                    assert all(isinstance(v,int) for v in x.get('effects',{}).values())
                    if cat == 'events':
                        assert len(x['options']) == 2
                        assert set(x['needs']) <= TAGS
                        for opt in x['options']:
                            assert set(opt['effects']) <= RESOURCES
                            assert isinstance(opt['text'],str) and opt['text']
                            assert isinstance(opt['check'],bool) and opt['success']
                            if opt['check']:
                                assert set(opt['failure']) <= RESOURCES
                                assert opt['fail']
                        assert x['needs'] and x['clue']
                    if cat == 'catastrophes':
                        assert len(x['stages']) == 4 and all(x['stages'])
                        assert x['pressure'] in RESOURCES
                    if cat == 'relations': assert isinstance(x['mutual'],bool)
                    if cat == 'goals':
                        assert x['kind'] in RESOURCES | {'together','apart','medical','ending'}
                        assert isinstance(x['threshold'],int) and 0<=x['threshold']<=100
                    if cat in ('bunkers','specials'): assert x['effects']
                    if cat == 'specials': assert x['min_act']==3
        return {cat:len(self.pool(cat)) for cat in MINIMUMS}
