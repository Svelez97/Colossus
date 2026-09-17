"""
colossus_core.py
----------------
Motor de filtrado de archivos masivos (Colossus).

Toda la logica es pura y testeable sin interfaz grafica. Usa Polars en modo
LAZY (scan_csv / scan_parquet / scan_ipc / scan_ndjson) para poder trabajar con
archivos que no caben en memoria: los filtros se empujan al escaneo y solo se
materializa el resultado (preview / conteo / export en streaming). Excel/ODS y
JSON "normal" se materializan por formato, pero el pipeline es el mismo.

Formatos: CSV/TXT/TSV (+.gz), Parquet, Arrow/Feather/IPC, NDJSON/JSONL, JSON y
Excel/ODS (.xlsx .xlsm .xls .xlsb .ods).

Novedades respecto al notebook original:
  - Tipos de dato soportados: entero, flotante, texto, BOOLEANO y FECHA/DATETIME.
  - Umbral de valores unicos configurable (por defecto 100).
  - Negacion por-filtro (NOT) ademas de negacion global.
  - Operadores extra: "is null" / "is not null" / "is true" / "is false".
  - Deteccion de separador mas robusta ( , ; | tab ).
  - Export en streaming con sink_csv (no carga todo en RAM).
"""
from __future__ import annotations

import csv
import datetime as dt
import gzip
import logging as _logging
from dataclasses import dataclass, field
from typing import Any

import polars as pl

# fastexcel avisa "Could not determine dtype ... falling back to string" cuando
# una columna esta vacia (comun al detectar la tabla). Es inofensivo: lo callamos.
_logging.getLogger("fastexcel").setLevel(_logging.ERROR)

# --------------------------------------------------------------------------- #
# Operadores por tipo de dato
# --------------------------------------------------------------------------- #
OPS_NO_VALUE = {"is null", "is not null", "is true", "is false"}

OPS_BY_KIND = {
    "int":      ["=", "!=", ">", ">=", "<", "<=", "in", "not in", "is null", "is not null"],
    "float":    ["=", "!=", ">", ">=", "<", "<=", "in", "not in", "is null", "is not null"],
    "date":     ["=", "!=", ">", ">=", "<", "<=", "in", "not in", "is null", "is not null"],
    "datetime": ["=", "!=", ">", ">=", "<", "<=", "in", "not in", "is null", "is not null"],
    "bool":     ["is true", "is false", "=", "!=", "is null", "is not null"],
    "str":      ["=", "!=", "in", "not in", "Like", "Not Like", "is null", "is not null"],
}
ALL_OPS = ["=", "!=", ">", ">=", "<", "<=", "in", "not in",
           "Like", "Not Like", "is true", "is false", "is null", "is not null"]

_DATE_FORMATS = ["%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%Y/%m/%d", "%d-%m-%Y", "%d.%m.%Y"]
_DATETIME_FORMATS = [
    "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M",
    "%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M", "%m/%d/%Y %H:%M:%S",
]
_TRUE = {"true", "t", "1", "yes", "y", "si", "sí", "verdadero"}
_FALSE = {"false", "f", "0", "no", "n", "falso"}


# --------------------------------------------------------------------------- #
# Especificacion de un filtro
# --------------------------------------------------------------------------- #
@dataclass
class FilterSpec:
    column: str
    op: str
    value: str = ""
    negate: bool = False          # NOT por-filtro
    enabled: bool = True

    def is_active(self) -> bool:
        if not self.enabled or not self.column or not self.op:
            return False
        if self.op in OPS_NO_VALUE:
            return True
        return self.value.strip() != ""


