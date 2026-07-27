"""Vista operativa + CRUD de proyectos/tareas/notas.

Capa 3 (ejecución). La lógica de negocio (riesgo/prioridad) vive en
risk_engine.py; aquí solo hay rutas HTTP y renderizado.

Uso: python3 execution/webapp.py
"""

import os
import re
import sys
from datetime import date
from pathlib import Path

from flask import Flask, abort, redirect, render_template, request, url_for

sys.path.insert(0, str(Path(__file__).parent))
import db  # noqa: E402
import risk_engine  # noqa: E402

app = Flask(__name__)

ENGAGEMENT_TYPES = ["Proyecto", "Diagnostico", "Mantenimiento o recurrente"]
PROJECT_STATUSES = ["Activo", "En pausa", "Cerrado", "Cancelado"]
TASK_PRIORITIES = ["Baja", "Media", "Alta", "Critica"]
TASK_STATUSES = ["Por hacer", "En progreso", "En revision", "Bloqueada", "Hecho"]
CURRENCIES = ["USD", "COP"]

PROJECT_CODE_RE = re.compile(r"^[A-Za-z0-9_-]+$")


@app.template_global()
def filter_link(endpoint, current, **overrides):
    """Arma una URL que COMBINA los filtros ya activos (`current`, el dict
    de filtros de la ruta) con los cambios pedidos (`overrides`) — nunca los
    reemplaza. `overrides[k] = None` quita ese filtro (toggle); cualquier
    otro valor lo setea. Sin esto, cada link de una tarjeta KPI pisaba el
    resto de filtros activos en vez de sumarse (ej. click en "Bloqueados"
    con un responsable ya filtrado hacía perder el filtro de responsable).
    """
    params = {k: v for k, v in current.items() if v}
    for key, value in overrides.items():
        if value is None:
            params.pop(key, None)
        else:
            params[key] = value
    return url_for(endpoint, **params)


def validate_project_form(data, conn, is_new):
    """Valida los campos de un formulario de proyecto ya recortado (strip).

    Devuelve (data, errores). `data` puede volver con business_value
    convertido a str numérico limpio si era válido.
    """
    errors = []

    code = data.get("project_code")
    if not code or not PROJECT_CODE_RE.match(code):
        errors.append(
            "El código de proyecto es obligatorio y solo puede tener letras, "
            "números, guiones y guiones bajos (sin espacios ni '/')."
        )
    elif is_new and db.get_project(conn, code) is not None:
        errors.append(
            f"Ya existe un proyecto con el código '{code}' — usa Editar en su lugar."
        )

    if data.get("engagement_type") not in ENGAGEMENT_TYPES:
        errors.append("Tipo de compromiso inválido.")
    if data.get("status") not in PROJECT_STATUSES:
        errors.append("Estado inválido.")
    if data.get("currency") not in CURRENCIES:
        errors.append("Moneda inválida.")

    if data.get("business_value") is not None:
        parsed = risk_engine.parse_float(data["business_value"])
        if parsed is None:
            errors.append("El valor de negocio debe ser un número.")
        else:
            data["business_value"] = str(parsed)

    return data, errors


def get_db():
    conn = db.get_conn()
    db.init_schema(conn)
    return conn


def refresh_diagnosis(conn, project, tasks, today):
    """Calcula el diagnóstico (salud + prioridad) y lo GRABA en la fila del
    proyecto — no es un valor de solo lectura. Se llama en cada mutación que
    pueda afectarlo (alta/edición de proyecto, alta/cambio/borrado de tarea)
    y también en cada carga del dashboard, para que ni el paso del tiempo
    (una fecha límite que se vence) lo deje desactualizado.
    """
    diag = risk_engine.diagnose(project, tasks, today)
    diag["computed_at"] = db.update_priority_snapshot(conn, project["project_code"], diag)
    return diag


def refresh_diagnosis_for(conn, project_code, today=None):
    """Atajo: releer proyecto+tareas actuales y refrescar su diagnóstico."""
    today = today or date.today()
    project = db.get_project(conn, project_code)
    if project is None:
        return None
    tasks = db.list_tasks(conn, project_code)
    return refresh_diagnosis(conn, project, tasks, today)


def build_row(conn, project, today):
    tasks = db.list_tasks(conn, project["project_code"])
    diag = refresh_diagnosis(conn, project, tasks, today)
    return {"project": project, "tasks": tasks, "diag": diag}


