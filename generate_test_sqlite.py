"""
generate_test_sqlite.py
-----------------------
Genera una base de datos SQLite de prueba para Colossus con VARIAS TABLAS y tipos
de dato mixtos (entero, texto, flotante, "booleano" 0/1 y fecha como texto).

Sirve para probar el selector de tabla al abrir un archivo .db.

Uso:
    python generate_test_sqlite.py            # ventas: 15.000 filas
    python generate_test_sqlite.py 50000      # otra cantidad
"""
import os
import sqlite3
import sys
import time

import polars as pl

CITIES = ["Bogota", "Medellin", "Cali", "Barranquilla", "Cartagena", "Bucaramanga",
          "Pereira", "Manizales", "Cucuta", "Ibague", "Armenia", "Pasto"]
CATS = ["FOOD", "DRUG", "DOLLAR", "TECH", "HOME", "AUTO", "TOYS", "BOOKS"]
REGIONS = ["NORTE", "SUR", "ORIENTE", "OCCIDENTE", "CENTRO"]
NAMES = ["Ana", "Luis", "Marta", "Carlos", "Sofia", "Diego", "Elena", "Jorge",
         "Paula", "Andres"]


def mod(seed: int, k: int):
    return (pl.col("id").hash(seed=seed) % k).cast(pl.Int64)


def make_ventas(n: int) -> pl.DataFrame:
    return (
        pl.select(pl.int_range(1, n + 1, dtype=pl.Int64).alias("id"))
        .with_columns(
            ciudad=mod(1, len(CITIES)).replace_strict(list(range(len(CITIES))), CITIES),
            categoria=mod(2, len(CATS)).replace_strict(list(range(len(CATS))), CATS),
            region=mod(3, len(REGIONS)).replace_strict(list(range(len(REGIONS))), REGIONS),
            precio=(mod(2, 1_000_000) / 100.0).round(2),
            cantidad=mod(4, 500),
            activo=mod(4, 2),                       # 0/1  (SQLite no tiene bool)
            fecha=(pl.date(2021, 1, 1) + pl.duration(days=mod(3, 1500)))
                  .dt.strftime("%Y-%m-%d"),          # fecha como TEXTO
        )
    )


def make_clientes(n: int) -> pl.DataFrame:
    return (
        pl.select(pl.int_range(1, n + 1, dtype=pl.Int64).alias("id"))
        .with_columns(
            nombre=mod(8, len(NAMES)).replace_strict(list(range(len(NAMES))), NAMES),
            ciudad=mod(5, len(CITIES)).replace_strict(list(range(len(CITIES))), CITIES),
            segmento=mod(6, 3).replace_strict([0, 1, 2], ["A", "B", "C"]),
            saldo=(mod(6, 5_000_00) / 100.0).round(2),
            vip=mod(7, 4).cast(pl.Int64).clip(0, 1),   # 0/1
        )
    )


def make_productos() -> pl.DataFrame:
    n = len(CATS) * 6
    return (
        pl.select(pl.int_range(1, n + 1, dtype=pl.Int64).alias("id"))
        .with_columns(
            nombre=("PROD-" + pl.col("id").cast(pl.Utf8).str.zfill(4)),
            categoria=mod(2, len(CATS)).replace_strict(list(range(len(CATS))), CATS),
            precio=(mod(9, 500_00) / 100.0).round(2),
        )
    )


def write_table(con: sqlite3.Connection, name: str, df: pl.DataFrame):
    cols = df.columns
    con.execute(f'DROP TABLE IF EXISTS "{name}"')
    con.execute(f'CREATE TABLE "{name}" ({", ".join(c + " " for c in cols)})')
    placeholders = ", ".join("?" for _ in cols)
    con.executemany(
        f'INSERT INTO "{name}" VALUES ({placeholders})', df.rows())


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 15_000
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "test_multi.db")
    if os.path.exists(out):
        os.remove(out)

    t0 = time.time()
    ventas = make_ventas(n)
    clientes = make_clientes(max(1, n // 3))
    productos = make_productos()

    con = sqlite3.connect(out)
    try:
        write_table(con, "ventas", ventas)
        write_table(con, "clientes", clientes)
        write_table(con, "productos", productos)
        con.commit()
    finally:
        con.close()

    size = os.path.getsize(out) / (1024 * 1024)
    print(f"Generado: {out}")
    print(f"  Tablas: ventas ({ventas.height:,} filas), "
          f"clientes ({clientes.height:,} filas), productos ({productos.height} filas)")
    print(f"  Tamano: {size:.1f} MB  ·  {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
