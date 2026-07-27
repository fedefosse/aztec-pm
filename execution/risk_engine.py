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


def to_usd(business_value, currency):
    if business_value is None or business_value == "":
        return None
    value = float(business_value)
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
        "open_tasks": len(buckets["open"]),
        "overdue_tasks": len(buckets["overdue"]),
        "blocked_tasks": len(buckets["blocked"]),
    }