def read_filters(args):
    """Filtros compartidos por / (ejecutivo) y /proyectos (tabla). `q`
    (búsqueda de texto) se maneja aparte, solo en /proyectos — no es un
    facet de tarjeta, es una caja de búsqueda."""
    return {
        "health": args.get("health", ""),
        "bucket": args.get("bucket", ""),
        "owner": args.get("owner", ""),
        "engagement_type": args.get("engagement_type", ""),
        "no_next_step": "1" if args.get("no_next_step", "") == "1" else "",
        "orphaned": "1" if args.get("orphaned", "") == "1" else "",
    }


def apply_filters(rows, filters, exclude=()):
    """Filtra `rows` con todos los filtros de `filters`, salvo las claves en
    `exclude`. Con `exclude` vacío es el filtrado normal (todo combinado,
    AND). Con una clave excluida sirve para conteos "facetados": cuántas
    filas habría SI se sumara ese filtro a los demás ya activos — lo que
    debe mostrar cada tarjeta KPI, no un total global fijo que ignora el
    resto de la selección.
    """
    if filters.get("health") and "health" not in exclude:
        rows = [r for r in rows if r["diag"]["health"] == filters["health"]]
    if filters.get("bucket") and "bucket" not in exclude:
        rows = [r for r in rows if r["diag"]["priority_bucket"] == filters["bucket"]]
    if filters.get("owner") and "owner" not in exclude:
        rows = [r for r in rows if r["project"]["owner_alias"] == filters["owner"]]
    if filters.get("engagement_type") and "engagement_type" not in exclude:
        rows = [r for r in rows if r["project"]["engagement_type"] == filters["engagement_type"]]
    if filters.get("no_next_step") and "no_next_step" not in exclude:
        rows = [r for r in rows if r["diag"]["no_clear_next_step"]]
    if filters.get("orphaned") and "orphaned" not in exclude:
        rows = [r for r in rows if r["diag"]["operationally_orphaned"]]
    return rows


def faceted_summary(all_rows, filters):
    """Conteos de la franja KPI. Cada número respeta el resto de filtros ya
    activos pero no el suyo propio (`exclude`) — así "Bloqueados" con un
    responsable ya filtrado muestra los bloqueados DE ESE responsable, no
    el total global del portafolio."""
    return {
        "total": len(apply_filters(all_rows, filters)),
        "bloqueados": sum(1 for r in apply_filters(all_rows, filters, exclude=("health",)) if r["diag"]["health"] == "Bloqueado"),
        "en_riesgo": sum(1 for r in apply_filters(all_rows, filters, exclude=("health",)) if r["diag"]["health"] == "En riesgo"),
        "sin_paso": sum(1 for r in apply_filters(all_rows, filters, exclude=("no_next_step",)) if r["diag"]["no_clear_next_step"]),
        "huerfanos": sum(1 for r in apply_filters(all_rows, filters, exclude=("orphaned",)) if r["diag"]["operationally_orphaned"]),
        "p0": sum(1 for r in apply_filters(all_rows, filters, exclude=("bucket",)) if r["diag"]["priority_bucket"] == "P0 - Critica"),
    }


