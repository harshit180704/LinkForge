import logging
import time
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from app.database import SessionLocal
from app.models import ClickEvent, ProcessedClick, ShortURL
from app.redis_client import client

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("click-worker")
STREAM = "url_clicks"
GROUP = "analytics"
CONSUMER = "local-worker"

def process(event_id: str, url_id: int):
    with SessionLocal() as db:
        try:
            db.add(ProcessedClick(event_id=event_id))
            db.add(ClickEvent(event_id=event_id, url_id=url_id))
            db.flush()  # unique event ID makes retries idempotent
            db.execute(update(ShortURL).where(ShortURL.id == url_id).values(
                click_count=ShortURL.click_count + 1
            ))
            db.commit()
        except IntegrityError:
            db.rollback()  # already processed

def run():
    try:
        client.xgroup_create(STREAM, GROUP, id="0", mkstream=True)
    except Exception as exc:
        if "BUSYGROUP" not in str(exc):
            raise
    log.info("Click worker started")
    while True:
        try:
            # Reclaim abandoned pending messages from a crashed consumer.
            next_id = "0-0"
            while True:
                next_id, pending, _ = client.xautoclaim(
                    STREAM, GROUP, CONSUMER, min_idle_time=30000,
                    start_id=next_id, count=100
                )
                for event_id, fields in pending:
                    process(event_id, int(fields["url_id"]))
                    client.xack(STREAM, GROUP, event_id)
                if next_id == "0-0" or not pending:
                    break
            entries = client.xreadgroup(
                GROUP, CONSUMER, {STREAM: ">"}, count=20, block=2000
            )
            for _, messages in entries:
                for event_id, fields in messages:
                    process(event_id, int(fields["url_id"]))
                    client.xack(STREAM, GROUP, event_id)
        except Exception:
            log.exception("Worker error; retrying")
            time.sleep(2)

if __name__ == "__main__":
    run()
