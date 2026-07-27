"""Reinicializa aztec_pm.db desde seed_data/*.csv + siembra ejemplos sintéticos.

Idempotente: siempre parte de una base vacía. Pensado para desarrollo/demo,
no para correr sobre datos vivos en producción (ver directives/gestion_proyectos.md).

Uso: python3 execution/import_dataset.py
"""

import csv
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import db  # noqa: E402

SEED_DIR = Path(__file__).parent.parent / "seed_data"


def read_csv(name):
    with open(SEED_DIR / name, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def reset_db():
    if db.DB_PATH.exists():
        db.DB_PATH.unlink()
    conn = db.get_conn()
    db.init_schema(conn)
    return conn


def import_team(conn):
    for row in read_csv("team.csv"):
        db.upsert_person(conn, row["member_alias"], row["role"])


def project_number(project_code):
    return int(project_code.split("-")[1])


def import_projects_and_tasks(conn):
    projects = read_csv("projects.csv")
    tasks = read_csv("tasks.csv")

    tasks_by_project = {}
    for t in tasks:
        tasks_by_project.setdefault(t["project_code"], []).append(t)

    for p in projects:
        code = p["project_code"]
        open_tasks_for_p = [
            t for t in tasks_by_project.get(code, [])
            if t["status"] != "Hecho"
        ]
        # Regla de siembra: proyectos con numero par heredan un siguiente
        # paso sugerido a partir de su primera tarea abierta; los impares
        # quedan sin siguiente paso, para mostrar la deteccion de higiene
        # operativa funcionando sobre datos reales desde el primer import.
        next_step = ""
        if project_number(code) % 2 == 0 and open_tasks_for_p:
            next_step = f"Continuar: {open_tasks_for_p[0]['title']}"

        db.upsert_project(conn, {
            "project_code": code,
            "client_alias": p["client_alias"],
            "project_name": p["project_name"],
            "engagement_type": p["engagement_type"],
            "owner_alias": p["owner_alias"],
            "status": p["status"] or "Activo",
            "target_date": p["target_date"] or None,
            "next_step": next_step,
            "blockers": p["blockers"] or "",
            "business_value": p["business_value"] or None,
            "currency": p["currency"] or "USD",
            "start_date": p["start_date"] or None,
            "stage": p["stage"],
            "summary": p["summary"],
        })

        for t in tasks_by_project.get(code, []):
            db.upsert_task(conn, {
                "task_code": t["task_code"],
                "project_code": code,
                "assignee_alias": t["assignee_alias"] or None,
                "priority": t["priority"],
                "status": t["status"],
                "due_date": t["due_date"] or None,
                "title": t["title"],
                "detail": t["detail"],
                "dependency": t["dependency"] or "",
            })

    return len(projects), len(tasks)


def seed_synthetic_examples(conn):
    """Proyectos con fechas relativas a HOY real, para mostrar el rango
    completo de estados/prioridades incluso cuando el dataset importado
    quede con fechas históricas (ver nota en la directiva)."""
    today = date.today()
    iso = lambda d: d.isoformat()

    synthetic = [
        dict(
            project_code="SYN-01", client_alias="Nimbus Retail",
            project_name="Portal de Autoservicio Clientes",
            engagement_type="Mantenimiento o recurrente", owner_alias="Camila Torres",
            status="Activo", target_date=iso(today + timedelta(days=90)),
            next_step="Revisar métricas de adopción del mes y ajustar FAQ",
            blockers="", business_value=9000, currency="USD",
            start_date=iso(today - timedelta(days=200)), stage="Ejecucion",
            summary="Portal de autoservicio ya estable, en fase de mantenimiento.",
        ),
        dict(
            project_code="SYN-02", client_alias="Ferra Bank",
            project_name="Migracion Core Bancario",
            engagement_type="Proyecto", owner_alias="Laura Gomez",
            status="Activo", target_date=iso(today + timedelta(days=5)),
            next_step="Validar corrida de conciliacion en ambiente staging",
            blockers="", business_value=32000, currency="USD",
            start_date=iso(today - timedelta(days=60)), stage="Ejecucion",
            summary="Migracion de motor transaccional a nueva arquitectura.",
        ),
        dict(
            project_code="SYN-03", client_alias="Vantia Salud",
            project_name="Chatbot Soporte Nivel 1",
            engagement_type="Diagnostico", owner_alias="Mateo Ruiz",
            status="Activo", target_date=iso(today + timedelta(days=15)),
            next_step="",
            blockers="Esperando acceso a la API de historias clinicas del cliente.",
            business_value=6000, currency="USD",
            start_date=iso(today - timedelta(days=10)), stage="Descubrimiento",
            summary="Diagnostico de viabilidad para chatbot de soporte N1.",
        ),
        dict(
            project_code="SYN-04", client_alias="Orbita Seguros",
            project_name="Dashboard Financiero Ejecutivo",
            engagement_type="Proyecto", owner_alias="Santiago Vera",
            status="Activo", target_date=iso(today + timedelta(days=60)),
            next_step="",
            blockers="", business_value=30000, currency="USD",
            start_date=iso(today - timedelta(days=20)), stage="Ejecucion",
            summary="Dashboard ejecutivo de indicadores financieros. Va sano, pero nadie definio el siguiente paso.",
        ),
        dict(
            project_code="SYN-05", client_alias="Kappa Logistics",
            project_name="Automatizacion de Onboarding",
            engagement_type="Mantenimiento o recurrente", owner_alias="Andrea Molina",
            status="Cerrado", target_date=iso(today - timedelta(days=40)),
            next_step="Cerrado: sin seguimiento activo.",
            blockers="", business_value=11000, currency="USD",
            start_date=iso(today - timedelta(days=300)), stage="Ejecucion",
            summary="Automatizacion entregada y cerrada; se deja como referencia historica.",
        ),
    ]
    for p in synthetic:
        db.upsert_project(conn, p)

    synthetic_tasks = [
        dict(task_code="SYN-01-T01", project_code="SYN-01", assignee_alias="Camila Torres",
             priority="Baja", status="En progreso", due_date=iso(today + timedelta(days=20)),
             title="Actualizar FAQ del portal", detail="Ajustar preguntas frecuentes tras feedback.",
             dependency=""),
        dict(task_code="SYN-02-T01", project_code="SYN-02", assignee_alias="Laura Gomez",
             priority="Critica", status="Por hacer", due_date=iso(today - timedelta(days=3)),
             title="Validar conciliacion en staging", detail="Bloquea el go-live si no se resuelve.",
             dependency=""),
        dict(task_code="SYN-03-T01", project_code="SYN-03", assignee_alias="Mateo Ruiz",
             priority="Alta", status="Bloqueada", due_date=iso(today + timedelta(days=10)),
             title="Integrar API de historias clinicas", detail="Sin acceso del cliente no se puede avanzar.",
             dependency=""),
        dict(task_code="SYN-04-T01", project_code="SYN-04", assignee_alias="Santiago Vera",
             priority="Media", status="En revision", due_date=iso(today + timedelta(days=25)),
             title="Revisar visualizaciones con stakeholder", detail="Pendiente feedback de negocio.",
             dependency=""),
        dict(task_code="SYN-05-T01", project_code="SYN-05", assignee_alias="Andrea Molina",
             priority="Baja", status="Hecho", due_date=iso(today - timedelta(days=45)),
             title="Entrega final de automatizacion", detail="Cerrado y aceptado por el cliente.",
             dependency=""),
    ]
    for t in synthetic_tasks:
        db.upsert_task(conn, t)


def main():
    conn = reset_db()
    import_team(conn)
    n_projects, n_tasks = import_projects_and_tasks(conn)
    seed_synthetic_examples(conn)
    conn.close()
    print(f"Importados {n_projects} proyectos y {n_tasks} tareas desde seed_data/.")
    print("Sembrados 5 proyectos sinteticos (SYN-01..05) con fechas relativas a hoy.")
    print(f"Base de datos lista en {db.DB_PATH}")


if __name__ == "__main__":
    main()
