"""Vista operativa + CRUD de proyectos/tareas/notas.

Capa 3 (ejecución). La lógica de negocio (riesgo/prioridad) vive en
risk_engine.py; aquí solo hay rutas HTTP y renderizado.

Uso: python3 execution/webapp.py
"""

import sys
from datetime import date
from pathlib import Path

from flask import Flask, redirect, render_template, request, url_for

sys.path.insert(0, str(Path(__file__).parent))
import db  # noqa: E402
import risk_engine  # noqa: E402

app = Flask(__name__)

ENGAGEMENT_TYPES = ["Proyecto", "Diagnostico", "Mantenimiento o recurrente"]
PROJECT_STATUSES = ["Activo", "En pausa", "Cerrado", "Cancelado"]
TASK_PRIORITIES = ["Baja", "Media", "Alta", "Critica"]
TASK_STATUSES = ["Por hacer", "En progreso", "En revision", "Bloqueada", "Hecho"]
CURRENCIES = ["USD", "COP"]


def get_db():
    conn = db.get_conn()
    db.init_schema(conn)
    return conn


def build_row(conn, project, today):
    tasks = db.list_tasks(conn, project["project_code"])
    diag = risk_engine.diagnose(project, tasks, today)
    return {"project": project, "tasks": tasks, "diag": diag}


@app.route("/")
def dashboard():
    conn = get_db()
    today = date.today()
    projects = db.list_projects(conn)
    people = db.list_people(conn)

    rows = [build_row(conn, p, today) for p in projects]

    health_filter = request.args.get("health", "")
    bucket_filter = request.args.get("bucket", "")
    owner_filter = request.args.get("owner", "")
    only_no_next_step = request.args.get("no_next_step", "") == "1"
    only_orphaned = request.args.get("orphaned", "") == "1"
    query = request.args.get("q", "").strip().lower()

    if health_filter:
        rows = [r for r in rows if r["diag"]["health"] == health_filter]
    if bucket_filter:
        rows = [r for r in rows if r["diag"]["priority_bucket"] == bucket_filter]
    if owner_filter:
        rows = [r for r in rows if r["project"]["owner_alias"] == owner_filter]
    if only_no_next_step:
        rows = [r for r in rows if r["diag"]["no_clear_next_step"]]
    if only_orphaned:
        rows = [r for r in rows if r["diag"]["operationally_orphaned"]]
    if query:
        rows = [
            r for r in rows
            if query in (r["project"]["project_name"] or "").lower()
            or query in (r["project"]["client_alias"] or "").lower()
            or query in (r["project"]["project_code"] or "").lower()
        ]

    rows.sort(key=lambda r: r["diag"]["priority_score"], reverse=True)

    all_rows_unfiltered = [build_row(conn, p, today) for p in projects]
    summary = {
        "total": len(all_rows_unfiltered),
        "bloqueados": sum(1 for r in all_rows_unfiltered if r["diag"]["health"] == "Bloqueado"),
        "en_riesgo": sum(1 for r in all_rows_unfiltered if r["diag"]["health"] == "En riesgo"),
        "sin_paso": sum(1 for r in all_rows_unfiltered if r["diag"]["no_clear_next_step"]),
        "huerfanos": sum(1 for r in all_rows_unfiltered if r["diag"]["operationally_orphaned"]),
        "p0": sum(1 for r in all_rows_unfiltered if r["diag"]["priority_bucket"] == "P0 - Critica"),
    }

    conn.close()
    return render_template(
        "dashboard.html",
        rows=rows,
        summary=summary,
        people=people,
        filters={
            "health": health_filter,
            "bucket": bucket_filter,
            "owner": owner_filter,
            "no_next_step": only_no_next_step,
            "orphaned": only_orphaned,
            "q": request.args.get("q", ""),
        },
    )


