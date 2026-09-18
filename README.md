# Colossus

Interfaz gráfica para **filtrar archivos demasiado grandes para abrir en Excel**.
Construida con **PySide6 (Qt)** + **Polars** en modo *lazy*, así que puede leer y
exportar archivos que no caben en memoria.

Interfaz con **tema claro / oscuro** (botón 🌙/☀️ en la barra superior),
barra de aplicación, tarjetas y botones primarios. La paleta sigue el
**degradado del logo** (esmeralda → azul → violeta → fucsia sobre azul marino).
Los iconos se dibujan por código, sin archivos de imagen.

## Formatos soportados

| Formato | Extensiones | Modo |
|---|---|---|
| Texto delimitado (+ comprimido) | `.csv` `.txt` `.tsv` `.csv.gz` | streaming |
| Parquet | `.parquet` `.pq` | streaming |
| Arrow / Feather | `.arrow` `.feather` `.ipc` | streaming |
| NDJSON / JSON lines | `.ndjson` `.jsonl` | streaming |
| JSON normal | `.json` | en memoria |
| Excel / hojas de cálculo | `.xlsx` `.xlsm` `.xls` `.xlsb` `.ods` | en memoria |
| SQLite (base de datos) | `.db` `.sqlite` `.sqlite3` `.db3` | en memoria (una tabla) |

*Streaming* = puede procesar archivos que **no caben en RAM**. En todos, los tipos
(entero, flotante, texto, booleano, fecha/datetime) se detectan solos. Al abrir una
base **SQLite** se muestra un panel para **elegir la tabla** (con vista previa); la
base se abre en **solo lectura** (no se modifica).

### Motor de lectura: caché Parquet (ultrarrápido)

Sin importar el formato de origen (CSV, Excel, SQLite, JSON…), al abrir el archivo
Colossus lo **convierte una sola vez a un Parquet temporal** y **todas las
operaciones** (vista previa, contar, min/max, resumen, filtros, export) leen de ese
Parquet. Parquet es columnar y comprimido: en pruebas con 10 millones de filas pasó
de 571 MB (CSV) a 91 MB, y las lecturas fueron **5–50× más rápidas** (p. ej. la vista
previa filtrada de ~1 s a ~20 ms). El Parquet vive en la carpeta temporal del sistema
y se borra solo al cerrar la app o abrir otro archivo. El archivo original **nunca se
modifica**; la exportación es siempre CSV.

## Instalar y ejecutar

```bash
pip install -r requirements.txt
python colossus.py
```

## Archivos

| Archivo | Qué hace |
|---|---|
| `colossus.py`          | La interfaz gráfica (ventana, filtros, tabla, export). |
| `colossus_core.py`     | El motor de filtrado con Polars (lógica pura, sin GUI). |
| `colossus_icons.py`    | Iconos dibujados por código con QPainter. |
| `logo.jpg`             | Logo de la marca; de él sale la paleta de colores. |
| `logo_mark.png`        | Monograma «C» recortado del logo (ícono de la barra). |
| `generate_test_data.py`| Genera un CSV de prueba grande (5M filas ≈ 272 MB). |

Genera datos de prueba con:

```bash
python generate_test_data.py            # 5.000.000 de filas
python generate_test_data.py 20000000   # 20 millones de filas (~1 GB)
```

## Cómo usar

1. **Abrir archivo** → ver *Formatos soportados* abajo. En CSV el separador se
   detecta solo (`,` `;` `|` tab); puedes forzarlo con el combo *Separador*. Al
   abrir un Excel se muestra un panel para elegir **la hoja**, **desde qué fila**
   empieza la data y **qué columnas** usar (ver más abajo). **Apenas se carga el
   archivo, la vista previa aparece automáticamente** abajo.
2. **Añadir filtro**: elige columna, operador y valor. Los operadores se adaptan
   al tipo de la columna. Para listas, separa por coma: `Bogota, Cali, Medellin`.
3. **NOT** (icono ⊘) niega solo ese filtro; **Negar todo el resultado** invierte
   el resultado final. Combina los filtros con **AND** u **OR**.
4. **Valores únicos** (panel derecho o la lupa de cada filtro): lista los valores
   distintos de la columna cuando no superan el *Umbral* (por defecto 100). Si lo
   superan, escribe un valor y pulsa **Enter** para verificar que existe (sin
   distinguir mayúsculas). Doble clic inserta el valor en el filtro activo.
