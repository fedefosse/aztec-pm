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

**Diagnóstico persistido**: `health`, `priority_score`, `priority_bucket`, `priority_breakdown` (JSON) y `priority_computed_at` SÍ son columnas reales de `projects` — se guardan de verdad, no son un valor de lectura calculado al vuelo y descartado. Pero tampoco son editables a mano: nadie los tipea, `webapp.py::refresh_diagnosis` los recalcula con `risk_engine.py` y los graba con `db.update_priority_snapshot` en cada mutación que pueda afectarlos (alta/edición de proyecto, alta/cambio de estado/borrado de tarea) y también en cada carga del dashboard — así ni el simple paso del tiempo (una fecha límite que se vence sin que nadie toque nada) los deja desactualizados. Lo que el usuario edita son los hechos (fechas, texto, estado); lo que el sistema calcula **y graba** es el diagnóstico (riesgo, prioridad). Ver "Por qué se persiste, no solo se calcula" más abajo.

## Criterio de detección de riesgo (capa determinista, `risk_engine.py`)

Un proyecto se marca:

- **Bloqueado** si: tiene al menos una tarea abierta en estado `Bloqueada`, o el campo `blockers` tiene texto no vacío.
- **En riesgo** (y no bloqueado) si: `target_date` ya pasó y el proyecto sigue `Activo`, o tiene al menos una tarea abierta vencida (`due_date` < hoy).
- **Sano**: ninguna de las anteriores.
- **Sin siguiente paso claro**: `next_step` vacío o en blanco. Esto es independiente de salud/riesgo — un proyecto sano puede igual no tener claridad de qué sigue, y eso es en sí mismo un riesgo operativo (nadie sabe qué hacer mañana).
- **Orfandad operativa**: el proyecto está `Activo` pero no tiene ninguna tarea abierta. Es una señal distinta de "sin siguiente paso" (que mira el campo de texto): esta mira los hechos — nadie está moviendo el proyecto, tenga o no un siguiente paso anotado. En el dataset de Aztec es rara (1 de 27 proyectos al importar), lo cual es justamente lo que se espera de una alerta crítica: si fuera frecuente, dejaría de ser señal.

La fecha "hoy" usada para estas comparaciones es la fecha real del sistema en el momento de la consulta, no una fecha fija.

## Criterio de priorización — Índice de Tensión

Se calcula un **score 0–100** por proyecto ("Índice de Tensión"), explicable y reproducible (no es una preferencia subjetiva, es una fórmula fija):

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
| Orfandad operativa | `Activo` sin ninguna tarea abierta | +15 |

Score final capado en 100. Buckets:

- **P0 — Crítica** (≥70): revisar hoy.
- **P1 — Alta** (50–69): revisar esta semana.
- **P2 — Media** (30–49): seguimiento normal.
- **P3 — Baja** (<30): sin acción inmediata.

**Por qué esta fórmula y no otra:** combina lo urgente (fecha) con lo importante (valor de negocio + tipo de compromiso) y con la señal de que algo ya salió mal (riesgo/bloqueo), y penaliza explícitamente la falta de claridad operativa (sin siguiente paso) porque en la práctica ese es el fallo más silencioso — un proyecto puede verse "sano" en status y aun así estar parado porque nadie sabe qué sigue.

**Conversión de moneda:** el dataset mezcla USD y COP. Se normaliza con una tasa fija documentada en código (`COP_TO_USD = 1/4000`) — es una aproximación deliberada para hacer los montos comparables, no una tasa de mercado en vivo.

**Nota sobre fechas del dataset:** las fechas semilla (`seed_data/*.csv`) fueron generadas por Aztec con una fecha de referencia interna (~2026-07 temprano) distinta a la fecha real del sistema al momento de esta entrega. Al importar el dataset, varios proyectos legacy aparecerán automáticamente en riesgo/vencidos porque sus fechas ya pasaron respecto a "hoy" real — esto es esperado, no un bug, y de hecho demuestra que el motor de riesgo funciona sobre datos reales. Para mostrar el rango completo de estados (sano/en riesgo/bloqueado/sin siguiente paso) con fechas futuras "de verdad", se agregan proyectos sintéticos de ejemplo en `import_dataset.py`.

