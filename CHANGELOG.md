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

## v0.4 — Prioridad persistida de verdad, dashboard ejecutivo, filtrado instantáneo

- **Prioridad y salud dejan de ser "solo calculadas" y pasan a ser persistidas de verdad**: nuevas columnas `health`, `priority_score`, `priority_bucket`, `priority_breakdown`, `priority_computed_at` en `projects`, escritas por `db.update_priority_snapshot`. Se recalculan y graban en cada mutación relevante (proyecto Y tarea: alta, edición, cambio de estado, borrado) y también en cada carga del dashboard, para que ni el paso del tiempo las deje desactualizadas. `import_dataset.py` calcula el diagnóstico inicial de los 27 proyectos apenas se siembra la base — nunca queda un proyecto sin prioridad guardada. Decisión explícita del usuario: "si no se guarda, debe hacerse completo, no a medias".
- **Nuevo dashboard ejecutivo (`/dashboard`)**: salud del portafolio (donut), ranking de proyectos por Índice de Tensión, carga por persona, evidencia de higiene operativa por persona (con nota de metodología), y ranking de tareas que bloquean a otras. Todo clickeable hasta el dato de origen. Filtro por responsable que reduce todas las secciones a una sola persona.
- **Nuevas funciones de analytics en `risk_engine.py`** (puras, testeadas): `health_distribution`, `workload_by_person` (refactor de la lógica que antes vivía solo en `/equipo`, ahora reutilizada por ambas páginas), `hygiene_stats_by_person`.
- **Tarjetas KPI clickeables** en la vista operativa — antes eran informativas nada más; ahora cada una lleva a los proyectos que representa, con estado visual de "filtro activo".
- **Filtrado instantáneo sin recargar la página** (`static/live-filters.js`, único JS del proyecto, sin frameworks ni build step) en `/` y `/dashboard`. Corrigió un problema de UX real: los filtros funcionaban en el backend (verificado con `curl`), pero requerían un click aparte en "Filtrar" sin ninguna señal visible de que el cambio se había registrado, lo cual se reportó como "no funcionan".

## v0.5 — Filtros combinables y facetados, dashboard como carga principal, /equipo rediseñado

- **Bug real corregido: los filtros no se combinaban.** Los links de las tarjetas KPI armaban su URL con `url_for(endpoint, health='Bloqueado')`, que en Flask solo incluye los parámetros pasados explícitamente — elegir "Bloqueados" después de filtrar por responsable perdía el filtro de responsable. Nuevo helper `webapp.filter_link` (registrado como global de Jinja) arma esas URLs a partir de los filtros ya activos más el cambio pedido, nunca desde cero. En el dashboard ejecutivo, además, esas tarjetas apuntaban a la ruta operativa en vez de filtrar la propia página — ahora se quedan en la misma vista.
- **Conteos facetados en las tarjetas KPI** (`webapp.faceted_summary`): cada número ahora refleja el resto de la selección activa, no un total fijo del portafolio completo — la tarjeta "Bloqueados" con un responsable ya filtrado muestra los bloqueados *de ese responsable*.
- **`/` (antes `/dashboard`) pasa a ser la carga principal de la app**, con dos gráficas nuevas (barras interactivas, clickeables como el resto): distribución de prioridad (P0–P3) y distribución por tipo de compromiso. La tabla operativa se movió a `/proyectos`. Se renombraron los endpoints Flask en vez de agregar un redirect, para que `url_for('dashboard')` siguiera significando "la página principal" sin tener que auditar cada referencia.
- **Nuevo filtro por tipo de compromiso** (`engagement_type`), mismo mecanismo combinable que el resto.
- **`/equipo` rediseñado**: layout sidebar (todas las personas con su carga a simple vista + buscador por nombre) + panel principal con el flujo completo de la persona seleccionada, en vez de tarjetas apiladas una debajo de otra. Por defecto se abre quien tiene más carga.
- **7 pruebas nuevas** (`apply_filters`, `faceted_summary`, `filter_link`, `priority_distribution`, `engagement_distribution`) — 57 en total.
