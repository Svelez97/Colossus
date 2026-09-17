"""
generate_test_excel.py
----------------------
Genera un Excel de prueba para Colossus con VARIAS HOJAS y con la data colocada
en distintas posiciones, para probar el panel de "desde que fila/columna empieza
la data".

Hoja principal ("Ventas"): 15.000 filas cuyos ENCABEZADOS estan en la fila 3 y
la data arranca en la columna C (las filas 1-2 y las columnas A-B son basura).

Uso:
    python generate_test_excel.py            # 15.000 filas en 'Ventas'
    python generate_test_excel.py 50000      # otra cantidad
"""
import os
import sys
import time

import polars as pl
import xlsxwriter

CITIES = ["Bogota", "Medellin", "Cali", "Barranquilla", "Cartagena", "Bucaramanga",
          "Pereira", "Manizales", "Cucuta", "Ibague", "Armenia", "Pasto"]
CATS = ["FOOD", "DRUG", "DOLLAR", "TECH", "HOME", "AUTO", "TOYS", "BOOKS"]
REGIONS = ["NORTE", "SUR", "ORIENTE", "OCCIDENTE", "CENTRO"]


def mod(seed: int, k: int):
    return (pl.col("id").hash(seed=seed) % k).cast(pl.Int64)


def make_sales(n: int) -> pl.DataFrame:
    return (
        pl.select(pl.int_range(1, n + 1, dtype=pl.Int64).alias("id"))
        .with_columns(
            ciudad=mod(1, len(CITIES)).replace_strict(list(range(len(CITIES))), CITIES),
            categoria=mod(2, len(CATS)).replace_strict(list(range(len(CATS))), CATS),
            region=mod(3, len(REGIONS)).replace_strict(list(range(len(REGIONS))), REGIONS),
            precio=(mod(2, 1_000_000) / 100.0).round(2),
            cantidad=mod(4, 500),
            activo=(mod(4, 2) == 0),
            fecha=(pl.date(2021, 1, 1) + pl.duration(days=mod(3, 1500))),
        )
    )


def make_clients(n: int) -> pl.DataFrame:
    return (
        pl.select(pl.int_range(1, n + 1, dtype=pl.Int64).alias("id"))
        .with_columns(
            ciudad=mod(5, len(CITIES)).replace_strict(list(range(len(CITIES))), CITIES),
            segmento=mod(6, 3).replace_strict([0, 1, 2], ["A", "B", "C"]),
            saldo=(mod(6, 5_000_00) / 100.0).round(2),
            vip=(mod(7, 4) == 0),
        )
    )


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 15_000
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "test_excel_multi.xlsx")

    t0 = time.time()
    ventas = make_sales(n)
    clientes = make_clients(max(1, n // 3))

    wb = xlsxwriter.Workbook(out)

    # --- Hoja 1: 'Ventas'  ->  encabezados en fila 3, data desde columna C ---
    ventas.write_excel(workbook=wb, worksheet="Ventas", position="C3",
                       table_name="Ventas", autofit=True)
    ws = wb.get_worksheet_by_name("Ventas")
    ws.write("A1", "REPORTE DE VENTAS 2021-2025  ·  CONFIDENCIAL")
    ws.write("A2", f"Generado el {time.strftime('%Y-%m-%d')}  ·  {n:,} registros")

    # --- Hoja 2: 'Clientes'  ->  layout normal (encabezados en fila 1) ---
    clientes.write_excel(workbook=wb, worksheet="Clientes", position="A1",
                         table_name="Clientes", autofit=True)

    # --- Hoja 3: 'Notas'  ->  pocas filas, otra posicion (B5) ---
    notas = pl.DataFrame({"clave": ["moneda", "fuente", "version"],
                          "valor": ["COP", "interno", "1.0"]})
    notas.write_excel(workbook=wb, worksheet="Notas", position="B5",
                      table_name="Notas", autofit=True)

    wb.close()

    size = os.path.getsize(out) / (1024 * 1024)
    print(f"Generado: {out}")
    print(f"  Hojas: Ventas ({n:,} filas, data en C3), "
          f"Clientes ({clientes.height:,} filas, A1), Notas (3 filas, B5)")
    print(f"  Tamano: {size:.1f} MB  ·  {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
