import asyncio

from .database import connection
from .rules_engine import ClassificationRule, classify_result


class StoredEvent:
    def __init__(self, row):
        self.state = row["state"]
        self.process_name = row["process_name"]
        self.window_title = row["window_title"]
        self.url_domain = row["url_domain"]
        self.url_path = row["url_path"]


async def run_next_reclassification() -> bool:
    async with connection() as conn:
        job = await conn.fetchrow(
            """UPDATE reclassification_jobs SET status='running',started_at=now()
               WHERE id=(SELECT id FROM reclassification_jobs WHERE status='queued' ORDER BY created_at LIMIT 1 FOR UPDATE SKIP LOCKED)
               RETURNING id,days"""
        )
        if job is None: return False
        try:
            total = await conn.fetchval("SELECT count(*) FROM activity_events WHERE ts_start>=now()-($1*interval '1 day')", job["days"])
            await conn.execute("UPDATE reclassification_jobs SET total_events=$2 WHERE id=$1", job["id"], total)
            rule_rows = await conn.fetch(
                """SELECT r.priority,r.match_field,r.match_type,r.pattern,c.productivity,c.id AS category_id
                   FROM rules r JOIN categories c ON c.id=r.category_id WHERE r.enabled=true ORDER BY r.priority"""
            )
            rules = [ClassificationRule(**dict(row)) for row in rule_rows]
            last_id = 0
            while True:
                rows = await conn.fetch(
                    """SELECT id,state,process_name,window_title,url_domain,url_path FROM activity_events
                       WHERE ts_start>=now()-($1*interval '1 day') AND id>$2 ORDER BY id LIMIT 5000""",
                    job["days"], last_id,
                )
                if not rows: break
                updates = []
                for row in rows:
                    result = classify_result(StoredEvent(row), rules)
                    updates.append((row["id"], result.state, result.category_id))
                await conn.executemany("UPDATE activity_events SET state=$2,category_id=$3 WHERE id=$1", updates)
                last_id = rows[-1]["id"]
                await conn.execute("UPDATE reclassification_jobs SET processed_events=processed_events+$2 WHERE id=$1", job["id"], len(rows))
            await conn.execute("UPDATE reclassification_jobs SET status='completed',finished_at=now() WHERE id=$1", job["id"])
        except Exception as error:
            await conn.execute("UPDATE reclassification_jobs SET status='failed',error=$2,finished_at=now() WHERE id=$1", job["id"], str(error)[:2000])
        return True
    return False


async def reclassification_worker() -> None:
    while True:
        try:
            worked = await run_next_reclassification()
            await asyncio.sleep(0 if worked else 3)
        except asyncio.CancelledError: raise
        except Exception: await asyncio.sleep(5)