### Por qué se persiste, no solo se calcula

El reto pide explícitamente "guardar ... prioridad". La primera versión de este sistema la calculaba siempre al vuelo y nunca la escribía a disco — defendible en espíritu (nunca queda desincronizada), pero no cumple la letra del requisito: no había ninguna fila en la base con un valor de prioridad real. Se corrigió sin las dos salidas fáciles que hubieran sido "a medias":

- **No** un campo editable a mano (eso reintroduce el riesgo de que quede desactualizado y de que dos personas prioricen distinto por opinión).
- **No** un cache oportunista que solo se escribe "si alguien abre la página" (eso deja proyectos nunca visitados con el valor en `NULL`, que es peor que no tener el campo).

En cambio: se recalcula y se graba en cada mutación relevante (project/task upsert/delete) **y** en cada listado del dashboard, así el peor caso es "desactualizado por el tiempo que pasó desde la última vez que alguien miró el portafolio", no "nunca se calculó". `import_dataset.py` corre un cálculo inicial para los 27 proyectos apenas se siembra la base, así el valor existe desde el primer momento, sin depender de que alguien abra la webapp primero.

## Dashboard ejecutivo (`/`) — carga principal de la app

Pensado para responder tres preguntas rápido, con evidencia clickeable hasta el dato de origen — no solo un número:

1. **¿Dónde está el cuello de botella?** Salud del portafolio (donut), distribución de prioridad, distribución por tipo de compromiso, y ranking de proyectos por Índice de Tensión.
2. **¿Quién tiene más atraso que el resto?** `risk_engine.workload_by_person` — misma función que usa `/equipo`, no una copia con lógica que pueda divergir.
3. **¿Alguien tiene un proceso que valga la pena replicar?** `risk_engine.hygiene_stats_by_person` compara, por persona, el % de sus proyectos con siguiente paso definido contra el % de sus tareas abiertas vencidas — **dos señales por separado, no un índice único**, para poder distinguir "buen proceso" de "le tocó una carga más fácil". Incluye una nota de metodología visible en la propia página (correlación sobre el snapshot actual, no una serie histórica — el dataset no tiene timestamps de cambio de estado).

Todo en la página es navegación real: cada tarjeta KPI, gajo del donut y fila de ranking lleva a los proyectos/tareas que la componen en `/proyectos` o en el detalle del proyecto — nunca es un número sin forma de auditarlo.

### Filtros combinables, no excluyentes (y facetados)

Todas las rutas con filtros (`/`, `/proyectos`, `/equipo`) comparten el mismo vocabulario de filtro (`health`, `bucket`, `owner`, `engagement_type`, `no_next_step`, `orphaned`) vía `webapp.read_filters`/`webapp.apply_filters`, con lógica AND: elegir "Bloqueados" y después un responsable **combina** ambos (`?health=Bloqueado&owner=...`), no reemplaza uno por el otro. Esto corrigió un bug real: los links de las tarjetas KPI armaban su URL con `url_for(endpoint, health='Bloqueado')`, que por diseño de Flask solo incluye los parámetros que se le pasan explícitamente — cualquier otro filtro ya activo en la URL actual se perdía. `webapp.filter_link(endpoint, filtros_actuales, **cambios)` (registrado como global de Jinja) es ahora el único mecanismo para armar esos links: parte de los filtros activos y aplica el cambio pedido (`None` = quitar ese filtro, cualquier otro valor = ponerlo), nunca reemplaza desde cero.

Las tarjetas KPI del dashboard ejecutivo muestran conteos **facetados** (`webapp.faceted_summary`): cada tarjeta se calcula aplicando todos los filtros activos **menos el suyo propio** (`apply_filters(rows, filters, exclude=("health",))` para la tarjeta de salud, por ejemplo) — así "Bloqueados" con un responsable ya filtrado muestra los bloqueados *de ese responsable*, no el total fijo del portafolio. Es el mismo patrón que un buscador de e-commerce con filtros a la izquierda: cada opción muestra cuántos resultados habría si además la eligieras.

## Interactividad (`static/live-filters.js`)

