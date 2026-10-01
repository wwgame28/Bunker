"""Play a reproducible headless party. No token, Telegram, or external AI required."""
import argparse
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from bunker.content import Content
from bunker.engine import game
from bunker.states import Phase

p=argparse.ArgumentParser()
p.add_argument('--players',type=int,default=8,choices=range(4,17))
p.add_argument('--seed',type=int,default=1827)
p.add_argument('--output')
a=p.parse_args(); content=Content()
r=game.new_room('DEMO1827',1,'Игрок 1',-100,0,a.seed,['core','two_rivers'])
for i in range(1,a.players+1): game.join(r,i,f'Игрок {i}')
r['timer']='fast'; game.apply(r,1,'start','',0,0,content)
steps=0
while r['phase']!=Phase.FINISHED:
    now=r['deadline']; epoch=r['epoch']; phase=r['phase']
    if phase==Phase.REVEAL:
        uid=r['turn']; fields=game.available_fields(r,r['players'][uid])
        # Demo volunteers one late private card to exercise public disclosure.
        field=('secret' if r['act']==7 and 'secret' in fields else fields[0])
        game.apply(r,uid,'reveal',field,epoch,now-1,content)
    elif phase==Phase.EVENT:
        for q in list(game.active(r)): game.apply(r,q['id'],'choose','0',epoch,now-1,content)
    else: game.advance(r,now,content)
    steps+=1
    if steps>300: raise RuntimeError('Simulation did not finish')
text='\n\n'.join(f"Акт {x['act']}: {x['text']}" for x in r['history'])+'\n\n'+r['epilogue']
if a.output: Path(a.output).write_text(text)
else: print(text)
print(f'\nSimulation OK: {a.players} players, {steps} steps, {r["ending"]}')