5. **Vista previa** / **Contar filas** / **Min / Max** sin exportar.
6. **Resumen** (botón): abre el **resumen estadístico** del resultado filtrado.
   Se calcula de forma *lazy* sobre **todo el dataset filtrado** (no una muestra)
   y muestra —solo para las **columnas numéricas**— count, media, desviación
   estándar, mínimo, cuartiles (25/50/75 %) y máximo, como el `describe()` de
   pandas/polars (las columnas de texto, booleanas o de fecha se omiten del
   resumen numérico). Dentro, el botón **Ver distribución** dibuja un **gráfico**
   de la columna que elijas —incluidas las de **texto**—: barras con una **curva
   suave tipo campana** para columnas numéricas (histograma por rangos) o conteo
   por valor para texto/booleanas/fecha. Los colores del gráfico siguen el
   degradado del logo.
7. **Asistente** (botón 💬): abre el **asistente de datos**, que describe en
   lenguaje natural **qué son los datos y cómo están organizados** (nº de filas y
   columnas, tipos, valores únicos, nulos, rangos, top de categorías y algunas
   observaciones automáticas, p. ej. qué columna parece un identificador). Todo se
   calcula **localmente en tu equipo, sin internet**; los datos no salen de ahí.
8. **Exportar CSV**: la exportación es **siempre CSV** (para manipular cómodo en
   Excel) y puedes **elegir el separador** de salida (`,` `;` `|` o tab). Se
   escribe en streaming (no carga todo en RAM).

## Tabla de resultados (tipo Excel)

- **Clic** en una cabecera de columna: ordena A→Z / Z→A (y fechas/números de
  menor a mayor y viceversa) sobre la vista previa.
- **Clic derecho** en una cabecera: menú con ordenar y con los **valores únicos
  disponibles** en la vista; al elegir uno se crea un filtro por ese valor.
- Mientras la herramienta trabaja aparece un **icono de carga girando** en la
  barra inferior; cuando termina, simplemente desaparece.

## Archivos de Excel / hojas de cálculo

Colossus abre `.xlsx`, `.xlsm`, `.xls`, `.xlsb` y `.ods`. Al elegir uno aparece un
panel con **vista previa en vivo** donde defines exactamente dónde está la data:

- **Identificar automáticamente la tabla**: un botón que busca solo la fila de
  encabezado y el rango de columnas con datos (ignora títulos/notas de arriba y
  columnas vacías a la izquierda). Rellena los campos por ti; luego puedes
  ajustarlos.
- **Hoja**: elige entre las hojas del libro.
- **Fila del encabezado**: en qué fila están los títulos de columna (útil cuando
  arriba hay filas de logo, título o notas). Se puede marcar *La primera fila no
  es encabezado* para que Colossus genere nombres automáticos.
- **Saltar filas de datos**: descarta filas basura justo debajo del encabezado.
- **Columnas**: un rango o lista tipo `A:F` o `A,C,E` (vacío = todas).

La vista previa se actualiza en vivo al cambiar cualquier opción (incluido el
campo de columnas), así confirmas que quedó bien antes de cargar. Los tipos
(número, fecha, booleano, texto) se detectan solos.

Si el archivo **no se puede leer** con las opciones actuales, aparece un aviso
con el motivo y la ventana **se queda abierta** para que corrijas la fila o las
columnas (o presiones *Cancelar*); no te saca a la ventana principal.

> Los Excel se cargan completos en memoria (por el formato), pero como rara vez
> superan ~1 millón de filas, va perfecto. Para archivos realmente enormes, CSV y
> Parquet siguen siendo *streaming*.

## Fechas con distinto formato

Lee fechas ISO (`AAAA-MM-DD`) y también `DD/MM/AAAA`, `MM/DD/AAAA`,
`DD-MM-AAAA`, etc. El selector **Fecha** de la barra superior permite forzar el
orden día/mes/año cuando es ambiguo (`auto`, `DMY`, `MDY`, `YMD`). El botón
**Detectar fechas** activa o desactiva toda esta interpretación.

## Tipos de dato soportados

Entero, flotante, texto, **booleano** y **fecha/datetime**, con operadores
adaptados a cada uno (incluye `is null` / `is not null` / `is true` / `is false`).

## Requisitos

```
polars>=1.20
pyarrow>=15
PySide6>=6.6
fastexcel>=0.10   # lectura de Excel / ODS
```
