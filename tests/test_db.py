"""Pruebas de integración de execution/db.py contra un SQLite en memoria.

A diferencia de test_risk_engine.py (funciones puras, sin DB), estas pruebas
SÍ tocan una base de datos real — es la única forma de probar honestamente
que "guardar prioridad" significa lo que dice: un valor que de verdad queda
escrito y se puede releer, no un cálculo que se pasa por alto.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "execution"))
import sqlite3  # noqa: E402
import db  # noqa: E402
import risk_engine  # noqa: E402


def make_memory_conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    db.init_schema(conn)
    return conn


PROJECT = {
    "project_code": "TST-01",
    "client_alias": "Cliente X",
    "project_name": "Proyecto de prueba",
    "engagement_type": "Proyecto",
    "owner_alias": None,
    "status": "Activo",
    "target_date": None,
    "next_step": "",
    "blockers": "Esperando acceso del cliente.",
    "business_value": "10000",
    "currency": "USD",
    "start_date": None,
    "stage": "Ejecucion",
    "summary": "",
}


class TestPrioritySnapshotPersistence(unittest.TestCase):
    def setUp(self):
        self.conn = make_memory_conn()
        db.upsert_project(self.conn, PROJECT)

    def test_priority_no_esta_seteada_antes_del_primer_calculo(self):
        # Antes de calcular y grabar nada, las columnas de diagnóstico
        # existen pero están vacías — no hay un valor "de mentira".
        row = db.get_project(self.conn, "TST-01")
        self.assertIsNone(row["priority_score"])
        self.assertIsNone(row["health"])

    def test_update_priority_snapshot_se_puede_releer(self):
        project = db.get_project(self.conn, "TST-01")
        diag = risk_engine.diagnose(project, [])
        db.update_priority_snapshot(self.conn, "TST-01", diag)

        reloaded = db.get_project(self.conn, "TST-01")
        # El proyecto tiene `blockers` con texto -> Bloqueado.
        self.assertEqual(reloaded["health"], "Bloqueado")
        self.assertEqual(reloaded["priority_score"], diag["priority_score"])
        self.assertEqual(reloaded["priority_bucket"], diag["priority_bucket"])
        self.assertIsNotNone(reloaded["priority_computed_at"])

    def test_el_desglose_persistido_es_json_valido_y_completo(self):
        import json
        project = db.get_project(self.conn, "TST-01")
        diag = risk_engine.diagnose(project, [])
        db.update_priority_snapshot(self.conn, "TST-01", diag)

        reloaded = db.get_project(self.conn, "TST-01")
        breakdown = json.loads(reloaded["priority_breakdown"])
        self.assertEqual(breakdown, diag["priority_breakdown"])

    def test_upsert_project_nunca_pisa_las_columnas_de_diagnostico(self):
        # Guardar un cambio de campo de usuario (ej. next_step) no debe
        # borrar ni tocar el diagnóstico ya persistido.
        project = db.get_project(self.conn, "TST-01")
        diag = risk_engine.diagnose(project, [])
        db.update_priority_snapshot(self.conn, "TST-01", diag)

        edited = dict(PROJECT)
        edited["next_step"] = "Ahora sí hay un siguiente paso"
        db.upsert_project(self.conn, edited)

        reloaded = db.get_project(self.conn, "TST-01")
        self.assertEqual(reloaded["next_step"], "Ahora sí hay un siguiente paso")
        self.assertEqual(reloaded["priority_score"], diag["priority_score"])

    def tearDown(self):
        self.conn.close()


if __name__ == "__main__":
    unittest.main()