# --------------------------------------------------------------------------- #
# Deteccion de separador y apertura del archivo
# --------------------------------------------------------------------------- #
def detect_separator(path: str) -> str:
    """Detecta el separador leyendo la primera linea no vacia (soporta .gz)."""
    candidates = ["|", ";", "\t", ","]
    opener = gzip.open if path.lower().endswith(".gz") else open
    try:
        with opener(path, "rt", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if line.strip():
                    counts = {c: line.count(c) for c in candidates}
                    best = max(counts, key=counts.get)
                    if counts[best] > 0:
                        return best
                    break
    except Exception:
        pass
    return ","


# Formatos de fecha por "orden". 'auto' prueba varios y elige el que mejor
# parsee la muestra (con preferencia dia-primero, comun en Latinoamerica).
DATE_ORDERS = {
    "YMD": ["%Y-%m-%d", "%Y/%m/%d"],
    "DMY": ["%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y"],
    "MDY": ["%m/%d/%Y", "%m-%d-%Y", "%m.%d.%Y"],
}
_TIME_SUFFIXES = ["", " %H:%M:%S", " %H:%M"]


def _candidate_formats(date_order: str):
    """Devuelve [(formato, es_datetime), ...] segun el orden pedido."""
    orders = [date_order] if date_order in DATE_ORDERS else ["YMD", "DMY", "MDY"]
    out = []
    for order in orders:
        for base in DATE_ORDERS[order]:
            for suf in _TIME_SUFFIXES:
                out.append((base + suf, suf != ""))
    return out


def _detect_col_format(values: list[str], date_order: str):
    """Detecta el formato de fecha de una columna de texto. Devuelve (fmt, es_dt)
    o (None, False) si no parece una fecha."""
    import datetime as _dt
    sample = [str(v).strip() for v in values if v not in (None, "")][:200]
    if len(sample) < 3:
        return None, False
    for fmt, is_dt in _candidate_formats(date_order):
        ok = 0
        for v in sample:
            try:
                _dt.datetime.strptime(v, fmt)
                ok += 1
            except ValueError:
                pass
        if ok / len(sample) >= 0.9:
            return fmt, is_dt
    return None, False


def _coerce_string_dates(lf: pl.LazyFrame, date_order: str) -> pl.LazyFrame:
    """Convierte a fecha las columnas de TEXTO que en realidad son fechas con un
    formato no-ISO (dd/mm/aaaa, mm/dd/aaaa, etc.). Solo mira una muestra."""
    schema = dict(lf.collect_schema())
    str_cols = [c for c, t in schema.items() if t == pl.String]
    if not str_cols:
        return lf
    try:
        sample = lf.select(str_cols).head(400).collect()
    except Exception:
        return lf
    casts = []
    for c in str_cols:
        fmt, is_dt = _detect_col_format(sample[c].to_list(), date_order)
        if fmt:
            target = pl.Datetime if is_dt else pl.Date
            casts.append(
                pl.col(c).str.strptime(target, format=fmt, strict=False).alias(c))
    return lf.with_columns(casts) if casts else lf


# --------------------------------------------------------------------------- #
# Excel / hojas de calculo  (.xlsx .xlsm .xls .xlsb .ods)
# --------------------------------------------------------------------------- #
EXCEL_EXTS = (".xlsx", ".xlsm", ".xls", ".xlsb", ".ods")


def is_excel(path: str) -> bool:
    return path.lower().endswith(EXCEL_EXTS)


def excel_sheet_names(path: str) -> list[str]:
    """Lista los nombres de las hojas sin leer los datos (solo metadatos)."""
    import fastexcel
    return list(fastexcel.read_excel(path).sheet_names)


def read_excel(path: str, excel_opts: dict | None = None) -> pl.DataFrame:
    """Lee una hoja de Excel/ODS a un DataFrame, permitiendo definir DONDE esta
    la data:

    excel_opts admite:
      sheet       : nombre de la hoja (None -> la primera).
      has_header  : True si una fila contiene los titulos de columna.
      header_row  : indice 0-based de la fila de encabezado (si has_header).
      skip_rows   : filas de datos a saltar tras el encabezado.
      use_columns : rango/columnas a usar, p.ej. "A:F" (None -> todas).
    """
    opts = excel_opts or {}
    has_header = opts.get("has_header", True)
    read_options: dict = {
        "header_row": int(opts.get("header_row", 0)) if has_header else None,
    }
    skip = int(opts.get("skip_rows", 0) or 0)
    if skip:
        read_options["skip_rows"] = skip
    cols = (opts.get("use_columns") or "").strip()
    if cols:
        read_options["use_columns"] = cols
    n_rows = opts.get("n_rows")
    if n_rows:
        read_options["n_rows"] = int(n_rows)

    kwargs: dict = {"read_options": read_options}
    sheet = opts.get("sheet")
    if sheet not in (None, ""):
        kwargs["sheet_name"] = sheet
    return pl.read_excel(path, **kwargs)


def _col_letter(idx0: int) -> str:
    """Indice de columna 0-based -> letra(s) de Excel (0->A, 26->AA)."""
    s = ""
    idx = idx0 + 1
    while idx > 0:
        idx, r = divmod(idx - 1, 26)
        s = chr(65 + r) + s
    return s


def detect_excel_table(path: str, sheet: str | None = None) -> dict | None:
    """Identifica automaticamente DONDE empieza la tabla en la hoja: la fila de
    encabezado y el rango de columnas con datos. Devuelve un dict listo para usar
    como excel_opts:  {header_row (0-based), use_columns 'C:J', first_col, ...}
    o None si la hoja parece vacia.

    Heuristica: mira las primeras filas del rango con datos, ignora las de arriba
    con pocas celdas (titulos/notas) y toma como encabezado la primera fila 'ancha'
    cuyo bloque de columnas continua en la fila siguiente (ahi empiezan los datos).
    Las columnas se expresan con su LETRA de Excel real (absolute_index), de modo
    que el rango sigue siendo valido aunque haya columnas vacias a la izquierda."""
    import fastexcel
    try:
        reader = fastexcel.read_excel(path)
        name = sheet if sheet not in (None, "") else reader.sheet_names[0]
        sh = reader.load_sheet(name, header_row=None, n_rows=100)
        cols_info = sh.available_columns()          # .absolute_index = col real (0-based)
        rows = sh.to_polars().rows()
    except Exception:
        return None

    if not rows:
        return None

    def filled(row):
        return [i for i, v in enumerate(row)
                if v is not None and str(v).strip() != ""]

    fills = [filled(r) for r in rows]
    counts = [len(f) for f in fills]
    if not any(counts):
        return None
    max_c = max(counts)

    header_idx = None
    for i in range(len(rows) - 1):
        # fila 'ancha' (>=60% del maximo, minimo 2 celdas) cuyo bloque de
        # columnas se solapa con la fila de abajo (los datos continuan).
        if counts[i] >= max(2, max_c * 0.6) and fills[i] and \
                set(fills[i]) & set(fills[i + 1]):
            header_idx = i
            break
    if header_idx is None:
        header_idx = counts.index(max_c)   # respaldo: la fila mas llena

    # posiciones del encabezado -> columnas absolutas de Excel -> letras
    abs_cols = [cols_info[j].absolute_index for j in fills[header_idx]]
    first, last = min(abs_cols), max(abs_cols)
    return {
        "header_row": header_idx,
        "use_columns": f"{_col_letter(first)}:{_col_letter(last)}",
        "first_col": _col_letter(first),
        "header_row_1based": header_idx + 1,
    }


# --------------------------------------------------------------------------- #
# Bases de datos SQLite  (.db .sqlite .sqlite3 .db3)
# --------------------------------------------------------------------------- #
SQLITE_EXTS = (".db", ".sqlite", ".sqlite3", ".db3")


def is_sqlite(path: str) -> bool:
    return path.lower().endswith(SQLITE_EXTS)


def _sqlite_connect(path: str):
    """Conexion de SOLO LECTURA a la base (no la modifica)."""
    import sqlite3
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True)


