"""
generate_test_data.py
----------------------
Genera un CSV de prueba grande para probar Massive Files Filter, con tipos de
dato mixtos (entero, texto, flotante, booleano y fecha) y separador '|'.

Uso:
    python generate_test_data.py            # 5.000.000 de filas (~272 MB)
    python generate_test_data.py 20000000   # 20 millones de filas (~1 GB)
"""
import os
import sys
import time

import polars as pl

CITIES = ["Bogota", "Medellin", "Cali", "Barranquilla", "Cartagena", "Bucaramanga",
          "Pereira", "Manizales", "Cucuta", "Ibague", "Santa Marta", "Villavicencio",
          "Pasto", "Monteria", "Neiva", "Armenia", "Popayan", "Sincelejo", "Tunja",
          "Riohacha"]
CATS = ["FOOD", "DRUG", "DOLLAR", "TECH", "HOME", "AUTO", "TOYS", "BOOKS"]
REGIONS = ["NORTE", "SUR", "ORIENTE", "OCCIDENTE", "CENTRO"]


def mod(seed: int, k: int):
    return (pl.col("id").hash(seed=seed) % k).cast(pl.Int64)


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 5_000_000
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "big_test.csv")

    t0 = time.time()
    df = (
        pl.select(pl.int_range(0, n, dtype=pl.Int64).alias("id"))
        .with_columns(
            city=mod(1, len(CITIES)).replace_strict(list(range(len(CITIES))), CITIES),
            category=mod(2, len(CATS)).replace_strict(list(range(len(CATS))), CATS),
            region=mod(3, len(REGIONS)).replace_strict(list(range(len(REGIONS))), REGIONS),
            price=(mod(2, 1_000_000) / 100.0).round(2),
            qty=mod(4, 500),
            active=(mod(4, 2) == 0),
            created=(pl.date(2020, 1, 1) + pl.duration(days=mod(3, 1500))),
        )
    )
    df.write_csv(out, separator="|")
    size = os.path.getsize(out) / (1024 * 1024)
    print(f"Generado: {n:,} filas  ·  {size:.1f} MB  ·  {time.time() - t0:.1f}s")
    print(f"Ruta: {out}")


if __name__ == "__main__":
    main()
