# Coima

Plataforma de inteligencia anticorrupción para las compras públicas argentinas
([comprar.gob.ar](https://comprar.gob.ar) y
[contratar.gob.ar](https://contratar.gob.ar)).

*Read in [English](README.md).*

> **Importante — leer primero.** Coima analiza datos **públicos** de compras públicas
> y produce **indicadores de riesgo estadísticos y heurísticos**. Sus chequeos, puntajes,
> alertas y hallazgos resaltan *patrones que pueden ameritar revisión*; **no son acusaciones
> ni prueba** de que una persona o empresa haya cometido algún delito o irregularidad. Lea
> [DISCLAIMER.md](DISCLAIMER.md) antes de usar el software o los datos.

## Demo en vivo

Hay una instancia pública en **[coima-demo.com](https://coima-demo.com)**. Sirve
**datos reales** extraídos de los portales oficiales, pero con los **nombres
censurados**: compradores, proveedores y funcionarios se muestran bajo seudónimos
estables, de modo que los patrones e indicadores de riesgo son genuinos sin que se
atribuya ningún nombre real a un hallazgo. La demo es de solo lectura y no expone
el control del scraper ni las herramientas de investigación.

## Objetivo

Los datos de compras públicas se publican proceso por proceso, sin forma de ver
patrones entre compradores, proveedores y tiempo. Coima extrae esos datos hacia
un grafo, corre sobre él una batería de detectores de señales de alerta
(ganadores en serie, patrones de competencia anómalos, indicadores de rotación
de ofertas, posible fraccionamiento de contratos, clústeres de contactos
compartidos, indicadores de sesgo de autorizantes, etc.), asigna puntajes de
riesgo a los proveedores y expone todo a través de un panel con un espacio de
investigación asistido por IA.

El objetivo es convertir registros de licitaciones dispersos en **pistas
priorizadas y consultables para revisión humana** por periodistas y auditores,
no etiquetar a nadie como culpable (ver [DISCLAIMER.md](DISCLAIMER.md)).

## Cómo funciona

```
comprar.gob.ar ──┐
                 ├──> scraper ──> grafo Neo4j ──> detectores ──> puntajes ──> UI
contratar.gob.ar ┘                (sistema de     (una consulta   (SQLite)
                                   registro)       Cypher c/u)
```

1. El **scraper** recorre cada proceso de compra y sus subpáginas, y escribe el
   resultado en Neo4j con `MERGE`, de modo que las ejecuciones son idempotentes
   y reanudables. También carga nodos de inflación (INDEC) y tipo de cambio
   (BCRA) para poder comparar montos entre años.
2. Neo4j es el **sistema de registro**: cada entidad (proceso, comprador,
   proveedor, oferta, orden de compra, funcionario) es un nodo, y cada detector
   es una consulta de grafo sobre sus relaciones.
3. Una **ejecución de detección** corre todos los chequeos habilitados, guarda
   sus hallazgos y los puntajes de riesgo derivados por proveedor en SQLite bajo
   un mismo id de ejecución, y la marca como completada.
4. La **API** sirve la última ejecución completada, así la UI es rápida y nunca
   espera a Neo4j.

## Módulos

| Carpeta | Qué es | Más información |
|---|---|---|
| `scraper/` | Extrae datos de ambos portales de compras e ingiere datos estructurados en Neo4j. Corre como CLI de una sola ejecución o como supervisor controlable desde el backend. | [scraper/README.md](scraper/README.md) · [SCHEMA.md](scraper/SCHEMA.md) |
| `backend/` | Servicio FastAPI y motor de detección: corre los detectores, calcula puntajes de riesgo, sirve perfiles de entidades y datos de grafo, gestiona investigaciones asistidas por IA y controla el scraper. | [backend/README.md](backend/README.md) · [CHECKS.md](backend/src/detector/checks/CHECKS.md) |
| `frontend/` | Aplicación de página única en React + Vite: panel, puntajes de riesgo, hallazgos de chequeos, perfiles de entidades, explorador de grafo, control del scraper y espacio de investigación. | [frontend/README.md](frontend/README.md) |
| `infra/` | Docker Compose, Dockerfiles por servicio y la configuración de nginx que une las cuatro piezas. | — |

> Los README de cada módulo están en inglés, igual que los comentarios del código.

El backend y el scraper corren como **contenedores separados** y se coordinan a
través de un volumen compartido (`control.json` / `run_status.json`); el backend
nunca lanza el proceso del scraper directamente.

## Inicio rápido (Docker)

```bash
cp .env.example .env          # opcional — los valores por defecto funcionan de fábrica
docker compose --env-file .env -f infra/docker-compose.yml up --build
```

Luego abrir:

- Frontend: http://localhost:8080
- Documentación de la API: http://localhost:8000/docs
- Navegador de Neo4j: http://localhost:7474 (usuario `neo4j`, contraseña desde `.env`)

Detener con `Ctrl+C`; `docker compose ... down` para eliminar los contenedores
(los volúmenes persisten). Agregar `-v` para también borrar los datos de Neo4j y
el progreso del scraper.

> Este stack está pensado para **uso local o de confianza**: publica Neo4j y el
> backend en el host y deja abierta la superficie de administración. No lo
> expongas a internet tal cual está — ver [SECURITY.md](SECURITY.md).

## Controlar el scraper

Abrir la página **Scraper** en el frontend. Muestra si hay una ejecución activa,
cuántos procesos se han extraído en total y cuántos apuntó la última ejecución,
con botones **Start** / **Stop**. Por debajo:

- `POST /api/scraper/start` escribe un comando `run`; el supervisor del scraper
  lo recoge en ~2s y comienza a extraer.
- `POST /api/scraper/stop` escribe un comando `stop`; el proceso actual termina,
  el lote de Neo4j se descarga y el progreso se guarda (limpio, reanudable).
- `GET /api/scraper/status` lee el `run_status.json` en vivo.

### Sembrar progreso de extracción existente

El scraper reanuda desde `progress.json` en su volumen de salida; un volumen
nuevo empieza desde cero. Para trasladar un archivo de progreso existente:

```bash
docker compose -f infra/docker-compose.yml cp \
  scraper/output/progress.json scraper:/data/scraper-output/progress.json
```

(o `docker cp <progress.json> <scraper-container>:/data/scraper-output/`).

## Desarrollo local (sin Docker)

```bash
# Backend — http://localhost:8000
cd backend && pip install -r requirements.txt && python run.py --api

# Frontend — http://localhost:5173, hace proxy de /api a :8000
cd frontend && npm install && npm run dev

# Scraper — CLI de una sola ejecución, o el bucle de servicio controlable
cd scraper && pip install -r requirements.txt
python main.py --help
python supervisor.py
```

Para ejecuciones locales, configurar `COIMA_NEO4J_URI` / `COIMA_NEO4J_PASSWORD`
y, para el canal de archivos backend↔scraper, apuntar ambos al mismo directorio
vía `COIMA_OUTPUT_DIR` (scraper) y `COIMA_SCRAPER_CONTROL_DIR` (backend).

Los detalles de instalación, estructura y pruebas de cada módulo están en su
propio README.

## Configuración

Todos los ajustes usan el prefijo de entorno `COIMA_`; ver
[`.env.example`](.env.example) para la lista completa, y los README de cada
módulo para saber qué lee cada servicio.

La configuración de detección (qué chequeos están activos, sus pesos y umbrales)
se deriva de los chequeos registrados y se superpone con overrides del usuario
editados desde la página de Configuración y almacenados en SQLite. La CLI
`run.py --detect` es un camino aparte y lee `backend/config.json` directamente.

## Fuentes de datos

- **Compras:** [comprar.gob.ar](https://comprar.gob.ar) (bienes y servicios) y
  [contratar.gob.ar](https://contratar.gob.ar) (obra pública) — los portales
  públicos de compras de Argentina, páginas "Ciudadano". La extracción es
  respetuosa por defecto; ver la sección de ética de scraping de
  [scraper/README.md](scraper/README.md).
- **Inflación (IPC):** INDEC IPC Nivel General Nacional.
- **Tipos de cambio:** BCRA Estadísticas Cambiarias.

El conjunto de datos extraído (grafo público en crudo, sin resultados de
detección) puede publicarse por separado bajo su propia licencia; ver
[DATASET_README.md](DATASET_README.md).

## Legal y ética

- Los resultados son **indicadores heurísticos, no acusaciones**. Lea [DISCLAIMER.md](DISCLAIMER.md).
- Derecho de réplica / corrección / baja: ver [DISCLAIMER.md](DISCLAIMER.md) §5.
- Los colaboradores deben mantener toda la redacción enmarcada como indicadores — ver
  [CONTRIBUTING.md](CONTRIBUTING.md) y [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).
- Problemas de seguridad: ver [SECURITY.md](SECURITY.md).

## Licencia

Coima está licenciado bajo la **GNU Affero General Public License v3.0**
(AGPL-3.0). Ver [LICENSE](LICENSE). La AGPL exige que quien corra una versión
modificada como servicio de red también ponga disponible el código fuente
correspondiente. El software se provee "TAL CUAL", sin garantía de ningún tipo.