def sqlite_table_names(path: str) -> list[str]:
    """Lista las tablas y vistas de la base (sin las internas de sqlite)."""
    con = _sqlite_connect(path)
    try:
        cur = con.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type IN ('table','view') AND name NOT LIKE 'sqlite_%' "
            "ORDER BY name")
        return [r[0] for r in cur.fetchall()]
    finally:
        con.close()


def read_sqlite(path: str, table: str | None = None,
                limit: int | None = None) -> pl.DataFrame:
    """Lee una tabla de la base a un DataFrame. Si no se indica tabla, usa la
    primera disponible. `limit` acota las filas (util para vistas previas)."""
    if not table:
        tables = sqlite_table_names(path)
        if not tables:
            raise ValueError("La base no tiene tablas legibles.")
        table = tables[0]
    safe = table.replace('"', '""')          # escapa el nombre de la tabla
    query = f'SELECT * FROM "{safe}"'
    if limit:
        query += f" LIMIT {int(limit)}"
    con = _sqlite_connect(path)
    try:
        return pl.read_database(query, con)
    finally:
        con.close()


def scan_file(path: str, separator: str | None = None, parse_dates: bool = True,
              date_order: str = "auto", excel_opts: dict | None = None,
              table: str | None = None):
    """Abre el archivo como LazyFrame. No lee todo en RAM (salvo Excel y JSON, que
    por formato se materializan; aun asi el resto del pipeline sigue igual).

    Formatos soportados:
      - CSV/TXT/TSV (incl. comprimidos .gz)  -> streaming
      - Parquet (.parquet .pq)               -> streaming
      - Arrow/Feather/IPC (.arrow .feather .ipc) -> streaming
      - NDJSON / JSON lines (.ndjson .jsonl) -> streaming
      - JSON normal (.json)                  -> en memoria
      - Excel / ODS (.xlsx .xlsm .xls .xlsb .ods) -> en memoria
      - SQLite (.db .sqlite .sqlite3 .db3)   -> en memoria (una tabla)

    parse_dates : intenta interpretar columnas de fecha (ISO automatico +
                  deteccion de formatos dd/mm/aaaa, mm/dd/aaaa, etc.).
    date_order  : 'auto' | 'YMD' | 'DMY' | 'MDY'  -> como leer fechas ambiguas.
    excel_opts  : opciones de lectura de Excel (ver read_excel).
    table       : tabla a leer en bases SQLite (None -> la primera).
    """
    lower = path.lower()
    if lower.endswith(".parquet") or lower.endswith(".pq"):
        return pl.scan_parquet(path), separator or ","
    if lower.endswith(SQLITE_EXTS):
        lf = read_sqlite(path, table).lazy()
        if parse_dates:
            lf = _coerce_string_dates(lf, date_order)
        return lf, separator or ","
    if lower.endswith(EXCEL_EXTS):
        lf = read_excel(path, excel_opts).lazy()
        if parse_dates:
            lf = _coerce_string_dates(lf, date_order)
        return lf, separator or ","
    if lower.endswith((".arrow", ".feather", ".ipc")):
        lf = pl.scan_ipc(path)
        if parse_dates:
            lf = _coerce_string_dates(lf, date_order)
        return lf, separator or ","
    if lower.endswith((".ndjson", ".jsonl")):
        lf = pl.scan_ndjson(path)
        if parse_dates:
            lf = _coerce_string_dates(lf, date_order)
        return lf, separator or ","
    if lower.endswith(".json"):
        # JSON "normal" (no lineas): se materializa y se pasa a lazy.
        lf = pl.read_json(path).lazy()
        if parse_dates:
            lf = _coerce_string_dates(lf, date_order)
        return lf, separator or ","
    # CSV / TXT / TSV, incluidos comprimidos .gz (scan_csv descomprime solo)
    sep = separator or detect_separator(path)
    lf = pl.scan_csv(
        path,
        separator=sep,
        try_parse_dates=parse_dates,
        infer_schema_length=10000,
        ignore_errors=False,
        truncate_ragged_lines=True,
    )
    if parse_dates:
        lf = _coerce_string_dates(lf, date_order)
    return lf, sep