Los filtros de `/`, `/proyectos` y `/equipo` aplican al instante (sin recargar la página) vía un único script vanilla, sin frameworks ni build step: intercepta el `submit` del formulario de filtros y los `click` de los links marcados `data-live-link`, hace `fetch()` de la misma URL con la nueva query string, y reemplaza solo los bloques del DOM marcados por id (`data-live-target="id1,id2,..."`, admite varias secciones a la vez) con lo que el servidor devolvió. El servidor sigue siendo la única fuente de verdad — esto solo evita el reload completo. Si JS falla o está desactivado, el formulario se degrada a un GET normal (recarga completa), que sigue funcionando exactamente igual. En `/dashboard` (ahora `/`), los campos que no tienen un `<select>`/checkbox propio en el formulario (`health`, `bucket`, `no_next_step`, `orphaned`, seteados por click en una tarjeta/gajo/barra) viajan como `<input type="hidden">` — si no estuvieran ahí, cambiar el filtro de responsable en el `<select>` habría hecho perder esos otros filtros al enviar el formulario (mismo tipo de bug que el de los links, pero por el lado del form).

## Herramientas (Capa 3 — no reinventar, usar estas)

- `execution/import_dataset.py` — crea/reinicializa `execution/aztec_pm.db` desde `seed_data/*.csv` + siembra ejemplos sintéticos + calcula y graba el diagnóstico inicial de los 27 proyectos. Idempotente: se puede correr las veces que sea, siempre parte de cero.
- `execution/risk_engine.py` — funciones puras de cálculo de salud, prioridad, mapa de bloqueos, carga por persona (`workload_by_person`), higiene operativa por persona (`hygiene_stats_by_person`), y distribuciones para las gráficas (`health_distribution`, `priority_distribution`, `engagement_distribution`). Sin efectos secundarios; se puede testear con datos sueltos.
- `execution/db.py` — acceso a SQLite (esquema + queries compartidas + `update_priority_snapshot` para persistir el diagnóstico).
- `execution/webapp.py` — servidor Flask: dashboard ejecutivo (`/`, carga principal), vista operativa (`/proyectos`) y carga del equipo (`/equipo`, calculada en vivo desde `tasks` vía `risk_engine.workload_by_person` — una sola implementación, no una copia por página) + formularios de alta/edición/eliminación de proyectos, tareas y notas. Toda entrada de usuario se valida contra las listas de valores permitidos antes de tocar la base (ver "Validación de entradas" abajo). `refresh_diagnosis`/`refresh_diagnosis_for` son el único punto donde se recalcula y graba el diagnóstico — cualquier ruta nueva que cree/edite/borre un proyecto o una tarea tiene que llamarlas. `read_filters`/`apply_filters`/`faceted_summary`/`filter_link` son el único mecanismo de filtrado — cualquier vista nueva con filtros debe reutilizarlos, no reimplementar su propia lógica de query params.

### Efecto dominó: el campo `dependency` va al revés de lo intuitivo

El campo `dependency` de una tarea guarda el título de su **prerrequisito** (la tarea de la que depende), no algo que ella misma bloquee. Es fácil leerlo al revés — la primera versión de la vista de equipo lo hizo. `risk_engine.py::compute_blocking_map` invierte la relación correctamente: para cada tarea, calcula cuántas otras tareas *abiertas* del mismo proyecto dependen de ella (el emparejamiento es por título y solo dentro del mismo proyecto, porque el dataset reutiliza los mismos nombres de tarea-arquetipo en distintos proyectos). Esas son las tareas que de verdad importa resolver primero: mientras sigan abiertas, frenan a otras. Una tarea `Hecha` deja de bloquear a nadie. Se usa tanto en `/equipo` (para ordenar la cola de cada persona) como en el detalle de cada proyecto (columna "Bloquea a").

### Validación de entradas

Todo dato que entra por un formulario se valida contra las listas de valores permitidos (`engagement_type`, `status`, `currency`, `priority`, `status` de tarea) antes de llegar a `db.py` — un valor fuera de esas listas antes rompía con un error de integridad de SQLite sin capturar. El código de proyecto debe ser no vacío y solo `[A-Za-z0-9_-]+` (evita que un código con `/` rompa el enrutamiento, y evita que un código vacío se guarde como fila fantasma — SQLite permite múltiples `NULL` en una clave primaria no-`INTEGER`). Crear un proyecto con un código ya existente se rechaza con un mensaje, en vez de sobreescribirlo en silencio.

