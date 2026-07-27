# Directiva: Gestión de Proyectos y Priorización Operativa

> SOP de la Capa 1 (ver CLAUDE.md raíz). Define el qué y el porqué; la mecánica determinista vive en `execution/`.

## Objetivo

Mantener una vista única y confiable del portafolio de proyectos de una operación tipo Aztec: quién es responsable de qué, en qué estado va, qué es urgente, qué está bloqueado y qué le falta claridad. La vista debe permitir decidir en segundos qué revisar hoy, sin tener que leer cada proyecto uno por uno.

## Entradas

- `seed_data/projects.csv`, `seed_data/tasks.csv`, `seed_data/team.csv` — copia de solo lectura del dataset de Aztec, exportada una vez desde el `.xlsx` original. Nunca se edita a mano; si el dataset fuente cambia, se re-exporta y se vuelve a correr `execution/import_dataset.py`.
- Altas y ediciones manuales hechas por el usuario a través de la webapp (nuevos proyectos, cambios de estado, siguiente paso, bloqueos, notas).

## Modelo de datos

**Project**: `project_code`, `client_alias`, `project_name`, `engagement_type` (Proyecto / Diagnostico / Mantenimiento o recurrente), `owner_alias`, `status` (Activo / En pausa / Cerrado / Cancelado), `target_date`, `next_step`, `blockers`, `business_value`, `currency`, `start_date`, `stage`, `summary`.

**Task**: `task_code`, `project_code`, `assignee_alias`, `priority` (Baja/Media/Alta/Critica), `status` (Por hacer/En progreso/En revision/Bloqueada/Hecho), `due_date`, `title`, `detail`, `dependency`.

**ProjectNote**: log de notas con timestamp por proyecto (histórico, no se sobreescribe).

Deliberadamente **no se guardan** `health`, `priority`, `open_tasks` ni `overdue_tasks` como columnas editables a mano: son **derivados** por `risk_engine.py` a partir del resto de los datos en cada consulta, para que nunca queden desincronizados de la realidad. Lo que el usuario edita son los hechos (fechas, texto, estado); lo que el sistema calcula es el diagnóstico (riesgo, prioridad).

## Criterio de detección de riesgo (capa determinista, `risk_engine.py`)

Un proyecto se marca:

- **Bloqueado** si: tiene al menos una tarea abierta en estado `Bloqueada`, o el campo `blockers` tiene texto no vacío.
- **En riesgo** (y no bloqueado) si: `target_date` ya pasó y el proyecto sigue `Activo`, o tiene al menos una tarea abierta vencida (`due_date` < hoy).
- **Sano**: ninguna de las anteriores.
- **Sin siguiente paso claro**: `next_step` vacío o en blanco. Esto es independiente de salud/riesgo — un proyecto sano puede igual no tener claridad de qué sigue, y eso es en sí mismo un riesgo operativo (nadie sabe qué hacer mañana).

La fecha "hoy" usada para estas comparaciones es la fecha real del sistema en el momento de la consulta, no una fecha fija.

## Criterio de priorización

Se calcula un **score 0–100** por proyecto, explicable y reproducible (no es una preferencia subjetiva, es una fórmula fija):

| Factor | Regla | Puntos |
|---|---|---|
| Urgencia de fecha | `target_date` vencida | +40 |
| | vence en ≤7 días | +30 |
| | vence en ≤30 días | +15 |
| | sin `target_date` definida | +10 (la ambigüedad de fecha es en sí un riesgo) |
| | vence en >30 días | +5 |
| Impacto de negocio | `business_value` normalizado a USD, top tercio observado (≥25.000) | +20 |
| | tercio medio (12.000–24.999) | +12 |
| | tercio bajo (<12.000) o sin dato | +5 / 0 |
| Severidad de riesgo | Bloqueado | +25 |
| | En riesgo | +15 |
| | Sano | +0 |
| Carga crítica | +5 por cada tarea abierta con prioridad Alta o Crítica, tope +20 |
| Tipo de compromiso | `Proyecto` (entrega con cliente, ingreso en juego) | +10 |
| | `Diagnostico` (define alcance/venta futura) | +5 |
| | `Mantenimiento o recurrente` (servicio ya estable) | +0 |
| Higiene operativa | `next_step` vacío | +10 |

Score final capado en 100. Buckets:

- **P0 — Crítica** (≥70): revisar hoy.
- **P1 — Alta** (50–69): revisar esta semana.
- **P2 — Media** (30–49): seguimiento normal.
- **P3 — Baja** (<30): sin acción inmediata.

**Por qué esta fórmula y no otra:** combina lo urgente (fecha) con lo importante (valor de negocio + tipo de compromiso) y con la señal de que algo ya salió mal (riesgo/bloqueo), y penaliza explícitamente la falta de claridad operativa (sin siguiente paso) porque en la práctica ese es el fallo más silencioso — un proyecto puede verse "sano" en status y aun así estar parado porque nadie sabe qué sigue.

**Conversión de moneda:** el dataset mezcla USD y COP. Se normaliza con una tasa fija documentada en código (`COP_TO_USD = 1/4000`) — es una aproximación deliberada para hacer los montos comparables, no una tasa de mercado en vivo.

**Nota sobre fechas del dataset:** las fechas semilla (`seed_data/*.csv`) fueron generadas por Aztec con una fecha de referencia interna (~2026-07 temprano) distinta a la fecha real del sistema al momento de esta entrega. Al importar el dataset, varios proyectos legacy aparecerán automáticamente en riesgo/vencidos porque sus fechas ya pasaron respecto a "hoy" real — esto es esperado, no un bug, y de hecho demuestra que el motor de riesgo funciona sobre datos reales. Para mostrar el rango completo de estados (sano/en riesgo/bloqueado/sin siguiente paso) con fechas futuras "de verdad", se agregan proyectos sintéticos de ejemplo en `import_dataset.py`.

## Herramientas (Capa 3 — no reinventar, usar estas)

- `execution/import_dataset.py` — crea/reinicializa `execution/aztec_pm.db` desde `seed_data/*.csv` + siembra ejemplos sintéticos. Idempotente: se puede correr las veces que sea, siempre parte de cero.
- `execution/risk_engine.py` — funciones puras de cálculo de salud, "sin siguiente paso" y score de prioridad. Sin efectos secundarios; se puede testear con datos sueltos.
- `execution/db.py` — acceso a SQLite (esquema + queries compartidas).
- `execution/webapp.py` — servidor Flask: vista operativa (dashboard filtrable) + formularios de alta/edición de proyectos, tareas y notas.

## Casos extremos conocidos

- Proyecto sin `target_date`: no se asume que está sano; suma puntos de urgencia por ambigüedad (ver tabla).
- Proyecto sin `business_value`: se trata como impacto bajo (0 pts), no se descarta ni se hace fallar la carga.
- Tarea sin `assignee_alias`: válida, se muestra como "Sin asignar" — es información útil (nadie es responsable todavía).
- Reimportar el dataset borra proyectos/tareas creados a mano en la demo. Es intencional para desarrollo (`import_dataset.py` documenta esto); en producción real este script no se volvería a correr sobre datos vivos sin backup.

## Aprendizajes registrados

- 2026-07-27 — el dataset trae `is_overdue` precalculado con una fecha de referencia distinta a la real; el motor de riesgo recalcula siempre contra la fecha real del sistema, no confía en esa columna para nada nuevo.
- 2026-07-27 — dos proyectos del dataset (PRJ-18, PRJ-20) vienen en COP con montos ~4000x mayores que el resto en USD; sin normalizar por moneda, el score de impacto queda roto para esos dos.
