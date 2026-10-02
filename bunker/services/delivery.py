import asyncio
import json
import logging
import time
from aiogram.exceptions import (TelegramForbiddenError, TelegramBadRequest,
    TelegramRetryAfter, TelegramNetworkError, TelegramServerError, TelegramMigrateToChat)
from aiogram.types import InlineKeyboardMarkup, FSInputFile
from pathlib import Path

ART_DIR=Path(__file__).resolve().parents[1]/'assets'/'catastrophes'

log=logging.getLogger(__name__)

async def deliver_once(bot,service,now=None):
    now=time.time() if now is None else now
    repo=service.repo
    for row in repo.due(now):
        payload=json.loads(row['payload'])
        try:
            photo=payload.get('photo')
            path=ART_DIR/(photo+'.jpg') if photo and photo.startswith('catastrophes_') and photo.removeprefix('catastrophes_').isdigit() else None
            if path and path.is_file():
                await bot.send_photo(row['chat_id'],FSInputFile(path),caption=payload['text'],parse_mode=None)
            else:
                await bot.send_message(row['chat_id'],payload['text'],
                    reply_markup=InlineKeyboardMarkup.model_validate(payload['keyboard']) if payload['keyboard'] else None,
                    parse_mode=None)
        except TelegramRetryAfter as e:
            repo.retry(row['id'],now,e.retry_after+1)
        except TelegramMigrateToChat as e:
            service.migrate_group(row['chat_id'],e.migrate_to_chat_id)
            repo.retry(row['id'],now,1)
        except TelegramForbiddenError:
            repo.dead(row['id'])
            if row['chat_id']>0: service.disconnected(row['chat_id'])
            else: log.warning('Cannot deliver group panel: room=%s',row['room'])
        except TelegramBadRequest:
            # sendMessage is always a fresh panel: no dependence on an old/deleted message.
            repo.dead(row['id'])
            log.error('Telegram rejected outgoing payload: outbox=%s room=%s',row['id'],row['room'])
        except (TelegramNetworkError,TelegramServerError,OSError):
            repo.retry(row['id'],now,min(120,2**min(row['attempts']+1,6)))
        else: repo.complete(row['id'])

async def worker(bot,service):
    while True:
        try:
            service.tick()
            await deliver_once(bot,service)
        except asyncio.CancelledError: raise
        except Exception:
            log.exception('Background worker error; next tick will retry')
        await asyncio.sleep(1.1)