@app.route("/")
def dashboard():
    """Dashboard ejecutivo — carga principal de la app. Todo lo que se ve
    reacciona a los mismos filtros combinados (health/bucket/owner/
    engagement_type/no_next_step/orphaned); ver apply_filters/faceted_summary.
    """
    conn = get_db()
    today = date.today()
    projects = db.list_projects(conn)
    people = db.list_people(conn)
    all_tasks = db.list_tasks(conn)

    all_rows = [build_row(conn, p, today) for p in projects]
    filters = read_filters(request.args)
    rows = apply_filters(all_rows, filters)

    summary = faceted_summary(all_rows, filters)

    health_scope = apply_filters(all_rows, filters, exclude=("health",))
    health_dist = risk_engine.health_distribution([r["diag"]["health"] for r in health_scope])

    bucket_scope = apply_filters(all_rows, filters, exclude=("bucket",))
    bucket_dist = risk_engine.priority_distribution([r["diag"]["priority_bucket"] for r in bucket_scope])

    engagement_scope = apply_filters(all_rows, filters, exclude=("engagement_type",))
    engagement_dist = risk_engine.engagement_distribution([r["project"]["engagement_type"] for r in engagement_scope])

    top_risk = sorted(rows, key=lambda r: r["diag"]["priority_score"], reverse=True)[:8]

    filtered_codes = {r["project"]["project_code"] for r in rows}
    filtered_tasks = [t for t in all_tasks if t["project_code"] in filtered_codes]
    filtered_projects = [r["project"] for r in rows]

    scoped_people = [p for p in people if p["member_alias"] == filters["owner"]] if filters["owner"] else people
    workload_rows, blocking_map = risk_engine.workload_by_person(scoped_people, filtered_tasks)
    max_open = max((r["open_count"] for r in workload_rows), default=0) or 1

    hygiene_stats = risk_engine.hygiene_stats_by_person(scoped_people, filtered_projects, filtered_tasks, today)

    task_by_code = {t["task_code"]: t for t in filtered_tasks}
    blocking_ranked = sorted(blocking_map.items(), key=lambda kv: len(kv[1]), reverse=True)
    top_blockers = [
        {"task": task_by_code[code], "blocks": titles}
        for code, titles in blocking_ranked if code in task_by_code
    ][:6]

    conn.close()
    return render_template(
        "dashboard.html",
        summary=summary,
        health_dist=health_dist,
        health_total=sum(health_dist.values()) or 1,
        bucket_dist=bucket_dist,
        bucket_total=sum(bucket_dist.values()) or 1,
        engagement_dist=engagement_dist,
        engagement_total=sum(engagement_dist.values()) or 1,
        top_risk=top_risk,
        workload_rows=workload_rows,
        max_open=max_open,
        hygiene_stats=hygiene_stats,
        top_blockers=top_blockers,
        total_projects=len(all_rows),
        matched_count=len(rows),
        people=people,
        filters=filters,
    )


@app.route("/proyectos")
def operational_view():
    conn = get_db()
    today = date.today()
    projects = db.list_projects(conn)
    people = db.list_people(conn)

    all_rows = [build_row(conn, p, today) for p in projects]
    filters = read_filters(request.args)
    filters["q"] = request.args.get("q", "").strip()

    rows = apply_filters(all_rows, filters)
    if filters["q"]:
        q = filters["q"].lower()
        rows = [
            r for r in rows
            if q in (r["project"]["project_name"] or "").lower()
            or q in (r["project"]["client_alias"] or "").lower()
            or q in (r["project"]["project_code"] or "").lower()
        ]

    rows.sort(key=lambda r: r["diag"]["priority_score"], reverse=True)

    summary = faceted_summary(all_rows, filters)

    conn.close()
    return render_template(
        "operational_view.html",
        rows=rows,
        summary=summary,
        people=people,
        engagement_types=ENGAGEMENT_TYPES,
        filters=filters,
    )


@app.route("/equipo")
def team_view():
    """Layout sidebar + detalle: la lista de personas (con su carga a
    simple vista, para comparar entre operadores sin abrir a cada uno) va
    a la izquierda; el flujo completo de la persona elegida va a la
    derecha. Sin selección explícita, se abre por defecto quien tiene más
    carga — es quien más probablemente hay que revisar primero.
    """
    conn = get_db()
    people = db.list_people(conn)
    all_tasks = db.list_tasks(conn)

    sidebar_rows, blocking_map = risk_engine.workload_by_person(people, all_tasks)
    max_open = max((r["open_count"] for r in sidebar_rows), default=0) or 1

    owner_filter = request.args.get("owner", "")
    if owner_filter:
        selected = next((r for r in sidebar_rows if r["person"]["member_alias"] == owner_filter), None)
    else:
        selected = sidebar_rows[0] if sidebar_rows else None

    conn.close()
    return render_template(
        "team.html", sidebar_rows=sidebar_rows, selected=selected, max_open=max_open,
        blocking_map=blocking_map, filters={"owner": owner_filter},
    )


def render_project_form(project, people, errors, is_edit):
    return render_template(
        "project_form.html", project=project, people=people, errors=errors,
        is_edit=is_edit, engagement_types=ENGAGEMENT_TYPES,
        statuses=PROJECT_STATUSES, currencies=CURRENCIES,
    )


