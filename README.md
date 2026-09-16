# Colossus

Interfaz gráfica para **filtrar archivos demasiado grandes para abrir en Excel**.
Construida con **PySide6 (Qt)** + **Polars** en modo *lazy*, así que puede leer y
exportar archivos que no caben en memoria.

Interfaz con **tema claro / oscuro** (botón 🌙/☀️ en la barra superior),
barra de aplicación, tarjetas y botones primarios. Los iconos se dibujan por
código, sin archivos de imagen.

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
| `generate_test_data.py`| Genera un CSV de prueba grande (5M filas ≈ 272 MB). |

Genera datos de prueba con:

```bash
python generate_test_data.py            # 5.000.000 de filas
python generate_test_data.py 20000000   # 20 millones de filas (~1 GB)
```

## Cómo usar

1. **Abrir archivo** → CSV / TXT / TSV / Parquet. El separador se detecta solo
   (`,` `;` `|` tab); puedes forzarlo con el combo *Separador*.
2. **Añadir filtro**: elige columna, operador y valor. Los operadores se adaptan
   al tipo de la columna. Para listas, separa por coma: `Bogota, Cali, Medellin`.
3. **NOT** (icono ⊘) niega solo ese filtro; **Negar todo el resultado** invierte
   el resultado final. Combina los filtros con **AND** u **OR**.
4. **Valores únicos** (panel derecho o la lupa de cada filtro): lista los valores
   distintos de la columna cuando no superan el *Umbral* (por defecto 100). Si lo
   superan, escribe un valor y pulsa **Enter** para verificar que existe (sin
   distinguir mayúsculas). Doble clic inserta el valor en el filtro activo.
5. **Vista previa** / **Contar filas** / **Min / Max** sin exportar.
6. **Exportar CSV**: escribe el resultado en streaming (no carga todo en RAM).

## Tabla de resultados (tipo Excel)

- **Clic** en una cabecera de columna: ordena A→Z / Z→A (y fechas/números de
  menor a mayor y viceversa) sobre la vista previa.
- **Clic derecho** en una cabecera: menú con ordenar y con los **valores únicos
  disponibles** en la vista; al elegir uno se crea un filtro por ese valor.
- Mientras la herramienta trabaja aparece un **icono de carga girando** en la
  barra inferior; cuando termina, simplemente desaparece.

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
```
