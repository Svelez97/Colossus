"""
mff_core.py
-----------
Motor de filtrado de archivos masivos (Massive Files Filter).

Toda la logica es pura y testeable sin interfaz grafica. Usa Polars en modo
LAZY (pl.scan_csv / pl.scan_parquet) para poder trabajar con archivos que no
caben en memoria: los filtros se empujan al escaneo y solo se materializa el
resultado (preview / conteo / export en streaming).

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
from dataclasses import dataclass, field
from typing import Any

import polars as pl

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
    """Detecta el separador leyendo la primera linea no vacia."""
    candidates = ["|", ";", "\t", ","]
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
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


def scan_file(path: str, separator: str | None = None, parse_dates: bool = True,
              date_order: str = "auto"):
    """Abre el archivo como LazyFrame (CSV/TXT o Parquet). No lee todo en RAM.

    parse_dates : intenta interpretar columnas de fecha (ISO automatico +
                  deteccion de formatos dd/mm/aaaa, mm/dd/aaaa, etc.).
    date_order  : 'auto' | 'YMD' | 'DMY' | 'MDY'  -> como leer fechas ambiguas.
    """
    lower = path.lower()
    if lower.endswith(".parquet") or lower.endswith(".pq"):
        return pl.scan_parquet(path), separator or ","
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


def export_csv(lf: pl.LazyFrame, out_path: str, separator: str = ",") -> None:
    """Escribe el resultado filtrado en streaming (memoria acotada)."""
    try:
        lf.sink_csv(out_path, separator=separator)
    except Exception:
        # Fallback si el plan no admite streaming: materializa y escribe.
        lf.collect().write_csv(out_path, separator=separator)
