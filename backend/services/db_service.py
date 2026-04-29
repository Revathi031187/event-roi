"""
SQLite persistence for saved reports.
All operations are async via aiosqlite.
"""
import json
import os
import aiosqlite
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "reports.db"


async def init_db() -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS reports (
                id          TEXT PRIMARY KEY,
                event_name  TEXT NOT NULL,
                created_at  TEXT NOT NULL,
                report_text TEXT,
                outline_json TEXT,
                ppt_filename TEXT,
                pdf_filename TEXT,
                stats_json  TEXT
            )
        """)
        await db.commit()


async def save_report(
    job_id: str,
    event_name: str,
    report_text: str,
    outline: dict,
    stats: dict,
    ppt_filename: str = None,
    pdf_filename: str = None,
) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT OR REPLACE INTO reports
                (id, event_name, created_at, report_text, outline_json,
                 ppt_filename, pdf_filename, stats_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job_id,
                event_name,
                datetime.utcnow().isoformat(),
                report_text,
                json.dumps(outline),
                ppt_filename,
                pdf_filename,
                json.dumps(stats),
            ),
        )
        await db.commit()


async def update_filenames(
    job_id: str,
    ppt_filename: str = None,
    pdf_filename: str = None,
) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        if ppt_filename:
            await db.execute(
                "UPDATE reports SET ppt_filename=? WHERE id=?",
                (ppt_filename, job_id),
            )
        if pdf_filename:
            await db.execute(
                "UPDATE reports SET pdf_filename=? WHERE id=?",
                (pdf_filename, job_id),
            )
        await db.commit()


async def list_reports(limit: int = 20) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """
            SELECT id, event_name, created_at, ppt_filename, pdf_filename, stats_json
            FROM reports
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (limit,),
        ) as cursor:
            rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def get_report(report_id: str) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM reports WHERE id=?", (report_id,)
        ) as cursor:
            row = await cursor.fetchone()
    if not row:
        return None
    data = dict(row)
    if data.get("outline_json"):
        data["outline"] = json.loads(data["outline_json"])
    if data.get("stats_json"):
        data["stats"] = json.loads(data["stats_json"])
    return data


async def delete_report(report_id: str) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "DELETE FROM reports WHERE id=?", (report_id,)
        )
        await db.commit()
        return cursor.rowcount > 0
