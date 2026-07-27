# Changelog

Historial de decisiones de este prototipo, en orden. No sigue versionado semántico estricto — son hitos de una sola sesión de trabajo.

## v0.1 — CRUD + motor de riesgo/prioridad

- Arquitectura de 3 capas (`directives/` + `execution/` + `seed_data/`), Flask + SQLite.
- Importación del dataset real de Aztec (22 proyectos, 82 tareas, 5 personas) + 5 proyectos sintéticos con fechas ancladas a "hoy" real, para ilustrar cada combinación de estado/prioridad.
- Motor de riesgo determinista (`risk_engine.py`): detección de Bloqueado / En riesgo / Sano y de "sin siguiente paso claro".
- Score de prioridad 0–100 explicable, con desglose por factor.
- Vista operativa filtrable (dashboard) + CRUD de proyectos, tareas y notas.

## v0.2 — Orfandad operativa, vista de equipo, Índice de Tensión

- Se evaluó y descartó un plan alternativo (Next.js + JSON + n8n) por contradecir el mandato de mantener la ejecución en Python determinista dentro de `execution/`.
- Se incorporaron del plan alternativo las ideas de negocio compatibles con el stack actual:
  - Nueva señal **orfandad operativa** (proyecto `Activo` sin ninguna tarea abierta).
  - Vista **`/equipo`**: carga por persona calculada en vivo.
  - Renombrado del score a **"Índice de Tensión"**.

## v0.3 — Hardening: validación, pruebas, corrección de datos, publicación

Tras una auditoría adversarial (agente de lectura sin el contexto de haber escrito el código) y una revisión manual de los datos:

- **Corrección de datos**: el campo `dependency` de las tareas se había interpretado al revés — guarda el *prerrequisito* de la tarea, no algo que ella bloquee. Se agregó `compute_blocking_map` para invertir la relación correctamente y se corrigió el "efecto dominó" en `/equipo` y en el detalle de proyecto.
- **Corrección de bugs**: un `business_value` no numérico rompía el cálculo de todo el dashboard (no solo un proyecto); se corrigió `to_usd()` para degradar a "sin dato" en vez de lanzar una excepción.
- **Endurecimiento de formularios**: validación de código de proyecto (formato, duplicados) y de todos los campos con lista cerrada de valores (`engagement_type`, `status`, `currency`, `priority`); errores legibles en vez de errores 500.
- **Completar el CRUD**: eliminar proyectos y tareas desde la UI (antes existían las funciones en `db.py` pero ninguna ruta las usaba).
- **Responsable de tarea como selector**, no texto libre — evita que un alias mal tipeado desaparezca en silencio de la vista de equipo.
- **Seguridad**: `debug=True` de Flask apagado por defecto (activable con `AZTEC_PM_DEBUG=1` para desarrollo).
- **Pruebas automatizadas**: `tests/test_risk_engine.py` (`unittest` estándar) sobre las funciones puras del motor de riesgo/prioridad, y `tests/test_webapp.py` sobre la generación de código de tarea sin colisiones (ver bug corregido más abajo).
- **Bug de datos corregido**: `task_new` generaba el código de una tarea nueva como `len(tareas existentes) + 1`. Si se borraba una tarea intermedia, el siguiente alta podía reutilizar un código ya usado — `upsert_task` lo interpretaba como una actualización silenciosa de la tarea equivocada (pérdida de datos sin ningún error visible). `_next_task_code` ahora prueba códigos hasta encontrar uno realmente libre.
- **Documentación**: `AGENTS.md`/`GEMINI.md` replicando `CLAUDE.md` (misma convención que la carpeta raíz del reto), directiva y README actualizados.
- **Publicación**: repositorio público en GitHub.
