"""Motor de riesgo y priorización — funciones puras, sin efectos secundarios.

Implementa el criterio documentado en directives/gestion_proyectos.md.
Cualquier cambio a las reglas de negocio debe reflejarse ahí primero.
"""

from datetime import date, datetime

COP_TO_USD = 1 / 4000  # tasa fija aproximada, documentada como supuesto

OPEN_TASK_STATUSES = {"Por hacer", "En progreso", "En revision", "Bloqueada"}


def parse_date(value):
    """Acepta 'YYYY-MM-DD' o 'DD/MM/YYYY'. Devuelve date o None."""
    if not value:
        return None
    value = str(value).strip()
    if not value:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


def parse_float(value):
    """Intenta convertir a float; nunca lanza. None si no es numérico."""
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def to_usd(business_value, currency):
    value = parse_float(business_value)
    if value is None:
        return None
    if currency == "COP":
        return value * COP_TO_USD
    return value


def task_is_overdue(task, today):
    if task["status"] == "Hecho":
        return False
    due = parse_date(task["due_date"])
    return due is not None and due < today


def split_tasks(tasks, today):
    """Separa tareas de un proyecto en abiertas/vencidas/bloqueadas."""
    open_tasks = [t for t in tasks if t["status"] in OPEN_TASK_STATUSES]
    overdue_tasks = [t for t in open_tasks if task_is_overdue(t, today)]
    blocked_tasks = [t for t in open_tasks if t["status"] == "Bloqueada"]
    critical_or_high_open = [
        t for t in open_tasks if t["priority"] in ("Alta", "Critica")
    ]
    return {
        "open": open_tasks,
        "overdue": overdue_tasks,
        "blocked": blocked_tasks,
        "critical_or_high_open": critical_or_high_open,
    }


def compute_health(project, tasks, today=None):
    """Devuelve 'Bloqueado' | 'En riesgo' | 'Sano'."""
    today = today or date.today()
    buckets = split_tasks(tasks, today)

    has_blocker_text = bool((project["blockers"] or "").strip())
    is_blocked = bool(buckets["blocked"]) or has_blocker_text

    target = parse_date(project["target_date"])
    target_overdue = (
        target is not None and target < today and project["status"] == "Activo"
    )
    is_at_risk = target_overdue or bool(buckets["overdue"])

    if is_blocked:
        return "Bloqueado"
    if is_at_risk:
        return "En riesgo"
    return "Sano"


def has_no_clear_next_step(project):
    return not (project["next_step"] or "").strip()


def is_operationally_orphaned(project, tasks, today=None):
    """Activo pero sin ninguna tarea abierta: nadie está moviendo el proyecto."""
    if project["status"] != "Activo":
        return False
    today = today or date.today()
    buckets = split_tasks(tasks, today)
    return len(buckets["open"]) == 0


def compute_priority(project, tasks, today=None):
    """Score 0-100 + bucket + desglose explicable."""
    today = today or date.today()
    buckets = split_tasks(tasks, today)
    breakdown = {}

    # Urgencia de fecha
    target = parse_date(project["target_date"])
    if target is None:
        breakdown["urgencia"] = 10
    else:
        days = (target - today).days
        if days < 0:
            breakdown["urgencia"] = 40
        elif days <= 7:
            breakdown["urgencia"] = 30
        elif days <= 30:
            breakdown["urgencia"] = 15
        else:
            breakdown["urgencia"] = 5

    # Impacto de negocio
    usd = to_usd(project["business_value"], project["currency"])
    if usd is None:
        breakdown["impacto"] = 0
    elif usd >= 25000:
        breakdown["impacto"] = 20
    elif usd >= 12000:
        breakdown["impacto"] = 12
    else:
        breakdown["impacto"] = 5

    # Severidad de riesgo
    health = compute_health(project, tasks, today)
    breakdown["severidad"] = {"Bloqueado": 25, "En riesgo": 15, "Sano": 0}[health]

    # Carga crítica (tope 20)
    breakdown["carga_critica"] = min(20, 5 * len(buckets["critical_or_high_open"]))

    # Tipo de compromiso
    breakdown["tipo_compromiso"] = {
        "Proyecto": 10,
        "Diagnostico": 5,
        "Mantenimiento o recurrente": 0,
    }.get(project["engagement_type"], 0)

    # Higiene operativa
    breakdown["higiene"] = 10 if has_no_clear_next_step(project) else 0

    # Orfandad operativa: activo pero nadie lo esta moviendo
    breakdown["orfandad"] = 15 if is_operationally_orphaned(project, tasks, today) else 0

    score = min(100, sum(breakdown.values()))

    if score >= 70:
        bucket = "P0 - Critica"
    elif score >= 50:
        bucket = "P1 - Alta"
    elif score >= 30:
        bucket = "P2 - Media"
    else:
        bucket = "P3 - Baja"

    return {
        "score": score,
        "bucket": bucket,
        "breakdown": breakdown,
        "health": health,
    }


def _title_stem(title):
    """El dataset arma el título como '{tarea} - {proyecto}'; el campo
    `dependency` de una tarea guarda ese mismo prefijo, no el proyecto."""
    return (title or "").split(" - ")[0].strip()


