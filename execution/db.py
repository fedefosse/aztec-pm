"""Acceso a SQLite para el sistema de gestión de proyectos.

Capa 3 (ejecución determinista) de la arquitectura descrita en CLAUDE.md.
Sin lógica de negocio aquí: solo esquema y acceso a datos. El diagnóstico
(riesgo/prioridad) vive en risk_engine.py, que consume estas funciones.
"""

import json
import sqlite3
from pathlib import Path
from datetime import datetime, timezone

DB_PATH = Path(__file__).parent / "aztec_pm.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    project_code TEXT PRIMARY KEY,
    client_alias TEXT NOT NULL,
    project_name TEXT NOT NULL,
    engagement_type TEXT NOT NULL CHECK(engagement_type IN ('Proyecto','Diagnostico','Mantenimiento o recurrente')),
    owner_alias TEXT,
    status TEXT NOT NULL DEFAULT 'Activo' CHECK(status IN ('Activo','En pausa','Cerrado','Cancelado')),
    target_date TEXT,
    next_step TEXT,
    blockers TEXT,
    business_value REAL,
    currency TEXT DEFAULT 'USD' CHECK(currency IN ('USD','COP')),
    start_date TEXT,
    stage TEXT,
    summary TEXT,
    -- Diagnóstico persistido (no editable a mano): recalculado y grabado por
    -- webapp.py::refresh_diagnosis en cada mutación que pueda afectarlo
    -- (alta/edición de proyecto, alta/cambio/borrado de tarea) y también en
    -- cada carga del dashboard, para que ni el simple paso del tiempo lo
    -- deje desactualizado. Ver directives/gestion_proyectos.md.
    health TEXT CHECK(health IN ('Bloqueado','En riesgo','Sano') OR health IS NULL),
    priority_score INTEGER,
    priority_bucket TEXT,
    priority_breakdown TEXT,
    priority_computed_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tasks (
    task_code TEXT PRIMARY KEY,
    project_code TEXT NOT NULL REFERENCES projects(project_code) ON DELETE CASCADE,
    assignee_alias TEXT,
    priority TEXT NOT NULL DEFAULT 'Media' CHECK(priority IN ('Baja','Media','Alta','Critica')),
    status TEXT NOT NULL DEFAULT 'Por hacer' CHECK(status IN ('Por hacer','En progreso','En revision','Bloqueada','Hecho')),
    due_date TEXT,
    title TEXT NOT NULL,
    detail TEXT,
    dependency TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS project_notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_code TEXT NOT NULL REFERENCES projects(project_code) ON DELETE CASCADE,
    ts TEXT NOT NULL,
    text TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS people (
    member_alias TEXT PRIMARY KEY,
    role TEXT
);
"""


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_schema(conn=None):
    own = conn is None
    conn = conn or get_conn()
    conn.executescript(SCHEMA)
    conn.commit()
    if own:
        conn.close()


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# --- People -----------------------------------------------------------

def upsert_person(conn, member_alias, role):
    conn.execute(
        "INSERT INTO people (member_alias, role) VALUES (?, ?) "
        "ON CONFLICT(member_alias) DO UPDATE SET role=excluded.role",
        (member_alias, role),
    )


def list_people(conn):
    return conn.execute("SELECT * FROM people ORDER BY member_alias").fetchall()


# --- Projects -----------------------------------------------------------

PROJECT_FIELDS = [
    "project_code", "client_alias", "project_name", "engagement_type",
    "owner_alias", "status", "target_date", "next_step", "blockers",
    "business_value", "currency", "start_date", "stage", "summary",
]


def upsert_project(conn, data):
    """Crea o actualiza un proyecto. `data` es un dict con PROJECT_FIELDS."""
    existing = conn.execute(
        "SELECT project_code FROM projects WHERE project_code = ?",
        (data["project_code"],),
    ).fetchone()
    ts = now_iso()
    if existing:
        cols = [f for f in PROJECT_FIELDS if f != "project_code"]
        set_clause = ", ".join(f"{c} = ?" for c in cols)
        values = [data.get(c) for c in cols] + [ts, data["project_code"]]
        conn.execute(
            f"UPDATE projects SET {set_clause}, updated_at = ? WHERE project_code = ?",
            values,
        )
    else:
        cols = PROJECT_FIELDS
        placeholders = ", ".join("?" for _ in cols)
        values = [data.get(c) for c in cols] + [ts, ts]
        conn.execute(
            f"INSERT INTO projects ({', '.join(cols)}, created_at, updated_at) "
            f"VALUES ({placeholders}, ?, ?)",
            values,
        )
    conn.commit()


def get_project(conn, project_code):
    return conn.execute(
        "SELECT * FROM projects WHERE project_code = ?", (project_code,)
    ).fetchone()


def list_projects(conn):
    return conn.execute("SELECT * FROM projects ORDER BY project_code").fetchall()


def update_priority_snapshot(conn, project_code, diag):
    """Graba el diagnóstico calculado (salud + prioridad) en la fila del
    proyecto. `diag` es el dict devuelto por risk_engine.diagnose(). Devuelve
    el timestamp con el que quedó grabado, para poder mostrarlo como
    evidencia de que es un valor real y fresco, no una opinión guardada.
    """
    ts = now_iso()
    conn.execute(
        "UPDATE projects SET health = ?, priority_score = ?, priority_bucket = ?, "
        "priority_breakdown = ?, priority_computed_at = ? WHERE project_code = ?",
        (
            diag["health"],
            diag["priority_score"],
            diag["priority_bucket"],
            json.dumps(diag["priority_breakdown"], ensure_ascii=False),
            ts,
            project_code,
        ),
    )
    conn.commit()
    return ts


def delete_project(conn, project_code):
    conn.execute("DELETE FROM projects WHERE project_code = ?", (project_code,))
    conn.commit()


# --- Tasks -----------------------------------------------------------

TASK_FIELDS = [
    "task_code", "project_code", "assignee_alias", "priority", "status",
    "due_date", "title", "detail", "dependency",
]


def upsert_task(conn, data):
    existing = conn.execute(
        "SELECT task_code FROM tasks WHERE task_code = ?", (data["task_code"],)
    ).fetchone()
    ts = now_iso()
    if existing:
        cols = [f for f in TASK_FIELDS if f != "task_code"]
        set_clause = ", ".join(f"{c} = ?" for c in cols)
        values = [data.get(c) for c in cols] + [ts, data["task_code"]]
        conn.execute(
            f"UPDATE tasks SET {set_clause}, updated_at = ? WHERE task_code = ?",
            values,
        )
    else:
        cols = TASK_FIELDS
        placeholders = ", ".join("?" for _ in cols)
        values = [data.get(c) for c in cols] + [ts, ts]
        conn.execute(
            f"INSERT INTO tasks ({', '.join(cols)}, created_at, updated_at) "
            f"VALUES ({placeholders}, ?, ?)",
            values,
        )
    conn.commit()


def list_tasks(conn, project_code=None):
    if project_code:
        return conn.execute(
            "SELECT * FROM tasks WHERE project_code = ? ORDER BY due_date IS NULL, due_date",
            (project_code,),
        ).fetchall()
    return conn.execute(
        "SELECT * FROM tasks ORDER BY due_date IS NULL, due_date"
    ).fetchall()


def delete_task(conn, task_code):
    conn.execute("DELETE FROM tasks WHERE task_code = ?", (task_code,))
    conn.commit()


# --- Notes -----------------------------------------------------------

def add_note(conn, project_code, text):
    conn.execute(
        "INSERT INTO project_notes (project_code, ts, text) VALUES (?, ?, ?)",
        (project_code, now_iso(), text),
    )
    conn.commit()


def list_notes(conn, project_code):
    return conn.execute(
        "SELECT * FROM project_notes WHERE project_code = ? ORDER BY ts DESC",
        (project_code,),
    ).fetchall()