def get_schema(lf: pl.LazyFrame) -> dict[str, pl.DataType]:
    """Devuelve {columna: dtype} sin materializar el archivo completo."""
    return dict(lf.collect_schema())


# --------------------------------------------------------------------------- #
# Clasificacion de tipos
# --------------------------------------------------------------------------- #
def dtype_kind(dtype: pl.DataType) -> str:
    """Clasifica un dtype de Polars en: int/float/bool/date/datetime/str."""
    try:
        if dtype == pl.Boolean:
            return "bool"
        if dtype == pl.Date:
            return "date"
        if isinstance(dtype, pl.Datetime) or dtype == pl.Datetime:
            return "datetime"
        if dtype.is_integer():
            return "int"
        if dtype.is_float():
            return "float"
    except Exception:
        pass
    return "str"


def ops_for(dtype: pl.DataType) -> list[str]:
    return OPS_BY_KIND.get(dtype_kind(dtype), OPS_BY_KIND["str"])


def dtype_label(dtype: pl.DataType) -> str:
    """Etiqueta corta y amigable del tipo, para mostrar junto a la columna."""
    return {
        "int": "123", "float": "1.2", "bool": "T/F",
        "date": "fecha", "datetime": "fecha-hora", "str": "abc",
    }[dtype_kind(dtype)]


# --------------------------------------------------------------------------- #
# Parseo de valores segun el tipo
# --------------------------------------------------------------------------- #
def _parse_bool(s: str) -> bool:
    v = s.strip().lower()
    if v in _TRUE:
        return True
    if v in _FALSE:
        return False
    raise ValueError(f"Valor booleano invalido: {s!r}")


