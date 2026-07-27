# Aztec PM — Sistema de Gestión de Proyectos

Prototipo funcional para el reto de Desarrollador de Soluciones con IA de Aztec: gestión de proyectos y tareas con detección automática de riesgo/bloqueo/falta de siguiente paso, un criterio de priorización explícito y **persistido** (no solo calculado), y un dashboard ejecutivo para identificar cuellos de botella y comparar carga entre el equipo con evidencia, no solo intuición.

## Arquitectura

Este proyecto sigue una arquitectura de 3 capas (ver `CLAUDE.md` en esta misma carpeta para el detalle):

- **`directives/gestion_proyectos.md`** — el SOP: modelo de datos, criterio de riesgo y de priorización, en lenguaje natural. **Léelo primero** — ahí está la explicación completa del criterio de priorización.
- **`execution/`** — código Python determinista: importación de datos, motor de riesgo/prioridad/analytics (funciones puras, sin efectos secundarios) y la app web (Flask) que expone todo como CRUD + vista operativa + dashboard ejecutivo. `static/live-filters.js` es el único JavaScript del proyecto (filtrado instantáneo, sin frameworks).
- **`tests/`** — pruebas de `risk_engine.py` y de las funciones puras de `webapp.py` (`unittest` estándar, sin tocar la base de datos).
- **`seed_data/`** — copia en CSV del dataset original de Aztec (de solo lectura), exportado una vez desde el `.xlsx` compartido.
- **`CHANGELOG.md`** — historial de decisiones de este prototipo, en orden.

## Cómo levantarlo

Requiere Python 3.9+ (usa `sqlite3` y `csv` de la librería estándar; la única dependencia externa es Flask).

```bash
cd aztec-pm
python3 -m venv .venv && source .venv/bin/activate   # opcional pero recomendado
pip install -r requirements.txt

python3 execution/import_dataset.py    # crea execution/aztec_pm.db desde seed_data/
python3 execution/webapp.py            # levanta el servidor en http://127.0.0.1:5050
```

Abre `http://127.0.0.1:5050` — ahí está la vista operativa con los 22 proyectos reales del dataset de Aztec más 5 proyectos sintéticos de ejemplo (ver más abajo por qué). El dashboard ejecutivo está en `http://127.0.0.1:5050/dashboard`.

`import_dataset.py` reinicializa la base de datos por completo cada vez que se corre (útil en desarrollo/demo; ver advertencia en la directiva sobre no correrlo en producción sobre datos vivos).

Por defecto el servidor corre sin el debugger de Flask (no es seguro dejarlo activo por defecto en un repo público), y solo escucha en `127.0.0.1`. Las rutas de eliminar no llevan token CSRF — aceptable para un prototipo local de un solo usuario, pero evita navegar sitios no confiables mientras el servidor esté corriendo en la misma máquina. Para desarrollo con recarga automática y depurador interactivo:

```bash
AZTEC_PM_DEBUG=1 python3 execution/webapp.py
```

### Cómo correr las pruebas

```bash
python3 -m unittest discover -s tests
```

Cubren las funciones puras de `execution/risk_engine.py` (parseo de fechas, conversión de moneda, umbrales de urgencia, reglas de salud, higiene operativa y el mapa de dependencias) y de `execution/webapp.py` (generación de código de tarea sin colisiones), todo sin tocar la base de datos.

## Ejemplos de proyectos con distintos estados y prioridades

Los 22 proyectos del dataset de Aztec ya traen variedad real (Sano/En riesgo/Bloqueado, distintos tipos de compromiso). Además, se siembran 5 proyectos sintéticos (`SYN-01` a `SYN-05`) con fechas ancladas a la fecha real del sistema (no a fechas históricas del dataset), pensados para mostrar explícitamente cada combinación:

| Código | Qué ilustra |
|---|---|
| `SYN-01` | Sano, con siguiente paso claro — caso "todo bien" |
| `SYN-02` | En riesgo por tarea vencida, fecha límite a 5 días — urgente pero no bloqueado |
| `SYN-03` | Bloqueado (dependencia externa) **y** sin siguiente paso — el peor caso combinado |
| `SYN-04` | Sano en salud, pero **sin siguiente paso definido** — muestra que la higiene operativa se detecta independientemente de la salud del proyecto |
| `SYN-05` | Cerrado, con fecha límite ya vencida — muestra que un proyecto cerrado no se marca en riesgo aunque su fecha haya pasado |

