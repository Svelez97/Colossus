# Massive Files Filter · C.O.R.E

Interfaz gráfica para **filtrar archivos demasiado grandes para abrir en Excel**.
Reescritura del notebook `MFF_UI.ipynb` con **PySide6 (Qt)** + **Polars lazy**.

Interfaz con **tema claro / oscuro** (botón 🌙/☀️ en la barra superior),
barra de aplicación, tarjetas y botones primarios.

## Instalar y ejecutar

```bash
pip install -r requirements.txt
python mff_app.py
```

> Todos los archivos del proyecto viven en esta carpeta `Massive_Files_Filter/`.
> `big_test.csv` es un archivo de prueba de 5.000.000 de filas (272 MB) para
> probar el rendimiento.

## Archivos

| Archivo | Qué hace |
|---|---|
| `mff_app.py`   | La interfaz gráfica (ventana, filtros, tabla, export). |
| `mff_core.py`  | El motor de filtrado con Polars (lógica pura, sin GUI). |
| `mff_icons.py` | Iconos dibujados por código con QPainter (sin archivos de imagen). |

## Cómo usar

1. **Abrir archivo** → CSV / TXT / TSV / Parquet. El separador se detecta solo
   (`,` `;` `|` tab); puedes forzarlo con el combo *Separador*.
2. **Añadir filtro**: elige columna, operador y valor. Los operadores se adaptan
   al tipo de la columna. Para listas, separa por coma: `Bogota, Cali, Medellin`.
3. **NOT** (icono ⊘) niega solo ese filtro; **Negar TODO el resultado** invierte
   el resultado final. Combina los filtros con **AND** u **OR**.
4. **Valores únicos** (panel derecho o la lupa de cada filtro): lista los valores
   distintos de la columna cuando no superan el *Umbral* (por defecto 100).
   Doble clic inserta el valor en el filtro activo.
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

La herramienta lee fechas ISO (`AAAA-MM-DD`) y también `DD/MM/AAAA`,
`MM/DD/AAAA`, `DD-MM-AAAA`, etc. El selector **Fecha** de la barra superior
permite forzar el orden día/mes/año cuando es ambiguo (`auto`, `DMY`, `MDY`,
`YMD`). El botón **Detectar fechas** activa o desactiva toda esta interpretación.

## Novedades frente al notebook original

- **Tipos de dato completos**: entero, flotante, texto, **booleano** y
  **fecha/datetime** (lo que faltaba en tu versión).
- **Archivos pesados**: Polars *lazy* + `sink_csv` en streaming; la tabla de
  preview es virtual (solo dibuja lo visible).
- **Sin imágenes**: los iconos se generan por código.
- Filtros ilimitados (no solo 5), NOT por-filtro, AND/OR, operadores
  `is null` / `is not null` / `is true` / `is false`.
- Operaciones pesadas en segundo plano: la ventana no se congela.
