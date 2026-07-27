# Aztec PM — Sistema de Gestión de Proyectos

Prototipo funcional para el reto de Desarrollador de Soluciones con IA de Aztec: gestión de proyectos y tareas con detección automática de riesgo/bloqueo/falta de siguiente paso, y un criterio de priorización explícito y reproducible.

## Arquitectura

Este proyecto sigue una arquitectura de 3 capas (ver `CLAUDE.md` en esta misma carpeta para el detalle):

- **`directives/gestion_proyectos.md`** — el SOP: modelo de datos, criterio de riesgo y de priorización, en lenguaje natural. **Léelo primero** — ahí está la explicación completa del criterio de priorización.
- **`execution/`** — código Python determinista: importación de datos, motor de riesgo/prioridad (funciones puras, sin efectos secundarios) y la app web (Flask) que expone todo como CRUD + vista operativa.
- **`seed_data/`** — copia en CSV del dataset original de Aztec (de solo lectura), exportado una vez desde el `.xlsx` compartido.

## Cómo levantarlo

Requiere Python 3.9+ (usa `sqlite3` y `csv` de la librería estándar; la única dependencia externa es Flask).

```bash
cd aztec-pm
python3 -m venv .venv && source .venv/bin/activate   # opcional pero recomendado
pip install -r requirements.txt

python3 execution/import_dataset.py    # crea execution/aztec_pm.db desde seed_data/
python3 execution/webapp.py            # levanta el servidor en http://127.0.0.1:5050
```

Abre `http://127.0.0.1:5050` — ahí está la vista operativa con los 22 proyectos reales del dataset de Aztec más 5 proyectos sintéticos de ejemplo (ver más abajo por qué).

`import_dataset.py` reinicializa la base de datos por completo cada vez que se corre (útil en desarrollo/demo; ver advertencia en la directiva sobre no correrlo en producción sobre datos vivos).

## Ejemplos de proyectos con distintos estados y prioridades

Los 22 proyectos del dataset de Aztec ya traen variedad real (Sano/En riesgo/Bloqueado, distintos tipos de compromiso). Además, se siembran 5 proyectos sintéticos (`SYN-01` a `SYN-05`) con fechas ancladas a la fecha real del sistema (no a fechas históricas del dataset), pensados para mostrar explícitamente cada combinación:

| Código | Qué ilustra |
|---|---|
| `SYN-01` | Sano, con siguiente paso claro — caso "todo bien" |
| `SYN-02` | En riesgo por tarea vencida, fecha límite a 5 días — urgente pero no bloqueado |
| `SYN-03` | Bloqueado (dependencia externa) **y** sin siguiente paso — el peor caso combinado |
| `SYN-04` | Sano en salud, pero **sin siguiente paso definido** — muestra que la higiene operativa se detecta independientemente de la salud del proyecto |
| `SYN-05` | Cerrado, con fecha límite ya vencida — muestra que un proyecto cerrado no se marca en riesgo aunque su fecha haya pasado |

## Criterio de priorización (resumen — detalle completo en `directives/gestion_proyectos.md`)

Cada proyecto recibe un **score 0–100**, calculado en `execution/risk_engine.py` a partir de:

1. **Urgencia** de la fecha límite (vencida, ≤7 días, ≤30 días, sin fecha, o lejana).
2. **Impacto de negocio** (valor del proyecto, normalizado a USD).
3. **Severidad de riesgo** (Bloqueado > En riesgo > Sano).
4. **Carga crítica** (cantidad de tareas abiertas de prioridad Alta/Crítica).
5. **Tipo de compromiso** (un `Proyecto` con cliente pesa más que un `Mantenimiento` recurrente).
6. **Higiene operativa** (+10 si no hay un siguiente paso definido — la falta de claridad es en sí un riesgo).

El score se traduce en buckets **P0 (crítica) / P1 (alta) / P2 (media) / P3 (baja)**. Es una fórmula fija y explicable, no una preferencia subjetiva — cualquiera puede leer `risk_engine.py` y saber exactamente por qué un proyecto quedó en P0.

La vista operativa (`/`) ordena por este score de mayor a menor por defecto, y permite filtrar por salud, prioridad, responsable y "sin siguiente paso".

## Qué detecta el sistema automáticamente

- **Bloqueado**: hay una tarea abierta en estado "Bloqueada", o el campo de bloqueos tiene texto.
- **En riesgo**: la fecha límite ya pasó (y el proyecto sigue activo), o hay tareas abiertas vencidas.
- **Sin siguiente paso claro**: el campo "siguiente paso" está vacío — independiente de si el proyecto está sano o no.

Estos tres campos **no se guardan a mano**: se recalculan en cada consulta a partir de los datos vivos (fechas, bloqueos, tareas), para que nunca queden desincronizados de la realidad.

## Qué dejé fuera a propósito (dado el tiempo del reto)

- **Autenticación/multiusuario**: es un prototipo de un solo usuario/operador; no hay login.
- **Edición de tareas más allá de estado** (título, prioridad, fecha) desde la UI — se puede vía re-importación o directamente en SQLite; no era crítico para demostrar el criterio de priorización.
- **Historial de cambios de proyecto** (sí existe para notas, no para el resto de campos) — un log de auditoría completo es razonable en producción, pero no esencial para el prototipo.
- **Conversión de moneda en vivo**: se usa una tasa fija documentada (`COP_TO_USD = 1/4000`) en vez de una API de tipo de cambio, para mantener el motor de prioridad 100% determinista y sin dependencias externas.
- **Un campo de prioridad editable a mano**: se decidió que la prioridad sea siempre calculada (no una opinión guardada), para que el criterio de priorización sea consistente en todo el portafolio. Se puede ajustar el peso de sus factores en `risk_engine.py` si el negocio lo requiere.

## Nota sobre las fechas del dataset importado

El dataset de Aztec fue generado con una fecha de referencia interna distinta a la fecha real del sistema al momento de esta entrega. Por eso, varios de los 22 proyectos reales aparecerán como vencidos/en riesgo apenas se importan — es un efecto esperado de comparar datos históricos contra "hoy" real, no un error del motor. El detalle completo está documentado en `directives/gestion_proyectos.md`.
