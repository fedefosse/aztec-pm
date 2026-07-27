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


if __name__ == "__main__":
    unittest.main()