def _parse_date(s: str) -> dt.date:
    s = s.strip()
    for fmt in _DATE_FORMATS:
        try:
            return dt.datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Fecha invalida: {s!r} (usa AAAA-MM-DD)")


def _parse_datetime(s: str) -> dt.datetime:
    s = s.strip()
    for fmt in _DATETIME_FORMATS:
        try:
            return dt.datetime.strptime(s, fmt)
        except ValueError:
            continue
    # permite escribir solo la fecha -> medianoche
    try:
        return dt.datetime.combine(_parse_date(s), dt.time())
    except ValueError:
        raise ValueError(f"Fecha-hora invalida: {s!r}")


def parse_scalar(s: str, kind: str) -> Any:
    if kind == "int":
        return int(str(s).strip())
    if kind == "float":
        return float(str(s).strip())
    if kind == "bool":
        return _parse_bool(s)
    if kind == "date":
        return _parse_date(s)
    if kind == "datetime":
        return _parse_datetime(s)
    return str(s).strip()


def parse_values(raw: str, kind: str) -> list[Any]:
    """Separa por coma y castea cada elemento al tipo de la columna."""
    parts = [p.strip() for p in str(raw).split(",")]
    parts = [p for p in parts if p != ""]
    if not parts:
        parts = [""]
    return [parse_scalar(p, kind) for p in parts]


# --------------------------------------------------------------------------- #
# Construccion de predicados (expresiones Polars)
# --------------------------------------------------------------------------- #
def build_predicate(spec: FilterSpec, dtype: pl.DataType) -> pl.Expr:
    """Convierte un FilterSpec en una expresion booleana de Polars."""
    kind = dtype_kind(dtype)
    col = pl.col(spec.column)
    op = spec.op
    raw = spec.value

    if op == "is null":
        expr = col.is_null()
    elif op == "is not null":
        expr = col.is_not_null()
    elif op == "is true":
        expr = col == True                       # noqa: E712  (columna booleana)
    elif op == "is false":
        expr = col == False                      # noqa: E712
    elif op in ("in", "not in"):
        vals = parse_values(raw, kind)
        expr = col.is_in(vals)
        if op == "not in":
            expr = ~expr
    elif op in ("=", "!="):
        vals = parse_values(raw, kind)
        expr = col.is_in(vals) if len(vals) > 1 else (col == vals[0])
        if op == "!=":
            expr = ~expr
    elif op == ">":
        expr = col > parse_scalar(raw, kind)
    elif op == ">=":
        expr = col >= parse_scalar(raw, kind)
    elif op == "<":
        expr = col < parse_scalar(raw, kind)
    elif op == "<=":
        expr = col <= parse_scalar(raw, kind)
    elif op == "Like":
        expr = col.cast(pl.Utf8).str.to_lowercase().str.contains(
            raw.strip().lower(), literal=True)
    elif op == "Not Like":
        expr = ~col.cast(pl.Utf8).str.to_lowercase().str.contains(
            raw.strip().lower(), literal=True)
    else:
        raise ValueError(f"Operador no soportado: {op!r}")

    if spec.negate:
        expr = ~expr
    return expr


def apply_filters(lf: pl.LazyFrame,
                  specs: list[FilterSpec],
                  schema: dict[str, pl.DataType],
                  combine: str = "AND",
                  global_negate: bool = False) -> pl.LazyFrame:
    """Aplica todos los filtros activos y devuelve un nuevo LazyFrame."""
    active = [s for s in specs if s.is_active()]
    if not active:
        return lf

    exprs = [build_predicate(s, schema[s.column]) for s in active]

    combined = exprs[0]
    for e in exprs[1:]:
        combined = (combined & e) if combine.upper() == "AND" else (combined | e)

    if global_negate:
        combined = ~combined

    return lf.filter(combined)


# --------------------------------------------------------------------------- #
# Operaciones de salida (materializan solo lo necesario)
# --------------------------------------------------------------------------- #
def unique_values(lf: pl.LazyFrame, column: str, limit: int = 100) -> tuple[list[Any], bool]:
    """
    Devuelve (valores_unicos_ordenados, dentro_del_umbral).
    Si hay mas de `limit` valores unicos, devuelve ([], False).
    """
    out = (lf.select(pl.col(column))
             .unique()
             .limit(limit + 1)
             .collect())
    vals = out.to_series().to_list()
    if len(vals) > limit:
        return [], False
    try:
        vals = sorted(v for v in vals if v is not None)
    except TypeError:
        vals = [v for v in vals if v is not None]
    return vals, True