## Criterio de priorización — Índice de Tensión (resumen — detalle completo en `directives/gestion_proyectos.md`)

Cada proyecto recibe un **Índice de Tensión de 0–100**, calculado en `execution/risk_engine.py` a partir de:

1. **Urgencia** de la fecha límite (vencida, ≤7 días, ≤30 días, sin fecha, o lejana).
2. **Impacto de negocio** (valor del proyecto, normalizado a USD).
3. **Severidad de riesgo** (Bloqueado > En riesgo > Sano).
4. **Carga crítica** (cantidad de tareas abiertas de prioridad Alta/Crítica).
5. **Tipo de compromiso** (un `Proyecto` con cliente pesa más que un `Mantenimiento` recurrente).
6. **Higiene operativa** (+10 si no hay un siguiente paso definido — la falta de claridad es en sí un riesgo).
7. **Orfandad operativa** (+15 si el proyecto está `Activo` pero no tiene ninguna tarea abierta — nadie lo está moviendo).

El score se traduce en buckets **P0 (crítica) / P1 (alta) / P2 (media) / P3 (baja)**. Es una fórmula fija y explicable, no una preferencia subjetiva — cualquiera puede leer `risk_engine.py` y saber exactamente por qué un proyecto quedó en P0.

La vista operativa (`/`) ordena por este índice de mayor a menor por defecto, y permite filtrar por salud, prioridad, responsable, "sin siguiente paso" y "activos sin tareas abiertas".

## Qué detecta el sistema automáticamente

- **Bloqueado**: hay una tarea abierta en estado "Bloqueada", o el campo de bloqueos tiene texto.
- **En riesgo**: la fecha límite ya pasó (y el proyecto sigue activo), o hay tareas abiertas vencidas.
- **Sin siguiente paso claro**: el campo "siguiente paso" está vacío — independiente de si el proyecto está sano o no.
- **Orfandad operativa**: el proyecto está `Activo` pero no tiene ninguna tarea abierta — señal distinta de la anterior porque mira los hechos (tareas), no el texto declarado.

Ninguno de estos campos se guarda **a mano** — pero sí se guardan de verdad, en columnas reales de la tabla `projects` (`health`, `priority_score`, `priority_bucket`, `priority_breakdown`, `priority_computed_at`). Se recalculan y se graban en cada mutación que pueda afectarlos (alta/edición de proyecto, alta/cambio/borrado de tarea) y también en cada carga del dashboard, para que ni siquiera el simple paso del tiempo los deje desactualizados. Se puede verificar directamente en SQLite sin pasar por la webapp — apenas se corre `import_dataset.py`, los 27 proyectos ya tienen su prioridad calculada y persistida:

```bash
python3 -c "
import sys; sys.path.insert(0, 'execution')
import db
conn = db.get_conn()
p = db.get_project(conn, 'PRJ-01')
print(p['health'], p['priority_score'], p['priority_bucket'], p['priority_computed_at'])
"
```

## Dashboard ejecutivo (`/dashboard`)

Página aparte de la vista operativa, pensada para responder rápido — con evidencia clickeable, no solo un número suelto:

- **Salud del portafolio**: donut (Bloqueado/En riesgo/Sano), cada gajo lleva a esos proyectos filtrados en `/`.
- **Top proyectos en riesgo**: ranking por Índice de Tensión.
- **Carga por persona**: quién tiene más atraso relativo al resto del equipo (misma función que `/equipo`, reutilizada, no una copia).
- **Evidencia — higiene operativa**: por persona, % de sus proyectos con siguiente paso definido vs. % de sus tareas abiertas vencidas, mostradas por separado (no mezcladas en un solo índice) para poder distinguir "tiene un buen proceso" de "le tocó una carga más fácil", con una nota de metodología visible en la página.
- **Tareas que están frenando a otras**: ranking de "efecto dominó".

Tiene un filtro por responsable ("Enfocar en: ...") que reduce las cinco secciones a una sola persona a la vez, y aplica al instante (ver abajo).

## Filtros instantáneos, sin recargar la página

