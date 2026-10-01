import logging
from aiogram import Router, F
from aiogram.filters import Command, CommandStart, CommandObject
from aiogram.types import Message, CallbackQuery, ErrorEvent, ChatMemberUpdated
from aiogram.exceptions import TelegramBadRequest
from bunker.engine.game import GameError, require
from bunker.keyboards.ui import menu, button, cb
from bunker.services.views import RULES

log=logging.getLogger(__name__)

def make_router(service):
    router=Router()
    repo=service.repo

    def home(uid):
        repo.enqueue(uid,'Бункер: Благовещенск\nСоздайте комнату или откройте ссылку от друга. Для входа по коду: /join КОД.\nВаш Telegram ID: '+str(uid),menu())

    def rooms(uid):
        mine=[r for r in repo.rooms() if str(uid) in r['players']][:20]
        if not mine: home(uid); return
        repo.enqueue(uid,'Ваши комнаты',{'inline_keyboard':[[button(r['code']+' · '+r['phase'],cb(r,'open'))] for r in mine]+[[button('Создать комнату','new')]]})

    @router.message(CommandStart())
    async def start(m:Message,command:CommandObject):
        if not m.from_user: return
        arg=command.args or ''
        if m.chat.type=='private':
            service.register(m.from_user.id,m.from_user.full_name)
            if arg.startswith('j_'):
                service.join(arg[2:].upper(),m.from_user.id,m.from_user.full_name)
            else: home(m.from_user.id)
        elif arg.startswith('b_'):
            service.bind(arg[2:].upper(),m.from_user.id,m.chat.id)
        else:
            repo.enqueue(m.chat.id,'Создайте комнату кнопкой в ЛС или командой /new в этой группе.',
                         {'inline_keyboard':[[button('Открыть бота',url=f'https://t.me/{service.username}')]]})

    @router.message(Command('new'))
    async def new(m:Message):
        if not m.from_user: return
        if m.chat.type=='private': service.register(m.from_user.id,m.from_user.full_name)
        service.create(m.from_user.id,m.from_user.full_name,f'create:{m.chat.id}:{m.message_id}',None if m.chat.type=='private' else m.chat.id)

    @router.message(Command('join'))
    async def join(m:Message,command:CommandObject):
        require(m.chat.type=='private','Для получения персонажа откройте бота в ЛС.')
        require(bool(command.args),'Формат: /join КОД')
        service.join(command.args.strip().upper(),m.from_user.id,m.from_user.full_name)

    @router.message(Command('room','rooms'))
    async def room(m:Message):
        if m.chat.type=='private': rooms(m.from_user.id)
        else:
            matches=[r for r in repo.rooms(live=True) if r['chat_id']==m.chat.id]
            require(bool(matches),'В группе ещё нет активной комнаты. /new создаёт комнату.')
            r=matches[0]; service.membership(r,m.from_user.id); service.read(r['code'],m.from_user.id,'refresh')

    @router.message(Command('help','rules'))
    async def rules(m:Message): repo.enqueue(m.chat.id,RULES)

    @router.message(Command('admin'))
    async def admin(m:Message):
        require(m.chat.type=='private','Админка доступна только в ЛС.')
        service.admin_view(m.from_user.id)

    @router.message(Command('id'))
    async def identity(m:Message): repo.enqueue(m.chat.id,'Ваш Telegram ID: '+str(m.from_user.id))

    @router.callback_query()
    async def callback(q:CallbackQuery):
        # Always stop the client's spinner, including for inaccessible old messages.
        try: await q.answer()
        except TelegramBadRequest: pass
        uid=q.from_user.id
        data=q.data or ''
        try:
            if data=='new':
                require(q.message is not None and q.message.chat.type=='private','Создайте комнату в ЛС.')
                service.register(uid,q.from_user.full_name)
                service.create(uid,q.from_user.full_name,'create-cb:'+q.id)
            elif data=='rooms': rooms(uid)
            elif data=='rules': repo.enqueue(uid,RULES,menu())
            elif data.startswith('admin:'):
                require(q.message is not None and q.message.chat.type=='private','Админка доступна только в ЛС.')
                _,action,arg=data.split(':',2); service.admin(uid,action,arg)
            elif data.startswith('g:'):
                fields=data.split(':',4)
                require(len(fields)==5 and fields[2].isdigit(),'Повреждённая кнопка.')
                _,code,epoch,action,arg=fields
                if action in ('open','card','goal','history','refresh','epilogue','askleave'):
                    service.read(code,uid,action)
                else:
                    require(q.message is not None and q.message.chat.type=='private','Действия с персонажем и голосование выполняются в ЛС.')
                    service.action(code,uid,action,arg,int(epoch),'callback:'+q.id)
            else: raise GameError('Неизвестная кнопка. Откройте /start.')
        except GameError as e:
            # Error details are personal even when the button was in a group.
            repo.enqueue(uid,str(e),menu())

    @router.message(F.migrate_to_chat_id)
    async def migrated(m:Message): service.migrate_group(m.chat.id,m.migrate_to_chat_id)

    @router.message(F.left_chat_member)
    async def left(m:Message): service.group_departure(m.chat.id,m.left_chat_member.id)

    @router.my_chat_member()
    async def bot_membership(update:ChatMemberUpdated):
        if update.chat.type=='private' and update.new_chat_member.status in ('kicked','left'):
            service.disconnected(update.from_user.id)
        elif update.chat.type in ('group','supergroup') and update.new_chat_member.status in ('kicked','left'):
            # Continue personal turns; warn host that the public group must be restored.
            for r in repo.rooms(live=True):
                if r['chat_id']==update.chat.id:
                    repo.enqueue(r['host'],'Бот удалён из игровой группы. Верните его, затем нажмите /room в группе. Личные панели и таймеры продолжают работать.',room=r['code'])

    @router.error()
    async def error(event:ErrorEvent):
        if isinstance(event.exception,GameError):
            m=event.update.message
            if m: repo.enqueue(m.chat.id,str(event.exception))
            return True
        # Do not log Update: private cards, names and Bot API token can be in payloads.
        log.error('Update failed: %s',type(event.exception).__name__)
        return False

    return router