def search_column_values(lf: pl.LazyFrame, column: str, query: str,
                          limit: int = 300) -> list:
    """Busca en TODO el archivo los valores distintos de `column` que contienen
    `query` (comparado como texto). Sirve para verificar que un valor existe
    aunque la columna tenga demasiados valores unicos para listarlos todos."""
    q = str(query).strip()
    if q == "":
        return []
    ql = q.lower()
    # 'v' conserva el texto original; 'vl' es la version en minusculas para
    # comparar sin distinguir mayusculas/minusculas.
    base = (lf.select(pl.col(column).cast(pl.Utf8).alias("v"))
              .drop_nulls()
              .with_columns(pl.col("v").str.to_lowercase().alias("vl")))

    # 1) coincidencia EXACTA (garantiza que aparezca aunque haya muchas parciales)
    exact = (base.filter(pl.col("vl") == ql).select("v").unique().limit(1)
             .collect().to_series().to_list())

    # 2) coincidencias que CONTIENEN el termino (excluyendo la exacta)
    contains = (base.filter(pl.col("vl").str.contains(ql, literal=True)
                            & (pl.col("vl") != ql))
                .select("v").unique().limit(limit).collect().to_series().to_list())
    try:
        contains = sorted(contains)
    except TypeError:
        pass
    return exact + contains


def count_rows(lf: pl.LazyFrame) -> int:
    return int(lf.select(pl.len()).collect().item())


def preview(lf: pl.LazyFrame, offset: int = 0, limit: int = 200) -> pl.DataFrame:
    return lf.slice(offset, limit).collect()


def min_max(lf: pl.LazyFrame, column: str) -> tuple[Any, Any]:
    out = lf.select(
        pl.col(column).min().alias("min"),
        pl.col(column).max().alias("max"),
    ).collect()
    return out.item(0, "min"), out.item(0, "max")


def describe(df: pl.DataFrame) -> pl.DataFrame:
    """Resumen estadistico tipo pandas/polars .describe():
    count, null_count, mean, std, min, 25%, 50%, 75%, max por columna."""
    return df.describe()


# Etiquetas de las estadisticas y como calcularlas (orden de fila).
_STAT_ROWS = [
    ("count", "count", lambda c: c.count()),
    ("nulos", "nulls", lambda c: c.null_count()),
    ("media", "mean",  lambda c: c.mean()),
    ("std",   "std",   lambda c: c.std()),
    ("min",   "min",   lambda c: c.min()),
    ("25%",   "q25",   lambda c: c.quantile(0.25)),
    ("50%",   "q50",   lambda c: c.median()),
    ("75%",   "q75",   lambda c: c.quantile(0.75)),
    ("max",   "max",   lambda c: c.max()),
]


def _fmt_stat(key: str, v) -> str:
    """Formatea un valor estadistico para mostrarlo limpio en la tabla."""
    if v is None:
        return ""
    if key in ("count", "nulls"):
        try:
            return f"{int(v):,}"
        except (TypeError, ValueError):
            return str(v)
    try:
        fv = float(v)
    except (TypeError, ValueError):
        return str(v)
    av = abs(fv)
    if fv == int(fv) and av < 1e15:
        return f"{int(fv):,}"
    if av != 0 and (av < 1e-3 or av >= 1e6):
        return f"{fv:.3e}"
    return f"{fv:,.3f}"


def describe_numeric(lf: pl.LazyFrame) -> pl.DataFrame:
    """Resumen estadistico (tipo .describe()) calculado de forma LAZY sobre TODO
    el dataset filtrado, SOLO para columnas numericas (entero/flotante). Ignora
    texto, booleano y fecha. Devuelve una tabla: filas = estadisticas, columnas =
    columnas numericas. Si no hay columnas numericas, devuelve un aviso."""
    schema = get_schema(lf)
    num_cols = [c for c, t in schema.items() if dtype_kind(t) in ("int", "float")]
    if not num_cols:
        return pl.DataFrame({
            "estadística": ["(sin columnas numéricas)"],
        })

    aggs = []
    for c in num_cols:
        for _label, key, fn in _STAT_ROWS:
            aggs.append(fn(pl.col(c)).alias(f"{c}\x00{key}"))
    row = lf.select(aggs).collect()

    data: dict[str, list] = {"estadística": [lbl for lbl, _k, _f in _STAT_ROWS]}
    for c in num_cols:
        data[c] = [_fmt_stat(key, row.item(0, f"{c}\x00{key}"))
                   for _lbl, key, _f in _STAT_ROWS]
    return pl.DataFrame(data)


