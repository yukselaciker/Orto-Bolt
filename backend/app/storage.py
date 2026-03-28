from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterator


DB_PATH = Path(__file__).resolve().parent.parent / "data" / "selcukbolt.sqlite3"


def init_storage() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_PATH) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS patients (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                patient_code TEXT,
                notes TEXT,
                created_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                patient_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                analysis_mode TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(patient_id) REFERENCES patients(id)
            )
            """
        )
        connection.commit()


@contextmanager
def get_connection() -> Iterator[sqlite3.Connection]:
    init_storage()
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    try:
        yield connection
        connection.commit()
    finally:
        connection.close()


def list_patients(search: str = "") -> list[dict]:
    query = "SELECT id, name, patient_code, notes, created_at FROM patients"
    params: tuple = ()
    if search.strip():
        query += " WHERE lower(name) LIKE ? OR lower(coalesce(patient_code, '')) LIKE ?"
        needle = f"%{search.strip().lower()}%"
        params = (needle, needle)
    query += " ORDER BY datetime(created_at) DESC"

    with get_connection() as connection:
        rows = connection.execute(query, params).fetchall()
    return [dict(row) for row in rows]


def create_patient(*, name: str, patient_code: str = "", notes: str = "") -> dict:
    timestamp = datetime.now().isoformat(timespec="seconds")
    with get_connection() as connection:
        cursor = connection.execute(
            """
            INSERT INTO patients (name, patient_code, notes, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (name.strip(), patient_code.strip(), notes.strip(), timestamp),
        )
        patient_id = cursor.lastrowid
        row = connection.execute(
            "SELECT id, name, patient_code, notes, created_at FROM patients WHERE id = ?",
            (patient_id,),
        ).fetchone()
    return dict(row) if row else {}


def list_records(patient_id: int | None = None, search: str = "") -> list[dict]:
    query = """
        SELECT
            r.id,
            r.patient_id,
            p.name AS patient_name,
            p.patient_code,
            r.title,
            r.analysis_mode,
            r.payload_json,
            r.created_at,
            r.updated_at
        FROM records r
        JOIN patients p ON p.id = r.patient_id
    """
    params: tuple = ()
    conditions: list[str] = []
    mutable_params: list = []
    if patient_id is not None:
        conditions.append("r.patient_id = ?")
        mutable_params.append(patient_id)
    if search.strip():
        conditions.append("(lower(r.title) LIKE ? OR lower(p.name) LIKE ?)")
        needle = f"%{search.strip().lower()}%"
        mutable_params.extend([needle, needle])
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    params = tuple(mutable_params)
    query += " ORDER BY datetime(r.updated_at) DESC"

    with get_connection() as connection:
        rows = connection.execute(query, params).fetchall()

    result: list[dict] = []
    for row in rows:
        item = dict(row)
        item["payload"] = json.loads(item.pop("payload_json"))
        result.append(item)
    return result


def create_record(*, patient_id: int, title: str, analysis_mode: str, payload: dict) -> dict:
    timestamp = datetime.now().isoformat(timespec="seconds")
    with get_connection() as connection:
        cursor = connection.execute(
            """
            INSERT INTO records (patient_id, title, analysis_mode, payload_json, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                patient_id,
                title.strip(),
                analysis_mode,
                json.dumps(payload, ensure_ascii=False),
                timestamp,
                timestamp,
            ),
        )
        record_id = cursor.lastrowid
    return get_record(record_id)


def update_record(*, record_id: int, title: str, analysis_mode: str, payload: dict) -> dict:
    timestamp = datetime.now().isoformat(timespec="seconds")
    with get_connection() as connection:
        connection.execute(
            """
            UPDATE records
            SET title = ?, analysis_mode = ?, payload_json = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                title.strip(),
                analysis_mode,
                json.dumps(payload, ensure_ascii=False),
                timestamp,
                record_id,
            ),
        )
    return get_record(record_id)


def get_record(record_id: int) -> dict:
    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT
                r.id,
                r.patient_id,
                p.name AS patient_name,
                p.patient_code,
                r.title,
                r.analysis_mode,
                r.payload_json,
                r.created_at,
                r.updated_at
            FROM records r
            JOIN patients p ON p.id = r.patient_id
            WHERE r.id = ?
            """,
            (record_id,),
        ).fetchone()
    if row is None:
        raise KeyError(record_id)
    item = dict(row)
    item["payload"] = json.loads(item.pop("payload_json"))
    return item


def delete_record(record_id: int) -> bool:
    with get_connection() as connection:
        cursor = connection.execute("DELETE FROM records WHERE id = ?", (record_id,))
    return cursor.rowcount > 0
