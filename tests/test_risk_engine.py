"""Pruebas del motor de riesgo/prioridad (funciones puras, sin DB).

Uso: python3 -m unittest discover -s tests   (desde la raíz de aztec-pm)
"""

import sys
import unittest
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "execution"))
import risk_engine  # noqa: E402

TODAY = date(2026, 7, 27)


def make_project(**overrides):
    base = {
        "project_code": "TST-01",
        "engagement_type": "Proyecto",
        "status": "Activo",
        "target_date": None,
        "next_step": "Algo concreto",
        "blockers": None,
        "business_value": None,
        "currency": "USD",
    }
    base.update(overrides)
    return base


def make_task(**overrides):
    base = {
        "task_code": "TST-01-T01",
        "project_code": "TST-01",
        "title": "Hacer algo",
        "status": "Por hacer",
        "priority": "Media",
        "due_date": None,
        "dependency": "",
    }
    base.update(overrides)
    return base


class TestParseDate(unittest.TestCase):
    def test_iso_format(self):
        self.assertEqual(risk_engine.parse_date("2026-08-01"), date(2026, 8, 1))

    def test_dd_mm_yyyy_format(self):
        self.assertEqual(risk_engine.parse_date("02/03/2026"), date(2026, 3, 2))

    def test_empty_or_none(self):
        self.assertIsNone(risk_engine.parse_date(None))
        self.assertIsNone(risk_engine.parse_date(""))
        self.assertIsNone(risk_engine.parse_date("   "))

    def test_garbage(self):
        self.assertIsNone(risk_engine.parse_date("no es una fecha"))


class TestParseFloat(unittest.TestCase):
    def test_valid_number(self):
        self.assertEqual(risk_engine.parse_float("1000"), 1000.0)

    def test_none_or_empty(self):
        self.assertIsNone(risk_engine.parse_float(None))
        self.assertIsNone(risk_engine.parse_float(""))

    def test_garbage_does_not_raise(self):
        self.assertIsNone(risk_engine.parse_float("no-es-un-numero"))


class TestToUsd(unittest.TestCase):
    def test_usd_passthrough(self):
        self.assertEqual(risk_engine.to_usd(1000, "USD"), 1000)

    def test_cop_conversion(self):
        self.assertAlmostEqual(risk_engine.to_usd(120_000_000, "COP"), 30_000)

    def test_missing_value(self):
        self.assertIsNone(risk_engine.to_usd(None, "USD"))
        self.assertIsNone(risk_engine.to_usd("", "USD"))

    def test_non_numeric_value_does_not_raise(self):
        # Regresión: un business_value corrupto no debe romper el cálculo.
        self.assertIsNone(risk_engine.to_usd("no-es-un-numero", "USD"))


class TestUrgencyThresholds(unittest.TestCase):
    def _urgencia(self, target_date):
        project = make_project(target_date=target_date)
        return risk_engine.compute_priority(project, [], today=TODAY)["breakdown"]["urgencia"]

    def test_vencida(self):
        self.assertEqual(self._urgencia((TODAY - timedelta(days=1)).isoformat()), 40)

    def test_exactamente_7_dias(self):
        self.assertEqual(self._urgencia((TODAY + timedelta(days=7)).isoformat()), 30)

    def test_8_dias_cae_a_siguiente_bucket(self):
        self.assertEqual(self._urgencia((TODAY + timedelta(days=8)).isoformat()), 15)

    def test_exactamente_30_dias(self):
        self.assertEqual(self._urgencia((TODAY + timedelta(days=30)).isoformat()), 15)

    def test_31_dias(self):
        self.assertEqual(self._urgencia((TODAY + timedelta(days=31)).isoformat()), 5)

    def test_sin_fecha(self):
        self.assertEqual(self._urgencia(None), 10)


class TestComputeHealth(unittest.TestCase):
    def test_bloqueado_por_tarea_bloqueada(self):
        project = make_project()
        tasks = [make_task(status="Bloqueada")]
        self.assertEqual(risk_engine.compute_health(project, tasks, TODAY), "Bloqueado")

    def test_bloqueado_por_texto_de_bloqueos(self):
        project = make_project(blockers="Esperando acceso del cliente.")
        self.assertEqual(risk_engine.compute_health(project, [], TODAY), "Bloqueado")

    def test_en_riesgo_por_fecha_vencida(self):
        project = make_project(target_date=(TODAY - timedelta(days=5)).isoformat())
        self.assertEqual(risk_engine.compute_health(project, [], TODAY), "En riesgo")

    def test_en_riesgo_por_tarea_vencida(self):
        project = make_project()
        tasks = [make_task(due_date=(TODAY - timedelta(days=2)).isoformat())]
        self.assertEqual(risk_engine.compute_health(project, tasks, TODAY), "En riesgo")

    def test_sano(self):
        project = make_project(target_date=(TODAY + timedelta(days=30)).isoformat())
        tasks = [make_task(due_date=(TODAY + timedelta(days=10)).isoformat())]
        self.assertEqual(risk_engine.compute_health(project, tasks, TODAY), "Sano")

    def test_cerrado_con_fecha_vencida_no_es_en_riesgo(self):
        project = make_project(status="Cerrado", target_date=(TODAY - timedelta(days=40)).isoformat())
        self.assertEqual(risk_engine.compute_health(project, [], TODAY), "Sano")