@app.route("/equipo")
def team_view():
    conn = get_db()
    people = db.list_people(conn)
    all_tasks = db.list_tasks(conn)

    rows = []
    for person in people:
        alias = person["member_alias"]
        my_tasks = [t for t in all_tasks if t["assignee_alias"] == alias]
        open_tasks = [t for t in my_tasks if t["status"] in risk_engine.OPEN_TASK_STATUSES]
        blocked = [t for t in open_tasks if t["status"] == "Bloqueada"]
        critical_high = [t for t in open_tasks if t["priority"] in ("Alta", "Critica")]

        # Efecto dominó: tareas con dependencia asociada flotan al inicio,
        # luego por prioridad y fecha límite.
        priority_rank = {"Critica": 0, "Alta": 1, "Media": 2, "Baja": 3}
        sorted_tasks = sorted(
            open_tasks,
            key=lambda t: (
                0 if (t["dependency"] or "").strip() else 1,
                priority_rank.get(t["priority"], 9),
                t["due_date"] or "9999-99-99",
            ),
        )
        rows.append({
            "person": person,
            "open_count": len(open_tasks),
            "blocked_count": len(blocked),
            "critical_count": len(critical_high),
            "tasks": sorted_tasks,
        })

    max_open = max((r["open_count"] for r in rows), default=0) or 1
    conn.close()
    return render_template("team.html", rows=rows, max_open=max_open)


@app.route("/proyectos/nuevo", methods=["GET", "POST"])
def project_new():
    conn = get_db()
    people = db.list_people(conn)
    if request.method == "POST":
        data = {f: request.form.get(f, "").strip() or None for f in db.PROJECT_FIELDS}
        db.upsert_project(conn, data)
        conn.close()
        return redirect(url_for("project_detail", project_code=data["project_code"]))
    conn.close()
    return render_template(
        "project_form.html", project=None, people=people,
        engagement_types=ENGAGEMENT_TYPES, statuses=PROJECT_STATUSES,
        currencies=CURRENCIES,
    )


@app.route("/proyectos/<project_code>")
def project_detail(project_code):
    conn = get_db()
    today = date.today()
    project = db.get_project(conn, project_code)
    if project is None:
        conn.close()
        return "Proyecto no encontrado", 404
    tasks = db.list_tasks(conn, project_code)
    notes = db.list_notes(conn, project_code)
    diag = risk_engine.diagnose(project, tasks, today)
    conn.close()
    return render_template(
        "project_detail.html", project=project, tasks=tasks, notes=notes,
        diag=diag, task_priorities=TASK_PRIORITIES, task_statuses=TASK_STATUSES,
    )


@app.route("/proyectos/<project_code>/editar", methods=["GET", "POST"])
def project_edit(project_code):
    conn = get_db()
    project = db.get_project(conn, project_code)
    if project is None:
        conn.close()
        return "Proyecto no encontrado", 404
    people = db.list_people(conn)
    if request.method == "POST":
        data = {f: request.form.get(f, "").strip() or None for f in db.PROJECT_FIELDS}
        data["project_code"] = project_code
        db.upsert_project(conn, data)
        conn.close()
        return redirect(url_for("project_detail", project_code=project_code))
    conn.close()
    return render_template(
        "project_form.html", project=project, people=people,
        engagement_types=ENGAGEMENT_TYPES, statuses=PROJECT_STATUSES,
        currencies=CURRENCIES,
    )


@app.route("/proyectos/<project_code>/tareas/nueva", methods=["POST"])
def task_new(project_code):
    conn = get_db()
    existing = db.list_tasks(conn, project_code)
    next_n = len(existing) + 1
    data = {
        "task_code": f"{project_code}-T{next_n:02d}-M",
        "project_code": project_code,
        "assignee_alias": request.form.get("assignee_alias", "").strip() or None,
        "priority": request.form.get("priority", "Media"),
        "status": request.form.get("status", "Por hacer"),
        "due_date": request.form.get("due_date", "").strip() or None,
        "title": request.form.get("title", "").strip(),
        "detail": request.form.get("detail", "").strip(),
        "dependency": "",
    }
    db.upsert_task(conn, data)
    conn.close()
    return redirect(url_for("project_detail", project_code=project_code))


@app.route("/tareas/<task_code>/estado", methods=["POST"])
def task_update_status(task_code):
    conn = get_db()
    project_code = request.form.get("project_code")
    task = next((t for t in db.list_tasks(conn, project_code) if t["task_code"] == task_code), None)
    if task:
        data = {k: task[k] for k in db.TASK_FIELDS}
        data["status"] = request.form.get("status")
        db.upsert_task(conn, data)
    conn.close()
    return redirect(url_for("project_detail", project_code=project_code))


@app.route("/proyectos/<project_code>/notas", methods=["POST"])
def note_new(project_code):
    conn = get_db()
    text = request.form.get("text", "").strip()
    if text:
        db.add_note(conn, project_code, text)
    conn.close()
    return redirect(url_for("project_detail", project_code=project_code))


if __name__ == "__main__":
    get_db().close()
    app.run(debug=True, port=5050)