Los filtros de `/` y `/dashboard` aplican al instante: un único script vanilla (`static/live-filters.js`, sin frameworks ni build step) intercepta el formulario y los links de las tarjetas KPI, pide la misma URL con la nueva query string, y reemplaza solo los bloques necesarios del DOM con lo que el servidor devolvió. Si JS falla o está desactivado, los filtros se degradan a un GET normal (recarga completa) — siguen funcionando igual, solo sin la parte instantánea.

## Vista de equipo (`/equipo`)

Carga operativa por persona, calculada en vivo desde las tareas (no desde los contadores estáticos de `seed_data/team.csv`, para que nunca queden desactualizados): tareas abiertas, bloqueadas y de prioridad alta/crítica por responsable.

Dentro de la cola de cada persona, las tareas de las que **dependen otras tareas abiertas** flotan al inicio ("efecto dominó" — si no avanzan, frenan trabajo de alguien más), con una etiqueta de a cuántas tareas bloquean. Importante: el campo `dependency` de una tarea guarda su **prerrequisito** (el título de la tarea de la que depende), no algo que ella misma bloquee — es fácil leerlo al revés. `execution/risk_engine.py::compute_blocking_map` invierte la relación correctamente (ver también el mismo indicador en el detalle de cada proyecto).

## Qué dejé fuera a propósito (dado el tiempo del reto)

- **Autenticación/multiusuario**: es un prototipo de un solo usuario/operador; no hay login.
- **Edición de tareas más allá de estado** (título, prioridad, fecha, responsable) desde la UI una vez creadas — el responsable solo se fija al crear la tarea; cambiarlo después requiere re-importar o editar directamente en SQLite. No era crítico para demostrar el criterio de priorización. (Sí se puede crear, cambiar de estado y **eliminar** tareas y proyectos desde la UI.)
- **Historial de cambios de proyecto** (sí existe para notas, no para el resto de campos) — un log de auditoría completo es razonable en producción, pero no esencial para el prototipo.
- **Conversión de moneda en vivo**: se usa una tasa fija documentada (`COP_TO_USD = 1/4000`) en vez de una API de tipo de cambio, para mantener el motor de prioridad 100% determinista y sin dependencias externas.
- **Un campo de prioridad editable a mano**: se decidió que la prioridad se calcule siempre igual para todo el portafolio (no una opinión tecleada por cada quien), y que ese cálculo se persista automáticamente en cada mutación relevante — ver "Qué detecta el sistema automáticamente" más arriba para el detalle de cómo se guarda. Se puede ajustar el peso de sus factores en `risk_engine.py` si el negocio lo requiere.
- **Evidencia de buenas prácticas como serie histórica**: el dashboard ejecutivo compara higiene operativa por persona sobre el estado *actual* del portafolio, no sobre cuánto tardó cada quien en cada tarea — el dataset no tiene esos timestamps. Es una correlación observada, documentada como tal en la propia página, no una afirmación de causalidad.
- **Stack Next.js/React + mock en JSON + automatización con n8n**: se evaluó como alternativa y se descartó a propósito. Habría significado reescribir un prototipo ya probado end-to-end sin ganar precisión de negocio real, y se aleja de mantener la lógica de riesgo/prioridad en un único lugar determinista y testeable (`risk_engine.py`). Las ideas de negocio de valor de esa alternativa sí se incorporaron sobre el stack actual (ver "Orfandad operativa" y "Vista de equipo" arriba).

## Notas sobre la calidad de los datos importados

- **Fechas**: el dataset de Aztec fue generado con una fecha de referencia interna distinta a la fecha real del sistema al momento de esta entrega. Por eso, varios de los 22 proyectos reales aparecerán como vencidos/en riesgo apenas se importan — es un efecto esperado de comparar datos históricos contra "hoy" real, no un error del motor.
- **Moneda mixta**: dos proyectos (`PRJ-18`, `PRJ-20`) vienen en COP con montos ~4000x mayores que el resto (en USD); se normalizan con una tasa fija documentada antes de calcular impacto.
- **El campo `dependency` de las tareas estaba invertido en mi primera lectura**: no es "esto bloquea a otros", es "esto depende de otra tarea" — el texto es el título de su prerrequisito dentro del mismo proyecto. `compute_blocking_map` en `risk_engine.py` invierte la relación para encontrar qué tareas son en realidad el cuello de botella (de las que depende más de una tarea abierta).

El detalle completo de estos tres puntos está documentado en `directives/gestion_proyectos.md` y en el registro de aprendizajes del `CLAUDE.md` raíz del reto.