@app.route("/proyectos/nuevo", methods=["GET", "POST"])
def project_new():
    conn = get_db()
    people = db.list_people(conn)
    if request.method == "POST":
        data = {f: request.form.get(f, "").strip() or None for f in db.PROJECT_FIELDS}
        data, errors = validate_project_form(data, conn, is_new=True)
        if errors:
            conn.close()
            return render_project_form(data, people, errors, is_edit=False)
        db.upsert_project(conn, data)
        refresh_diagnosis_for(conn, data["project_code"])
        conn.close()
        return redirect(url_for("project_detail", project_code=data["project_code"]))
    conn.close()
    return render_project_form(None, people, None, is_edit=False)


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
    people = db.list_people(conn)
    diag = refresh_diagnosis(conn, project, tasks, today)
    blocking_map = risk_engine.compute_blocking_map(tasks)
    conn.close()
    return render_template(
        "project_detail.html", project=project, tasks=tasks, notes=notes,
        people=people, diag=diag, blocking_map=blocking_map,
        task_priorities=TASK_PRIORITIES, task_statuses=TASK_STATUSES,
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
        data, errors = validate_project_form(data, conn, is_new=False)
        if errors:
            conn.close()
            return render_project_form(data, people, errors, is_edit=True)
        db.upsert_project(conn, data)
        refresh_diagnosis_for(conn, project_code)
        conn.close()
        return redirect(url_for("project_detail", project_code=project_code))
    conn.close()
    return render_project_form(project, people, None, is_edit=True)


def _next_task_code(existing_codes, project_code):
    """Primer código libre para una tarea nueva del proyecto.

    No basta con `len(existing) + 1`: si se borró una tarea intermedia, ese
    número vuelve a estar "libre" según el conteo pero el código ya existió
    y `upsert_task` lo tomaría como una actualización silenciosa de una
    tarea que en realidad es otra (pérdida de datos). Se prueba código por
    código hasta encontrar uno que de verdad no esté en uso.
    """
    n = len(existing_codes) + 1
    while f"{project_code}-T{n:02d}-M" in existing_codes:
        n += 1
    return f"{project_code}-T{n:02d}-M"


@app.route("/proyectos/<project_code>/tareas/nueva", methods=["POST"])
def task_new(project_code):
    priority = request.form.get("priority", "Media")
    status = request.form.get("status", "Por hacer")
    assignee_alias = request.form.get("assignee_alias", "").strip() or None
    if priority not in TASK_PRIORITIES or status not in TASK_STATUSES:
        abort(400, description="Prioridad o estado de tarea inválidos.")

    conn = get_db()
    if assignee_alias and not any(
        p["member_alias"] == assignee_alias for p in db.list_people(conn)
    ):
        conn.close()
        abort(400, description="Responsable inválido.")

    existing = db.list_tasks(conn, project_code)
    task_code = _next_task_code({t["task_code"] for t in existing}, project_code)
    data = {
        "task_code": task_code,
        "project_code": project_code,
        "assignee_alias": assignee_alias,
        "priority": priority,
        "status": status,
        "due_date": request.form.get("due_date", "").strip() or None,
        "title": request.form.get("title", "").strip(),
        "detail": request.form.get("detail", "").strip(),
        "dependency": "",
    }
    db.upsert_task(conn, data)
    refresh_diagnosis_for(conn, project_code)
    conn.close()
    return redirect(url_for("project_detail", project_code=project_code))


@app.route("/tareas/<task_code>/estado", methods=["POST"])
def task_update_status(task_code):
    new_status = request.form.get("status")
    if new_status not in TASK_STATUSES:
        abort(400, description="Estado de tarea inválido.")

    conn = get_db()
    project_code = request.form.get("project_code")
    task = next((t for t in db.list_tasks(conn, project_code) if t["task_code"] == task_code), None)
    if task:
        data = {k: task[k] for k in db.TASK_FIELDS}
        data["status"] = new_status
        db.upsert_task(conn, data)
        refresh_diagnosis_for(conn, project_code)
    conn.close()
    return redirect(url_for("project_detail", project_code=project_code))


@app.route("/tareas/<task_code>/eliminar", methods=["POST"])
def task_delete(task_code):
    conn = get_db()
    project_code = request.form.get("project_code")
    db.delete_task(conn, task_code)
    refresh_diagnosis_for(conn, project_code)
    conn.close()
    return redirect(url_for("project_detail", project_code=project_code))


@app.route("/proyectos/<project_code>/eliminar", methods=["POST"])
def project_delete(project_code):
    conn = get_db()
    db.delete_project(conn, project_code)
    conn.close()
    return redirect(url_for("operational_view"))


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
    # AZTEC_PM_DEBUG=1 activa el recargador/depurador de Flask para desarrollo.
    app.run(debug=os.environ.get("AZTEC_PM_DEBUG") == "1", port=5050)
