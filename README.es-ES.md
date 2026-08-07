

# geedl — Descargador de Google Earth Engine

> **Descarga imágenes satelitales de Google Earth Engine directamente a tu disco local.**
> Sin Google Cloud Storage. Sin Google Drive. Sin tareas de exportación.
> Reanudable, seguro ante fallos, completamente impulsado por YAML.

[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

`geedl` es una herramienta de línea de comandos de alto rendimiento y priorización local para descargar
**imágenes de Sentinel-1, Sentinel-2, Landsat 7, Landsat 8 y Landsat 9** de
Google Earth Engine. Apúntalo a un shapefile y un rango de fechas: dividirá tu
ROI en baldosas, compondrá escenas, calculará índices espectrales (NDVI, EVI, NDWI, NBR, RVI…)
y escribirá **GeoTIFFs Optimizados para la Nube** directamente en tu máquina.

---

## ¿Por qué geedl?

Si alguna vez has intentado descargar imágenes de Earth Engine para una área grande,
sabes el dolor: tareas de exportación que tardan horas, archivos atrapados en Google Drive,
cubos de Cloud Storage por los que tienes que pagar, y ninguna forma de reanudar cuando algo falla. **geedl salta todo eso.**

| | Exportación tradicional de EE | **geedl** |
|---|---|---|
| Destino | Google Drive / cubo de GCS | **Disco local** |
| Rendimiento | Tarea de exportación única | **Baldosas asíncronas paralelas (predeterminado 16)** |
| Reanudar tras un fallo | Reexportar desde cero | **Punto de control SQLite — reanuda exactamente donde te detuviste** |
| Ajuste del tamaño de baldosa | Manual | **Calculado automáticamente según el presupuesto de píxeles** |
| Formato de salida | GeoTIFF | **GeoTIFF Optimizado para la Nube + archivo complementario STAC + catálogo GeoParquet** |
| Configuración | Script de Python por trabajo | **Un solo archivo YAML** |

---

## Características

- **Descarga directa desde Earth Engine** mediante `ee.data.computePixels()` — sin GCS, sin Drive.
- **Soporte para ROI en shapefile** — se proyecta automáticamente a UTM, se simplifica para la carga y se divide en baldosas de forma inteligente.
- **División en baldosas inteligente** — clasifica las baldosas como `inside`, `partial` o `outside`; omite el espacio vacío; ordena por **curva de Hilbert** para solicitudes a EE con caché caliente.
- **Composición por ventanas temporales** — modos de días fijos, mes calendario, año calendario, rango completo o escena única. El modo de escena sugiere las fechas disponibles más cercanas cuando el día solicitado no tiene imágenes.
- **Fusión de baldosas por ventana** — las baldosas fluyen a un directorio temporal de preparación, luego se fusionan en un COG por ROI/ventana antes de que el trabajo finalice.
- **Barras de progreso en vivo** — barras generales y por ventana de `tqdm` rastrea cada baldosa a través de la descarga, validación y escritura.
- **Índices espectrales** — NDVI, EVI, NDWI, NDMI, NBR, NDSI, SAVI, BSI, RVI y ratio VV/VH incorporados. Agrega los tuyos con una función decorada.
- **Seguro ante fallos y reanudable** — cada baldosa tiene un punto de control; las escrituras atómicas (`.tmp` → `os.rename`) garantizan que no haya archivos corruptos en el disco.
- **Enmascaramiento de nubes** incorporado — SCL de Sentinel-2, `QA_PIXEL` de Landsat C2. Interruptores de nubes + sombras + nieve por trabajo.
- **Landsat 7 SLC-off** gestionado mediante composición multitemporal — sin desenfoque focal, sin índices rotos.
- **Salida COG** — legible nativamente por QGIS, GDAL, stackstac y navegadores STAC.
- **Amigable para agentes de IA** — la configuración YAML es la única fuente de verdad. Cambia conjuntos de datos, índices, formas de salida o comportamiento de la canalización sin tocar Python.

---

## Instalación

`geedl` utiliza un entorno **conda** para Python + bibliotecas geoespaciales a nivel de sistema
(GDAL, PROJ, GEOS) y **uv** para la resolución rápida de dependencias de Python
dentro de ese entorno.

```bash
# 1. Create and activate the conda environment
conda create -n geedl python=3.12 -y
conda activate geedl

# 2. Install uv inside the env
conda install -c conda-forge uv -y

# 3. Install geedl with uv (editable)
uv pip install -e .
```

O, con herramientas de desarrollo (pytest, ruff, mypy):

```bash
uv pip install -e ".[dev]"
```

También necesitarás autenticarte con Earth Engine una vez:

```bash
earthengine authenticate
```

> Cada sesión de shell posterior necesitará `conda activate geedl` antes de ejecutar
> el CLI de `geedl`.

---

## Inicio rápido

### 1. Escribe una configuración

Crea `job.yaml`:

```yaml
job_name: tuscany_ndvi_q1_2023

roi:
  path: data/tuscany.shp

dataset:
  name: sentinel-2
  bands:
    select: [B2, B3, B4, B8]
  indices:
    - {name: NDVI}
    - {name: EVI}

date:
  start: "2023-01-01"
  end:   "2023-03-31"

composite:
  strategy: median
  window:
    type: fixed_days
    size: 30
    step: 30
    label_format: "%Y-%m-%d"

output:
  dir: ./output
  format: COG
  dtype: float32

asset:
  project: my-ee-project
  base_path: users/me/geedl_assets
```

### 2. Ejecútalo

```bash
geedl validate -c job.yaml   # check config (no EE calls)
geedl plan     -c job.yaml   # preview windows + tile count
geedl run      -c job.yaml   # download to ./output
```

### 3. Reanuda si se interrumpe

Simplemente vuelve a ejecutar el mismo comando. Las baldosas completadas se omiten automáticamente.

```bash
geedl run -c job.yaml                  # resume
geedl run -c job.yaml --retry-failed   # also retry tiles that failed
geedl status -c job.yaml               # check progress
```

---

## Háblale. Obtén un job.yaml.

`geedl` fue diseñado para que todo el trabajo: sensor, índices, ventanas temporales, forma de salida,
concurrencia, autenticación — viva en **un solo archivo YAML declarativo**. Eso lo convierte
en el objetivo ideal para un agente de codificación LLM: no hay Python que escribir, ni
SDK que aprender, ni cuaderno que depurar. Describes lo que quieres, el agente
emite una configuración, tú la ejecutas.

Coloca este README y `CLAUDE.md` en el contexto de tu agente (Claude Code,
Cursor, Codex, Aider, ChatGPT — cualquiera de ellos), luego pregunta en lenguaje claro.

**Tú:**

> Necesito una serie temporal mensual de NDVI y NDWI sobre mi finca en Toscana para
> todo 2023. El shapefile está en `data/tuscany.shp`. Quiero Sentinel-2 con
> nubes y sombras enmascaradas, salida como COGs, y solo los índices: descarta
> las bandas de origen. Ejecuta 24 baldosas en paralelo.

**Agente (en un solo paso, genera `job.yaml`):**

```yaml
job_name: tuscany_ndvi_ndwi_2023

roi:
  path: data/tuscany.shp

dataset:
  name: sentinel-2
  bands:
    select: []                     # drop source bands, keep only indices
  indices:
    - {name: NDVI}
    - {name: NDWI}
  cloud_mask:
    enabled: true
    mask_shadow: true
    mask_snow: false

date:
  start: "2023-01-01"
  end:   "2023-12-31"

composite:
  strategy: median
  window:
    type: calendar_month
    label_format: "%Y-%m"

output:
  dir: ./output
  format: COG
  dtype: float32
  compression: DEFLATE
  structure:
    separate_indices: true         # one GeoTIFF per index

pipeline:
  concurrency: 24

asset:
  project: my-ee-project
  base_path: projects/my-ee-project/assets

auth:
  method: browser
```

**Tú:**

```bash
geedl plan -c job.yaml && geedl run -c job.yaml
```

Ese es todo el ciclo. ¿Necesitas cambiar el sensor? "Cambia a Landsat 8 con los
mismos índices." ¿Necesitas una ventana diferente? "Hazlo con composiciones de 16 días ancladas
al inicio de la ventana." ¿Necesitas detección urbana desde SAR en su lugar?
"Dame el falso color SAR_URBAN de Sentinel-1 sobre el mismo ROI para la
primera semana de mayo." El agente edita el YAML — tú vuelves a ejecutar `geedl`.

Consulta [`examples/`](examples/) para diez configuraciones concretas (NDVI, NDWI, RGB,
S1 RTC, OSFC de derrames de petróleo, falso color SAR urbano S1, modo escena, …) que
también sirven como prompts de pocos ejemplos para cualquier LLM.

> **Por qué funciona**: `CLAUDE.md` documenta cada campo de configuración, cada límite
> de módulo y cada restricción innegociable (escrituras atómicas, índices solo por plugin,
> S1-debe-ser-mosaico, …). Un agente que lo lee tiene el esquema completo
> y el conjunto completo de reglas — por lo que no alucina campos ni elige
> estrategias de composición físicamente incorrectas.

---

## Uso

### Autenticación

Dos métodos, seleccionados en YAML:

```yaml
# Browser flow (default) — uses your `earthengine authenticate` credentials.
auth:
  method: browser

# Service account — for headless / CI use.
auth:
  method: service_account
  service_account_email: bot@my-proj.iam.gserviceaccount.com
  key_file: /etc/secrets/ee-key.json
```

### Configuraciones por sensor

**Sentinel-2 — composiciones mensuales de NDVI/EVI**

```yaml
dataset:
  name: sentinel-2
  bands: {select: [B2, B3, B4, B8, B11]}
  indices: [{name: NDVI}, {name: EVI}, {name: NDMI}]
  cloud_mask: {enabled: true, mask_shadow: true, mask_snow: false}
composite:
  strategy: median
  window: {type: calendar_month}
```

**Sentinel-1 — mosaicos de retrodispersión VV/VH**

```yaml
dataset:
  name: sentinel-1
  bands: {select: [VV, VH]}
  indices: [{name: RVI}]
composite:
  strategy: median   # ignored — S1 always forces mosaic (see CLAUDE.md §7)
  window: {type: fixed_days, size: 12, step: 12}
```

**Landsat 8/9 — composiciones trimestrales**

```yaml
dataset:
  name: landsat-8
  bands: {select: [SR_B2, SR_B3, SR_B4, SR_B5, SR_B6, SR_B7]}
  indices: [{name: NDVI}, {name: NBR}, {name: SAVI}]
composite:
  strategy: median
  window: {type: fixed_days, size: 90, step: 90, anchor: center}
```

**Modo de escena de fecha única — obtén la adquisición de Sentinel-1 disponible más cercana**

```yaml
dataset:
  name: sentinel-1
  bands: {select: [VV, VH]}
date:
  start: "2024-06-15"
  end:   "2024-06-15"
composite:
  strategy: none
  window: {type: scene}   # one output per intersecting scene; suggests nearby dates if empty
```

**Salida solo índices — descarta las bandas de origen, mantén solo el índice calculado**

```yaml
dataset:
  name: sentinel-2
  bands:
    select: []                # [] = no source bands; null = all registry bands; list = those bands
  indices:
    - {name: NDVI}
output:
  structure:
    separate_indices: true    # each index gets its own GeoTIFF
```

`bands.select` es triestado:
- `null` (omitido) — mantiene todas las bandas definidas en `registry.yaml` para el conjunto de datos.
- `[]` — no mantiene bandas de origen. El trabajo es rechazado en el momento de la validación a menos que se solicite al menos un índice.
- `[B4, B8, ...]` — mantiene exactamente esas bandas.

En los tres casos, los índices se calculan a partir de las bandas de origen nativas independientemente de `select` (las expresiones hacen referencia directamente a NIR/RED/etc.), por lo que `select: []` sigue produciendo una salida válida de NDVI/EVI/etc.

**Landsat 7 — recuperación SLC-off mediante ventana de composición larga**

```yaml
dataset:
  name: landsat-7
  bands: {select: [SR_B3, SR_B4, SR_B5]}
  indices: [{name: NDVI}]
  slc_off: {strategy: multi_temporal, min_scenes_warning: 5}
composite:
  strategy: median
  window: {type: calendar_year}   # wide enough to fill SLC gaps
```

### Ajuste de concurrencia y tamaño de baldosa

```yaml
pipeline:
  concurrency: 16          # parallel async tiles
  max_retries: 6
  retry_base_delay: 1.0
  timeout_per_tile: 120
tiling:
  max_tile_bytes: null     # null = auto, derived from EE's 50 MB request budget
  overlap_px: 2            # request buffer to avoid seam artifacts
  skip_coverage_threshold: 0.05  # tiles <5% inside ROI are skipped
```

### Ganchos (Hooks)

Ejecuta código del usuario en tres puntos del ciclo de vida (formato: `módulo.ruta:nombre_funcion`):

```yaml
hooks:
  pre_download: my_pkg.hooks:before_tile
  post_tile:    my_pkg.hooks:after_tile
  post_job:     my_pkg.hooks:on_finish
```

### Ejecución de pruebas

```bash
pytest                       # full unit + integration suite (~2s, no EE calls)
pytest --live                # also runs the opt-in EE smoke tests
                             #   requires: GEEDL_TEST_EE_PROJECT=ee-tat3 \
                             #   GEEDL_TEST_EE_KEY=/credentials.json \
                             #   pytest tests/test_live_smoke.py --live
GEEDL_TEST_EE_PROJECT=ee-tat3 GEEDL_TEST_EE_KEY=ee-tat3-835f3bd207eb.json pytest --live 
pytest tests/test_indices_matrix.py -v   # one module
```

---

## Conjuntos de datos compatibles

| Identificador | Colección | Resolución nativa |
|---|---|---|
| `sentinel-2` | `COPERNICUS/S2_SR_HARMONIZED` | 10 m |
| `sentinel-1` | `COPERNICUS/S1_GRD` (IW, DESC) | 10 m |
| `landsat-7` | `LANDSAT/LE07/C02/T1_L2` | 30 m |
| `landsat-8` | `LANDSAT/LC08/C02/T1_L2` | 30 m |
| `landsat-9` | `LANDSAT/LC09/C02/T1_L2` | 30 m |

Agrega nuevos conjuntos de datos editando `geedl/datasets/registry.yaml` — no se requieren cambios en Python.

```bash
geedl datasets                       # list available datasets
geedl indices --dataset sentinel-2  # list compatible indices
```

---

## Índices espectrales

Incorporados: **NDVI, NDWI, NDMI, NBR, NDSI, EVI, SAVI, BSI** (óptico) y **RVI, ratio VV/VH** (SAR).

Agregar un nuevo índice requiere una sola función:

```python
# geedl/indices/optical.py
from . import index

@index("CIRE", datasets=["sentinel-2"])
def cire(img, ds):
    return img.expression("NIR/RED_EDGE - 1", {
        "NIR": img.select("B8"),
        "RED_EDGE": img.select("B5"),
    }).rename("CIRE")
```

Haz referencia a él desde cualquier configuración YAML — no se necesitan otros cambios de código.

---

## Estructura de salida

```
output/
  sentinel-2/
    2023-01-01/
      tile_A00_2023-01-01.tif      # Cloud-Optimized GeoTIFF
      tile_A00_2023-01-01.json     # STAC Item sidecar
      tile_B01_2023-01-01.tif
      ...
    2023-02-01/
      ...
  catalog.parquet                   # GeoParquet spatial index of all tiles
  job.yaml                          # frozen copy of the config used
  checkpoint.db                     # SQLite resume state
```

Lee el catálogo de vuelta con cualquier herramienta compatible con GeoParquet:

```python
import geopandas as gpd
gdf = gpd.read_parquet("output/catalog.parquet")
gdf[gdf.datetime.str.startswith("2023-01")].plot()
```

---

## Cómo funciona

1. **Preparación del ROI** — se carga el shapefile, se proyecta automáticamente a UTM, se simplifica y se carga una vez como un activo de EE (ID determinista basado en hash, por lo que el mismo ROI se reutiliza entre ejecuciones).
2. **División en baldosas** — la caja delimitadora se divide en cuadrados de tamaño fijo cuyas dimensiones se derivan del presupuesto de píxeles por solicitud de EE. Las baldosas fuera del ROI se omiten; las baldosas en el borde se etiquetan como `partial` y obtienen tanto un `img.clip()` del lado del servidor como una máscara local de rasterio.
3. **Ventaneado** — el rango de fechas se divide en ventanas de composición (días fijos, meses calendario, etc.).
4. **Descarga asíncrona** — cada (baldosa × ventana) se obtiene concurrentemente mediante `ee.data.computePixels()` en formato NPY. Los fallos se reintentan con reintento exponencial + jitter completo.
5. **Validación** — cada matriz se verifica por forma, todos-nodata y rango de valores plausible antes de ser escrita.
6. **Escritura atómica** — los datos se escriben en `{path}.tmp.tif`, se dividen internamente en 256×256, se construyen las vistas previas (overviews), luego `os.rename()` lo intercambia en su lugar.
7. **Punto de control** — solo después de que el renombrado tenga éxito, la baldosa se marca como `done` en el punto de control SQLite. La recuperación ante fallos restablece las baldosas `in_flight` a `pending` y elimina cualquier rezagado en el siguiente lanzamiento.
8. **Fusión y catálogo** — una vez que cada baldosa en una ventana es `done`, las baldosas parciales se fusionan en un COG por ROI/ventana. Los archivos complementarios STAC y `catalog.parquet` se escriben a partir de las salidas fusionadas al final del trabajo.

Consulta [`ARCH.md`](ARCH.md) para la justificación de diseño completa y el registro de decisiones.

---

## Referencia de CLI

```bash
geedl run        -c job.yaml [--fresh] [--retry-failed]   # run or resume
geedl validate   -c job.yaml                             # check config
geedl plan       -c job.yaml                             # dry-run preview
geedl status     -c job.yaml                             # tile counts
geedl datasets                                            # list datasets
geedl indices    --dataset sentinel-2                    # list indices
geedl cleanup    -c job.yaml                             # delete EE asset
```

---

## Estado del proyecto

`geedl` v0.1 es **software pre-1.0**. La canalización central funciona de extremo a extremo en los
conjuntos de datos listados, incluyendo el modo escena para trabajos de fecha única con sugerencias
de retroceso a la fecha más cercana. Brechas conocidas: solo un proceso, sin GUI.
Consulta [`ARCH.md`](ARCH.md) §17 para la lista completa de advertencias.

---

## Contribuir

Issues y PRs bienvenidos. La base de código tiene un gráfico de dependencias estricto
(`utils → datasets → indices → io/roi → pipeline → cli`) y un motor de índices solo por plugin: consulta [`CLAUDE.md`](.claude/CLAUDE.md) para contratos de módulos y
convenciones de pruebas antes de abrir un PR.

El proyecto se basa fuertemente en el **minimalismo y la anti-sobreingeniería**: prefiere
editar módulos existentes sobre agregar nuevos, sin abstracciones especulativas, sin
parches de compatibilidad hacia atrás, sin andamiaje defensivo dentro de los límites de confianza, y
comentarios solo donde el *por qué* no es obvio. Consulta la sección "Ética de ingeniería"
de `CLAUDE.md` para las reglas completas.

---

## Licencia

MIT
