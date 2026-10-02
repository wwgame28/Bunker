import json
from unittest.mock import AsyncMock
import pytest
from test_persistence import started
from bunker.services.delivery import deliver_once, ART_DIR


def test_start_queues_matching_art_once(service):
    r=started(service)
    rows=service.repo.db.execute("SELECT payload FROM outbox WHERE json_extract(payload,'$.kind')='catastrophe'").fetchall()
    assert len(rows)==1
    payload=json.loads(rows[0][0])
    assert payload['photo']==r['catastrophe']['id']
    assert r['catastrophe']['stages'][0] in payload['text']
    service.action(r['code'],1,'start','',r['epoch'],'start')
    assert service.repo.db.execute("SELECT count(*) FROM outbox WHERE json_extract(payload,'$.kind')='catastrophe'").fetchone()[0]==1


@pytest.mark.asyncio
async def test_photo_delivery(service,tmp_path,monkeypatch):
    import bunker.services.delivery as delivery
    monkeypatch.setattr(delivery,'ART_DIR',tmp_path)
    (tmp_path/'catastrophes_001.jpg').write_bytes(b'image')
    service.repo.enqueue(-100,'Disaster',photo='catastrophes_001')
    bot=AsyncMock()
    await deliver_once(bot,service,100)
    bot.send_photo.assert_awaited_once()
    bot.send_message.assert_not_awaited()
    assert not service.repo.due(100)


@pytest.mark.asyncio
async def test_missing_art_falls_back(service):
    service.repo.enqueue(-100,'Disaster',photo='catastrophes_999')
    bot=AsyncMock()
    await deliver_once(bot,service,100)
    bot.send_message.assert_awaited_once()
    bot.send_photo.assert_not_awaited()


def test_all_catastrophes_have_art(content):
    for c in content.pool('catastrophes'):
        assert (ART_DIR/(c['id']+'.jpg')).is_file(), c['id']