def distribution_data(lf: pl.LazyFrame, column: str, bins: int = 24,
                      top: int = 25) -> dict:
    """Datos de distribucion de UNA columna, calculados sobre TODO el dataset
    filtrado (materializa solo esa columna, no el dataset entero). Sirve para
    dibujar un grafico:

      - Numerica con muchos valores  -> histograma por rangos (forma de campana).
      - Texto / booleana / fecha / pocos valores -> conteo por valor.

    Devuelve dict con: labels, counts, numeric (bool), edges (o None), total,
    truncated (bool: si hay mas categorias de las mostradas)."""
    schema = get_schema(lf)
    dtype = schema.get(column)
    kind = dtype_kind(dtype) if dtype is not None else "str"
    s = lf.select(pl.col(column)).collect().to_series()
    s_nn = s.drop_nulls()

    if kind in ("int", "float") and s_nn.len() > 0 and s.n_unique() > top:
        lo = float(s_nn.min())
        hi = float(s_nn.max())
        h = s_nn.hist(bin_count=bins)
        counts = h.get_column("count").cast(pl.Int64).to_list()
        n = len(counts)
        step = (hi - lo) / n if n else 0
        edges = [lo + i * step for i in range(n + 1)]
        labels = [f"{edges[i]:.3g} – {edges[i + 1]:.3g}" for i in range(n)]
        return {
            "labels": labels, "counts": counts, "numeric": True,
            "edges": edges, "total": int(s_nn.len()), "truncated": False,
            "nulls": int(s.len() - s_nn.len()), "column": column,
        }

    vc = s.value_counts(sort=True)
    truncated = vc.height > top
    vc = vc.head(top)
    first = vc.columns[0]
    labels = ["(nulo)" if v is None else str(v)
              for v in vc.get_column(first).to_list()]
    counts = vc.get_column("count").cast(pl.Int64).to_list()
    return {
        "labels": labels, "counts": counts, "numeric": False,
        "edges": None, "total": int(s.len()), "truncated": truncated,
        "nulls": int(s.null_count()), "column": column,
    }


def distribution(df: pl.DataFrame, column: str, bins: int = 12,
                 top: int = 25) -> pl.DataFrame:
    """(Compat) Distribucion como tabla de texto con barra visual. Se conserva
    por compatibilidad; la GUI usa ahora distribution_data() + grafico."""
    s = df.get_column(column)
    kind = dtype_kind(s.dtype)
    s_nn = s.drop_nulls()

    if kind in ("int", "float") and s_nn.len() > 0 and s.n_unique() > top:
        h = s_nn.hist(bin_count=bins)
        labels = h.get_column("category").cast(pl.Utf8).to_list()
        counts = h.get_column("count").cast(pl.Int64).to_list()
        label_name = "rango"
    else:
        vc = s.value_counts(sort=True).head(top)
        first = vc.columns[0]
        labels = ["(nulo)" if v is None else str(v)
                  for v in vc.get_column(first).to_list()]
        counts = vc.get_column("count").cast(pl.Int64).to_list()
        label_name = "valor"

    total = sum(counts) or 1
    top_n = max(counts) if counts else 1
    pct = [round(c / total * 100, 1) for c in counts]
    bars = ["█" * max(1, round(c / top_n * 22)) for c in counts]
    return pl.DataFrame({
        label_name: labels,
        "conteo": counts,
        "%": pct,
        "distribucion": bars,
    })


def export_csv(lf: pl.LazyFrame, out_path: str, separator: str = ",") -> None:
    """Escribe el resultado filtrado en streaming (memoria acotada)."""
    try:
        lf.sink_csv(out_path, separator=separator)
    except Exception:
        # Fallback si el plan no admite streaming: materializa y escribe.
        lf.collect().write_csv(out_path, separator=separator)