class TestHigieneOperativa(unittest.TestCase):
    def test_sin_siguiente_paso(self):
        project = make_project(next_step="")
        self.assertTrue(risk_engine.has_no_clear_next_step(project))

    def test_con_siguiente_paso(self):
        project = make_project(next_step="Revisar con el cliente")
        self.assertFalse(risk_engine.has_no_clear_next_step(project))

    def test_huerfano_activo_sin_tareas(self):
        project = make_project(status="Activo")
        self.assertTrue(risk_engine.is_operationally_orphaned(project, [], TODAY))

    def test_no_huerfano_si_tiene_tareas_abiertas(self):
        project = make_project(status="Activo")
        tasks = [make_task(status="En progreso")]
        self.assertFalse(risk_engine.is_operationally_orphaned(project, tasks, TODAY))

    def test_cerrado_nunca_es_huerfano(self):
        project = make_project(status="Cerrado")
        self.assertFalse(risk_engine.is_operationally_orphaned(project, [], TODAY))


class TestComputePriority(unittest.TestCase):
    def test_score_nunca_pasa_de_100(self):
        project = make_project(
            target_date=(TODAY - timedelta(days=5)).isoformat(),
            blockers="Bloqueado por el cliente.",
            next_step="",
            business_value=100000,
            currency="USD",
        )
        tasks = [make_task(status="Bloqueada", priority="Critica") for _ in range(10)]
        result = risk_engine.compute_priority(project, tasks, TODAY)
        self.assertLessEqual(result["score"], 100)

    def test_bucket_p0_por_encima_de_70(self):
        project = make_project(
            target_date=(TODAY - timedelta(days=1)).isoformat(),
            blockers="Bloqueado.",
        )
        result = risk_engine.compute_priority(project, [], TODAY)
        self.assertGreaterEqual(result["score"], 70)
        self.assertEqual(result["bucket"], "P0 - Critica")

    def test_bucket_p3_proyecto_sano_y_lejano(self):
        # Con al menos una tarea abierta de baja prioridad para no disparar
        # también la señal de "orfandad operativa" (Activo + 0 tareas abiertas),
        # que es una condición aparte y sumaría puntos por su cuenta.
        project = make_project(target_date=(TODAY + timedelta(days=90)).isoformat())
        tasks = [make_task(status="En progreso", priority="Baja",
                            due_date=(TODAY + timedelta(days=60)).isoformat())]
        result = risk_engine.compute_priority(project, tasks, TODAY)
        self.assertLess(result["score"], 30)
        self.assertEqual(result["bucket"], "P3 - Baja")


class TestComputeBlockingMap(unittest.TestCase):
    def test_una_tarea_bloquea_a_otra(self):
        tasks = [
            make_task(task_code="P-T01", title="Plan next delivery iteration - X", dependency=""),
            make_task(task_code="P-T02", title="Functional validation - X", dependency="Plan next delivery iteration"),
        ]
        blocks = risk_engine.compute_blocking_map(tasks)
        self.assertEqual(blocks.get("P-T01"), ["Functional validation - X"])
        self.assertNotIn("P-T02", blocks)

    def test_una_tarea_puede_bloquear_a_varias(self):
        tasks = [
            make_task(task_code="P-T01", title="Weekly KPI monitoring - X", dependency=""),
            make_task(task_code="P-T02", title="Adjust rule - X", dependency="Weekly KPI monitoring"),
            make_task(task_code="P-T03", title="Clean backlog - X", dependency="Weekly KPI monitoring"),
        ]
        blocks = risk_engine.compute_blocking_map(tasks)
        self.assertEqual(len(blocks.get("P-T01", [])), 2)

    def test_tarea_hecha_ya_no_bloquea_a_nadie(self):
        tasks = [
            make_task(task_code="P-T01", title="Plan - X", dependency=""),
            make_task(task_code="P-T02", title="Validar - X", dependency="Plan", status="Hecho"),
        ]
        blocks = risk_engine.compute_blocking_map(tasks)
        self.assertNotIn("P-T01", blocks)

    def test_no_cruza_proyectos_distintos(self):
        # Mismo texto de dependencia en dos proyectos distintos no debe mezclarse.
        tasks = [
            make_task(task_code="A-T01", project_code="A", title="Plan - A", dependency=""),
            make_task(task_code="B-T02", project_code="B", title="Validar - B", dependency="Plan"),
        ]
        blocks = risk_engine.compute_blocking_map(tasks)
        self.assertNotIn("A-T01", blocks)


if __name__ == "__main__":
    unittest.main()