## Casos extremos conocidos

- Proyecto sin `target_date`: no se asume que está sano; suma puntos de urgencia por ambigüedad (ver tabla).
- Proyecto sin `business_value`: se trata como impacto bajo (0 pts), no se descarta ni se hace fallar la carga.
- Tarea sin `assignee_alias`: válida, se muestra como "Sin asignar" — es información útil (nadie es responsable todavía).
- Reimportar el dataset borra proyectos/tareas creados a mano en la demo. Es intencional para desarrollo (`import_dataset.py` documenta esto); en producción real este script no se volvería a correr sobre datos vivos sin backup.
- `business_value` no numérico (dato corrupto, no solo ausente): `to_usd()` lo trata igual que "sin dato" (0 puntos de impacto) en vez de fallar — antes reventaba el cálculo de *todo* el portafolio en cada carga del dashboard, no solo el de ese proyecto.
- Crear/editar un proyecto con un valor fuera de las listas permitidas, o con un código de proyecto vacío/con `/`: se rechaza con un error legible y se re-muestra el formulario con lo ya tecleado, en vez de un error 500 o una fila fantasma.
- Crear una tarea con un `assignee_alias` que no está en el roster: se rechaza (antes solo el `<select>` de la UI lo impedía; una petición directa igual podía colar un alias inválido que después desaparecía en silencio de `/equipo`).
- Código de tarea nueva: se genera probando `T01`, `T02`, ... hasta encontrar uno libre, no asumiendo que "código libre = cantidad de tareas existentes + 1". Si se borra una tarea intermedia, ese número vuelve a estar "libre" según el conteo pero el código ya existió — asumirlo generaba una colisión silenciosa (`upsert_task` actualizaba la tarea vieja en vez de crear una nueva, pérdida de datos sin ningún error visible).

## Aprendizajes registrados

