import asyncio
import contextlib
import fcntl
import logging
import os
from pathlib import Path
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher
from aiogram.types import BotCommand
from bunker.content import Content
from bunker.database.repository import Repository
from bunker.handlers.telegram import make_router
from bunker.services.game_service import GameService
from bunker.services.delivery import worker

async def run():
    load_dotenv()
    token=os.getenv('BOT_TOKEN','').strip()
    if not token or token.startswith('PUT_'):
        raise SystemExit('Укажите BOT_TOKEN в .env или секретах хостинга. См. README.md.')
    path=os.getenv('DATABASE_PATH','./data/bunker.sqlite3')
    Path(path).parent.mkdir(parents=True,exist_ok=True)
    # A long-polling token and SQLite require one worker. Fail early on local duplicates.
    with open(path+'.lock','w') as lock:
        try: fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError: raise SystemExit('Уже запущен процесс с этой базой данных.')
        repo=Repository(path)
        bot=Bot(token)
        background=None
        try:
            me=await bot.get_me()
            # Preserve pending updates; never drop room actions on deploy.
            await bot.delete_webhook(drop_pending_updates=False)
            admins=[int(x.strip()) for x in os.getenv('ADMIN_IDS','').split(',') if x.strip()]
            service=GameService(repo,Content(),me.username,admins)
            dp=Dispatcher(disable_fsm=True)
            dp.include_router(make_router(service))
            await bot.set_my_commands([BotCommand(command=c,description=d) for c,d in [
                ('start','Главное меню'),('new','Создать комнату'),('room','Панель комнаты'),
                ('join','Войти по коду'),('rules','Правила'),('id','Мой Telegram ID'),('admin','Администратор')]])
            background=asyncio.create_task(worker(bot,service))
            logging.getLogger(__name__).info('Bot started: @%s',me.username)
            # Sequential handling makes an incoming update durable before Telegram ACK.
            await dp.start_polling(bot,handle_as_tasks=False,close_bot_session=False,
                                   allowed_updates=dp.resolve_used_update_types())
        finally:
            if background:
                background.cancel()
                with contextlib.suppress(asyncio.CancelledError): await background
            await bot.session.close(); repo.close()

if __name__=='__main__':
    logging.basicConfig(level=os.getenv('LOG_LEVEL','INFO'),format='%(asctime)s %(levelname)s %(name)s: %(message)s')
    asyncio.run(run())
