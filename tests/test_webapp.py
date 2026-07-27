"""Pruebas de las funciones puras de execution/webapp.py (sin levantar Flask)."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "execution"))
import webapp  # noqa: E402


class TestNextTaskCode(unittest.TestCase):
    def test_primer_codigo_de_un_proyecto_vacio(self):
        self.assertEqual(webapp._next_task_code(set(), "PRJ-01"), "PRJ-01-T01-M")

    def test_siguiente_codigo_secuencial(self):
        existing = {"PRJ-01-T01-M", "PRJ-01-T02-M"}
        self.assertEqual(webapp._next_task_code(existing, "PRJ-01"), "PRJ-01-T03-M")

    def test_no_colisiona_tras_borrar_una_tarea_intermedia(self):
        # Regresión: quedaban 2 tareas (T01, T03) tras borrar T02. Contar
        # nada más "len(existing) + 1" generaría de nuevo "T03", que ya
        # existe, y upsert_task lo tomaría como una actualización silenciosa
        # de la tarea equivocada.
        existing = {"PRJ-01-T01-M", "PRJ-01-T03-M"}
        new_code = webapp._next_task_code(existing, "PRJ-01")
        self.assertNotIn(new_code, existing)
        self.assertEqual(new_code, "PRJ-01-T04-M")


def make_row(project_code, health, bucket, owner=None, engagement_type="Proyecto",
             no_next_step=False, orphaned=False):
    return {
        "project": {"project_code": project_code, "owner_alias": owner, "engagement_type": engagement_type},
        "diag": {
            "health": health, "priority_bucket": bucket, "priority_score": 0,
            "no_clear_next_step": no_next_step, "operationally_orphaned": orphaned,
        },
    }


NO_FILTERS = {"health": "", "bucket": "", "owner": "", "engagement_type": "", "no_next_step": "", "orphaned": ""}


class TestApplyFilters(unittest.TestCase):
    def test_combina_varios_filtros_con_and(self):
        # Regresión: antes, elegir "Bloqueados" con un responsable ya
        # filtrado perdía el filtro de responsable — los dos deben poder
        # aplicarse a la vez.
        rows = [
            make_row("A", "Bloqueado", "P0 - Critica", owner="Daniel Rojas"),
            make_row("B", "Bloqueado", "P1 - Alta", owner="Camila Torres"),
            make_row("C", "Sano", "P3 - Baja", owner="Daniel Rojas"),
        ]
        filters = dict(NO_FILTERS, health="Bloqueado", owner="Daniel Rojas")
        result = webapp.apply_filters(rows, filters)
        self.assertEqual([r["project"]["project_code"] for r in result], ["A"])

    def test_exclude_ignora_esa_clave_del_filtro(self):
        rows = [make_row("A", "Bloqueado", "P0 - Critica"), make_row("B", "Sano", "P3 - Baja")]
        filters = dict(NO_FILTERS, health="Bloqueado")
        result = webapp.apply_filters(rows, filters, exclude=("health",))
        self.assertEqual(len(result), 2)


class TestFacetedSummary(unittest.TestCase):
    def test_conteo_de_tarjeta_respeta_el_resto_de_filtros_activos(self):
        # Regresión: la tarjeta "Bloqueados" debe mostrar cuántos bloqueados
        # tiene la selección ACTUAL (ej. de un responsable), no el total
        # fijo del portafolio completo.
        rows = [
            make_row("A", "Bloqueado", "P0 - Critica", owner="Daniel Rojas"),
            make_row("B", "Bloqueado", "P1 - Alta", owner="Camila Torres"),
        ]
        filters = dict(NO_FILTERS, owner="Daniel Rojas")
        summary = webapp.faceted_summary(rows, filters)
        self.assertEqual(summary["bloqueados"], 1)
        self.assertEqual(summary["total"], 1)


class TestFilterLink(unittest.TestCase):
    def test_combina_en_vez_de_reemplazar(self):
        with webapp.app.test_request_context("/"):
            current = dict(NO_FILTERS, owner="Daniel Rojas")
            url = webapp.filter_link("dashboard", current, health="Bloqueado")
        self.assertIn("health=Bloqueado", url)
        self.assertIn("Daniel", url)

    def test_override_none_quita_el_filtro(self):
        with webapp.app.test_request_context("/"):
            current = dict(NO_FILTERS, health="Bloqueado")
            url = webapp.filter_link("dashboard", current, health=None)
        self.assertNotIn("health=", url)


if __name__ == "__main__":
    unittest.main()
