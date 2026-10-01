import secrets
import time
from bunker.engine import game
from bunker.engine.game import GameError, require
from bunker.states import Phase
from bunker.services.views import public_text, private_text, roster_text
from bunker.keyboards.ui import public_keyboard, private_keyboard, button, cb

class GameService:
    def __init__(self,repo,content,username,admins=(),clock=time.time):
        self.repo=repo; self.content=content; self.username=username
        self.admins={int(x) for x in admins}; self.clock=clock

    def get(self,code):
        r=self.repo.get(code)
        require(r is not None,'Комната не найдена. Проверьте код приглашения.')
        return r

    def membership(self,r,uid):
        require(str(uid) in r['players'],'Эта комната вам недоступна. Используйте приглашение.')

    def ensure_free(self,uid,code=None):
        require(not any(r['code']!=code and str(uid) in r['players'] and r['players'][str(uid)]['status']=='active'
                        for r in self.repo.rooms(live=True)),'Вы уже участвуете в другой комнате. Сначала выйдите из неё через «Мои комнаты».')

    def notify(self,r,before=None):
        now=self.clock()
        if r['chat_id']:
            self.repo.enqueue(r['chat_id'],public_text(r,now),public_keyboard(r,self.username),r['code'],'panel')
        if r['chat_id'] and r['phase']==Phase.FINISHED and r['epilogue'] and (before is None or before['phase']!=Phase.FINISHED):
            self.repo.enqueue(r['chat_id'],r['epilogue'],room=r['code'])
        epoch_changed=before is None or r['epoch']!=before['epoch']
        if epoch_changed:
            for p in r['players'].values():
                if p['reachable']:
                    initial=before is not None and before['phase']==Phase.LOBBY and r['act']==1
                    self.repo.enqueue(p['id'],private_text(r,p['id'],full=initial),
                        private_keyboard(r,p['id'],self.username),r['code'],'card' if initial else 'panel')
        elif r['phase']==Phase.LOBBY and r['host'] in r['players']:
            self.send_private(r,r['host'])

    def send_private(self,r,uid,full=False):
        self.membership(r,uid)
        self.repo.enqueue(uid,private_text(r,uid,full),private_keyboard(r,uid,self.username),r['code'],'panel' if not full else 'card')

    def register(self,uid,name):
        with self.repo.transaction():
            self.repo.user(uid,name)
            for r in self.repo.rooms(live=True):
                if str(uid) in r['players']:
                    r['players'][str(uid)]['reachable']=True
                    self.repo.save(r)

    def create(self,uid,name,key,chat_id=None):
        with self.repo.transaction():
            old=self.repo.seen(key)
            if old: return self.get(old[0])
            self.ensure_free(uid)
            if chat_id:
                require(not any(r['chat_id']==chat_id for r in self.repo.rooms(live=True)),'В этой группе уже идёт партия. Откройте /room.')
            code=secrets.token_hex(4).upper()
            while self.repo.get(code): code=secrets.token_hex(4).upper()
            enabled=self.repo.setting('packs',['core','two_rivers'])
            r=game.new_room(code,uid,name,chat_id,self.clock(),secrets.randbits(63),enabled)
            r['players'][str(uid)]['reachable']=self.repo.reachable(uid)
            self.repo.save(r); self.repo.mark(key,code); self.notify(r)
            return r

    def join(self,code,uid,name):
        with self.repo.transaction():
            r=self.get(code); self.ensure_free(uid,code)
            self.repo.user(uid,name)
            game.join(r,uid,name,True)
            self.repo.save(r); self.notify(r)
            self.send_private(r,uid)
            return r

    def bind(self,code,uid,chat_id):
        with self.repo.transaction():
            r=self.get(code)
            require(r['host']==str(uid),'Только создатель комнаты может привязать её к группе.')
            require(r['phase']==Phase.LOBBY,'Привязка доступна до старта.')
            require(r['chat_id'] in (None,chat_id),'Комната уже связана с другой группой.')
            require(not any(x['code']!=code and x['chat_id']==chat_id for x in self.repo.rooms(live=True)),'В этой группе уже есть активная комната.')
            r['chat_id']=chat_id; self.repo.save(r); self.notify(r)

    def action(self,code,uid,action,arg,epoch,key):
        self.tick()
        with self.repo.transaction():
            if self.repo.seen(key): return 'Это действие уже обработано.'
            before=self.get(code); r=self.get(code)
            game.apply(r,uid,action,arg,epoch,self.clock(),self.content)
            self.repo.save(r); self.repo.mark(key)
            # Never publish intermediate ballot information.
            if action not in ('vote','choose','ready') or r['epoch']!=before['epoch']:
                self.notify(r,before)
            if str(uid) in r['players'] and r['players'][str(uid)]['reachable']:
                self.send_private(r,uid)
            return {'vote':'Тайный голос принят.','choose':'Выбор принят.','ready':'Готовность отмечена.'}.get(action,'Готово.')

    def read(self,code,uid,kind):
        r=self.get(code); self.membership(r,uid)
        with self.repo.transaction():
            if kind in ('open','card'):
                self.send_private(r,uid,full=kind=='card')
            elif kind=='goal':
                p=r['players'][str(uid)]
                text=p['goal']['text'] if p['goal'] else 'Цель появится после старта.'
                if r['ending']: text+='\nРезультат: '+('выполнена' if p['goal_success'] else 'не выполнена')
                self.repo.enqueue(uid,text,private_keyboard(r,uid,self.username),code)
            elif kind=='history':
                history='\n\n'.join(f"Акт {x['act']}: {x['text']}" for x in r['history']) or 'Партия ещё не началась.'
                self.repo.enqueue(uid,history+'\n\nОТКРЫТЫЕ КАРТОЧКИ\n'+roster_text(r),private_keyboard(r,uid,self.username),code)
            elif kind=='epilogue':
                require(r['phase']==Phase.FINISHED,'Эпилог появится после окончания партии.')
                self.repo.enqueue(uid,r['epilogue'] or 'Комната закрыта до начала игры.',private_keyboard(r,uid,self.username),code)
            elif kind=='refresh':
                target=r['chat_id'] or uid
                self.repo.enqueue(target,public_text(r,self.clock()),public_keyboard(r,self.username),code,'panel')
            elif kind=='askleave':
                self.repo.enqueue(uid,'Покинуть партию? Вернуться активным игроком после старта нельзя.',
                    {'inline_keyboard':[[button('Да, выйти',cb(r,'leave')),button('Остаться',cb(r,'open'))]]},code)

    def tick(self):
        now=self.clock()
        for room in self.repo.rooms(live=True):
            if room['deadline'] is None or room['deadline']>now: continue
            with self.repo.transaction():
                r=self.get(room['code']); before=self.get(room['code'])
                if r['deadline'] is not None and r['deadline']<=now:
                    # One phase per recovery tick; the next phase gets a fresh deadline.
                    game.advance(r,now,self.content)
                    self.repo.save(r); self.notify(r,before)

    def disconnected(self,uid):
        with self.repo.transaction():
            self.repo.db.execute('UPDATE users SET reachable=0 WHERE id=?',(int(uid),))
            for old in self.repo.rooms(live=True):
                if str(uid) in old['players']:
                    r=self.get(old['code']); r['players'][str(uid)]['reachable']=False
                    if r['phase']!=Phase.LOBBY: game.leave(r,str(uid),self.clock(),self.content)
                    self.repo.save(r); self.notify(r,old)

    def group_departure(self,chat_id,uid):
        for r in self.repo.rooms(live=True):
            if r['chat_id']==chat_id and str(uid) in r['players']:
                self.action(r['code'],uid,'leave','',r['epoch'],f'left:{r["code"]}:{uid}:{r["epoch"]}')

    def migrate_group(self,old_id,new_id):
        with self.repo.transaction():
            for r in self.repo.rooms():
                if r['chat_id']==old_id:
                    r['chat_id']=new_id; self.repo.save(r)
            self.repo.db.execute('UPDATE outbox SET chat_id=? WHERE chat_id=?',(new_id,old_id))

    def require_admin(self,uid): require(int(uid) in self.admins,'Доступ только администратору бота.')

    def admin_view(self,uid):
        self.require_admin(uid)
        rooms=self.repo.rooms(); live=[r for r in rooms if r['phase']!=Phase.FINISHED]
        completed=[r for r in rooms if r['ending']]
        text=f'Администратор\nАктивных комнат: {len(live)}\nАктивных игроков: {sum(len(game.active(r)) for r in live)}\nЗавершённых партий: {len(completed)}\nВсего комнат: {len(rooms)}'
        rows=[]
        for r in live[:30]:
            text+=f"\n{r['code']} · {len(game.active(r))} игроков · акт {r['act']} · {r['phase']}"
            rows.append([button('Завершить '+r['code'],'admin:askend:'+r['code'])])
        enabled=self.repo.setting('packs',['core','two_rivers'])
        for pack in self.content.packs:
            rows.append([button(('✅ ' if pack in enabled else '⬜ ')+pack,'admin:pack:'+pack)])
        rows.append([button('Обновить','admin:show:')])
        self.repo.enqueue(uid,text,{'inline_keyboard':rows})

    def admin(self,uid,action,arg):
        self.require_admin(uid)
        if action=='show': self.admin_view(uid); return
        if action=='askend':
            self.get(arg)
            self.repo.enqueue(uid,'Завершить комнату '+arg+' без игрового финала?',{'inline_keyboard':[[button('Подтвердить','admin:end:'+arg),button('Отмена','admin:show:')]]}); return
        with self.repo.transaction():
            if action=='end':
                r=self.get(arg)
                require(r['phase']!=Phase.FINISHED,'Комната уже завершена.')
                game.record(r,'Комната закрыта администратором.')
                r['epilogue']='Партия остановлена администратором без оценки выживания.'
                game.transition(r,Phase.FINISHED,self.clock()); self.repo.save(r); self.notify(r)
            elif action=='pack':
                require(arg in self.content.packs,'Пакет не найден.')
                require(arg!='core','Основной пакет обязателен; дополнительные можно отключать.')
                enabled=self.repo.setting('packs',['core','two_rivers'])
                if arg in enabled: enabled.remove(arg)
                else: enabled.append(arg)
                self.repo.set_setting('packs',enabled)
            else: raise GameError('Неизвестное административное действие.')
        self.admin_view(uid)