def compute_blocking_map(tasks):
    """Quién bloquea a quién.

    El campo `dependency` de una tarea es su PRERREQUISITO (el título de la
    tarea de la que depende), no algo que ella misma bloquee — es fácil
    leerlo al revés. Esta función invierte la relación: para cada tarea,
    devuelve la lista de títulos de tareas abiertas que dependen de ella
    (dentro del mismo proyecto; los títulos solo son únicos por proyecto).
    Una tarea "Hecha" ya no cuenta como dependiente de nadie.
    """
    by_project = {}
    for t in tasks:
        by_project.setdefault(t["project_code"], []).append(t)

    blocks = {}
    for project_tasks in by_project.values():
        title_to_code = {_title_stem(t["title"]): t["task_code"] for t in project_tasks}
        for t in project_tasks:
            if t["status"] == "Hecho":
                continue
            dep = (t["dependency"] or "").strip()
            if not dep:
                continue
            prereq_code = title_to_code.get(dep)
            if prereq_code:
                blocks.setdefault(prereq_code, []).append(t["title"])
    return blocks


def diagnose(project, tasks, today=None):
    """Diagnóstico completo de un proyecto: salud, prioridad, y flags operativos."""
    today = today or date.today()
    buckets = split_tasks(tasks, today)
    priority = compute_priority(project, tasks, today)
    return {
        "health": priority["health"],
        "priority_score": priority["score"],
        "priority_bucket": priority["bucket"],
        "priority_breakdown": priority["breakdown"],
        "no_clear_next_step": has_no_clear_next_step(project),
        "operationally_orphaned": is_operationally_orphaned(project, tasks, today),
        "open_tasks": len(buckets["open"]),
        "overdue_tasks": len(buckets["overdue"]),
        "blocked_tasks": len(buckets["blocked"]),
    }


def health_distribution(healths):
    """Cuenta de proyectos por salud, para el donut del dashboard ejecutivo.
    `healths` es la lista de valores 'health' ya calculados (uno por proyecto)."""
    counts = {"Bloqueado": 0, "En riesgo": 0, "Sano": 0}
    for h in healths:
        counts[h] = counts.get(h, 0) + 1
    return counts


def workload_by_person(people, all_tasks):
    """Carga de trabajo por persona a partir de TODAS las tareas del
    portafolio (no solo de un proyecto). Reutilizado por /equipo y
    /dashboard para no calcular esto dos veces con lógica distinta.

    Devuelve una lista de dicts (uno por persona) ordenada de mayor a menor
    carga abierta — así "quién tiene más atraso que otros" es simplemente
    leer la lista de arriba hacia abajo.
    """
    blocking_map = compute_blocking_map(all_tasks)
    priority_rank = {"Critica": 0, "Alta": 1, "Media": 2, "Baja": 3}

    rows = []
    for person in people:
        alias = person["member_alias"]
        my_tasks = [t for t in all_tasks if t["assignee_alias"] == alias]
        open_tasks = [t for t in my_tasks if t["status"] in OPEN_TASK_STATUSES]
        blocked = [t for t in open_tasks if t["status"] == "Bloqueada"]
        critical_high = [t for t in open_tasks if t["priority"] in ("Alta", "Critica")]

        # Efecto dominó: las tareas de las que dependen OTRAS tareas abiertas
        # flotan al inicio — son las que, si no avanzan, frenan a alguien más.
        sorted_tasks = sorted(
            open_tasks,
            key=lambda t: (
                0 if t["task_code"] in blocking_map else 1,
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

    rows.sort(key=lambda r: r["open_count"], reverse=True)
    return rows, blocking_map


def hygiene_stats_by_person(people, projects, all_tasks, today=None):
    """Evidencia de higiene operativa por persona — NO es un índice único:
    se muestran dos señales por separado (ver directiva) para que se pueda
    distinguir "buen proceso" de "le tocó una carga más fácil".

    - next_step_pct: % de los proyectos donde es responsable (owner_alias)
      que tienen un siguiente paso definido.
    - overdue_pct: % de sus tareas abiertas (assignee_alias) que están
      vencidas.

    Ambos son `None` (no `0`) cuando no hay base para calcular el
    porcentaje (nadie es responsable de ningún proyecto, o no tiene tareas
    abiertas) — 0% y "sin datos" no son lo mismo y no deben mostrarse igual.
    """
    today = today or date.today()
    stats = []
    for person in people:
        alias = person["member_alias"]

        my_projects = [p for p in projects if p["owner_alias"] == alias]
        with_next_step = [p for p in my_projects if not has_no_clear_next_step(p)]
        next_step_pct = (
            round(100 * len(with_next_step) / len(my_projects)) if my_projects else None
        )

        my_tasks = [t for t in all_tasks if t["assignee_alias"] == alias]
        open_tasks = [t for t in my_tasks if t["status"] in OPEN_TASK_STATUSES]
        overdue = [t for t in open_tasks if task_is_overdue(t, today)]
        overdue_pct = round(100 * len(overdue) / len(open_tasks)) if open_tasks else None

        stats.append({
            "person": person,
            "project_count": len(my_projects),
            "next_step_pct": next_step_pct,
            "open_task_count": len(open_tasks),
            "overdue_pct": overdue_pct,
        })
    return stats
