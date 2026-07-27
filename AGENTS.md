# Arquitectura de este proyecto

> Este archivo está replicado en CLAUDE.md, AGENTS.md y GEMINI.md para que las mismas instrucciones carguen en cualquier entorno de IA (misma convención que la carpeta raíz del reto).

Este sistema está organizado en 3 capas, para separar la intención (qué hacer y por qué) de la ejecución (código determinista):

- **`directives/`** — SOPs en Markdown. `directives/gestion_proyectos.md` define el modelo de datos, el criterio de detección de riesgo y la fórmula de priorización, en lenguaje natural. Es la fuente de verdad de las reglas de negocio: si cambia una regla de riesgo o de puntaje, se documenta ahí primero y luego se refleja en `execution/risk_engine.py`.
- **`execution/`** — scripts Python deterministas: `db.py` (esquema/acceso a SQLite), `import_dataset.py` (carga del dataset semilla), `risk_engine.py` (funciones puras de riesgo/prioridad, sin efectos secundarios) y `webapp.py` (rutas Flask: CRUD + vista operativa).
- **`tests/`** — pruebas de `risk_engine.py` con `unittest` de la librería estándar, sin tocar la base de datos.
- **`seed_data/`** — copia de solo lectura del dataset original de Aztec, exportada a CSV. Nunca se edita a mano.

**Por qué separar así:** la lógica de riesgo/prioridad debe ser la misma sin importar quién la corra o cuándo — por eso vive en funciones puras y testeables, no dispersa entre plantillas o rutas. La directiva es el contrato legible por humanos de esas reglas; el código es su implementación.

Antes de tocar `risk_engine.py`, correr `python3 -m unittest discover -s tests` y mantenerlo en verde; si cambia una regla de negocio, actualizar primero `directives/gestion_proyectos.md`.

Ver `README.md` para instrucciones de arranque, `CHANGELOG.md` para el historial de decisiones, y `directives/gestion_proyectos.md` para el detalle completo del criterio de priorización.