- 2026-07-27 — el dataset trae `is_overdue` precalculado con una fecha de referencia distinta a la real; el motor de riesgo recalcula siempre contra la fecha real del sistema, no confía en esa columna para nada nuevo.
- 2026-07-27 — dos proyectos del dataset (PRJ-18, PRJ-20) vienen en COP con montos ~4000x mayores que el resto en USD; sin normalizar por moneda, el score de impacto queda roto para esos dos.
- 2026-07-27 — se evaluó un plan alternativo (Next.js + JSON + n8n) para el mismo reto. Se descartó el cambio de stack: contradecía el mandato explícito de mantener la ejecución en scripts Python deterministas dentro de `execution/`, y reescribir habría descartado un prototipo ya probado end-to-end sin ganar valor de negocio real. Sí se incorporaron las ideas de negocio de ese plan que no requerían cambiar de stack: la señal de "orfandad operativa" (Activo + 0 tareas abiertas), la vista de carga del equipo, y el "efecto dominó". Lección: un plan alternativo puede aportar criterio de negocio sin forzar a adoptar su arquitectura.
- 2026-07-27 — el campo `dependency` del dataset de tareas se leyó al revés en la primera implementación del "efecto dominó" (se asumió que una tarea *con* dependencia era la que bloqueaba a otras). Verificado contra los datos: el 100% de las tareas con `dependency` no vacía referencian el título de OTRA tarea del mismo proyecto de la que dependen — es decir, el campo guarda el prerrequisito, no lo que la tarea bloquea. **Por qué importa:** antes de construir lógica de negocio sobre un campo de relación de un dataset ajeno, verificar la dirección de la relación contra los datos reales (ej. ¿el valor matchea el título de otra fila?), no asumirla por el nombre del campo.
- 2026-07-27 — una auditoría adversarial de un agente Explore (fresh eyes, sin el contexto de haber escrito el código) encontró 7 problemas reales antes de publicar: un `business_value` no numérico rompía todo el dashboard (no solo un proyecto), `debug=True` quedaba prendido por defecto, no había validación de enums/código de proyecto (permitía filas fantasma y colisiones silenciosas), el alias de responsable en el formulario de tarea era texto libre (typos invisibles en `/equipo`), y no existían pruebas automatizadas pese a que la directiva ya prometía que el motor "se puede testear". **Por qué importa:** antes de dar por "impecable" un prototipo que uno mismo construyó, vale la pena una revisión de alguien (o algo) sin el contexto de haberlo escrito — el autor tiende a no ver los huecos que dejó.
- 2026-07-27 — una segunda pasada de revisión (código + `/simplify` + `/security-review` + revisión final de un agente independiente) encontró un bug real de pérdida de datos silenciosa: el código de una tarea nueva se generaba como "cantidad de tareas existentes + 1", que puede colisionar con un código ya usado si se borró una tarea intermedia — `upsert_task` toma esa colisión como una actualización, no como un error. También encontró documentación desactualizada (número de pruebas, una afirmación del README sobre qué es editable que ya no era cierta). **Por qué importa:** hacer una ronda de revisión no es suficiente para "impecable" — cada ronda de fixes puede introducir bugs nuevos (el propio `task_delete` de esta ronda fue lo que expuso el bug de colisión de códigos) y desactualizar la documentación que se acababa de escribir. Vale la pena una revisión final holística (no solo del diff) antes de publicar.
- 2026-07-27 — "prioridad calculada pero nunca guardada" no satisfacía la letra del requisito del reto ("guardar ... prioridad"), aunque sí su espíritu. El usuario fue explícito: si no se guarda, tiene que ser completo, no a medias. La media tinta que había que evitar era cachear el valor solo cuando alguien abre la página (deja proyectos nunca vistos en `NULL`) o guardarlo sin mantenerlo sincronizado con cambios en las tareas. La solución completa recalcula y graba en cada mutación relevante (proyecto Y tarea) más en cada listado del dashboard, y `import_dataset.py` corre un cálculo inicial — así el valor persistido existe desde el primer momento y nunca depende de que alguien lo haya "mirado" antes. **Por qué importa:** cuando un requisito se cumple "en espíritu" pero no "en la letra", vale la pena preguntar cuál de los dos es el que realmente están evaluando, en vez de asumir que el espíritu alcanza.
- 2026-07-27 — un reporte de "los filtros no funcionan" resultó ser, verificado con `curl` uno por uno, un problema de percepción/UX, no un bug real: el backend filtraba correctamente en los 6 casos probados, pero el formulario requería un click aparte en "Filtrar" después de elegir una opción, sin ninguna señal visible de que el cambio se había registrado. **Por qué importa:** antes de asumir que un reporte de "no funciona" es un bug de lógica, vale la pena reproducirlo capa por capa (backend primero, con curl) — a veces "no funciona" quiere decir "no se siente como que funciona", que es un problema real pero distinto, y armar el fix equivocado (perseguir un bug de backend inexistente) hubiera sido tiempo perdido.
- 2026-07-27 — un segundo reporte, esta vez sí un bug real: los links de las tarjetas KPI armaban su URL con `url_for(endpoint, health='Bloqueado')`, que en Flask solo incluye los parámetros que se le pasan — cualquier otro filtro ya activo (ej. responsable) se perdía al hacer click. Además, en el dashboard ejecutivo esas tarjetas apuntaban a la ruta operativa en vez de filtrar la propia página. **Por qué importa:** un helper que arma URLs a partir de "los filtros actuales + un cambio" (no desde cero) es infraestructura, no un detalle de una sola página — se centralizó en `filter_link` para que no se pudiera repetir el mismo bug en cada vista nueva que agregue filtros.
- 2026-07-27 — el usuario pidió que las tarjetas KPI mostraran "los datos relacionados" con el resto de la selección, no un total fijo — eso llevó a conteos facetados (`faceted_summary`): cada tarjeta se calcula excluyendo su propio filtro del resto de la selección activa. Es el mismo patrón de un buscador con filtros a la izquierda (cada opción muestra cuántos resultados tendría si la sumaras). En la misma conversación pidió que el dashboard ejecutivo pasara a ser la carga principal (`/`) — se renombraron los endpoints Flask (`dashboard` = ejecutivo en `/`, `operational_view` = tabla en `/proyectos`) en vez de agregar un redirect, para que `url_for('dashboard')` siguiera significando "la página principal" en todas las plantillas sin tener que auditar cada referencia por separado.
