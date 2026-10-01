import pytest
from bunker.content import Content
from bunker.engine import game
from bunker.database.repository import Repository
from bunker.services.game_service import GameService

@pytest.fixture(scope='session')
def content(): return Content()

@pytest.fixture
def room_factory(content):
    def make(n=4,seed=731,timer='off'):
        r=game.new_room('ABCD1234',1,'Игрок 1',-100,0,seed,['core','two_rivers'])
        r['players']['1']['reachable']=True
        for i in range(2,n+1): game.join(r,i,f'Игрок {i}')
        r['timer']=timer
        game.apply(r,1,'start','',r['epoch'],0,content)
        return r
    return make

@pytest.fixture
def service(tmp_path,content):
    repo=Repository(str(tmp_path/'game.db'))
    now=[1000.0]
    s=GameService(repo,content,'test_bunker_bot',[99],clock=lambda:now[0])
    s.test_clock=now
    yield s
    repo.close()
