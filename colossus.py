"""
colossus.py  -  Colossus
========================
Interfaz grafica en PySide6 para filtrar archivos CSV/TXT/Parquet demasiado
grandes para abrir en Excel. Reescritura del notebook MFF original con:

  * Polars en modo LAZY  -> lee archivos que no caben en memoria.
  * Tipos de dato: entero, flotante, texto, BOOLEANO y FECHA/DATETIME.
  * Valores unicos por columna (cuando no superan un umbral, por defecto 100).
  * Negacion por-filtro (NOT) y negacion global. Combina con AND / OR.
  * Iconos dibujados por codigo (sin archivos de imagen).
  * Operaciones pesadas en segundo plano (la ventana no se congela).
  * Sistema de diseno propio con tema CLARO / OSCURO (boton en la barra).

Requisitos:  pip install polars pyarrow PySide6
Ejecutar:    python colossus.py
"""
from __future__ import annotations

import os
import sys
import traceback

import polars as pl
from PySide6.QtCore import (
    Qt, QAbstractTableModel, QModelIndex, QObject, QRunnable, QThreadPool,
    Signal, Slot, QTimer, QSize, QRectF,
)
from PySide6.QtGui import QColor, QPalette, QPainter, QPen
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QLabel, QLineEdit, QComboBox, QCheckBox,
    QPushButton, QToolButton, QHBoxLayout, QVBoxLayout, QSplitter, QScrollArea,
    QFrame, QListWidget, QListWidgetItem, QTableView, QSpinBox, QFileDialog,
    QMessageBox, QHeaderView, QMenu, QGraphicsDropShadowEffect, QSizePolicy,
)

import colossus_core as core
from colossus_icons import make_icon, make_pixmap


# --------------------------------------------------------------------------- #
# Paletas de color (sistema de diseno)
# --------------------------------------------------------------------------- #
PALETTES = {
    "light": {
        "bg": "#EDEFF3", "appbar": "#1D2230", "appbar_text": "#F4F6FB",
        "appbar_sub": "#9AA3B8", "surface": "#FFFFFF", "surface_alt": "#F6F7FA",
        "border": "#E1E4EC", "text": "#232838", "subtext": "#6B7280",
        "accent": "#E4572E", "accent_hover": "#C8461F", "accent_soft": "#FBE3D9",
        "table_header": "#F1F3F8", "selection": "#FBE3D9", "grid": "#EDEFF3",
        "field": "#FFFFFF", "shadow": 45,
    },
    "dark": {
        "bg": "#0F1218", "appbar": "#0A0C11", "appbar_text": "#EAECF3",
        "appbar_sub": "#7C8397", "surface": "#191D27", "surface_alt": "#212632",
        "border": "#2A3040", "text": "#E4E7F0", "subtext": "#98A0B2",
        "accent": "#FF6B3D", "accent_hover": "#FF855F", "accent_soft": "#7A4126",
        "table_header": "#212632", "selection": "#7A4126", "grid": "#242A38",
        "field": "#141821", "shadow": 120,
    },
}
NEUTRAL_ICON = "#8A90A2"   # gris que se ve bien en claro y oscuro

# Check blanco (SVG embebido) para la casilla activada -> activacion inequivoca
import urllib.parse as _up
_CHECK_SVG = ("<svg xmlns='http://www.w3.org/2000/svg' width='14' height='14' "
              "viewBox='0 0 14 14'><path d='M3 7.4 L5.8 10.2 L11 4.2' fill='none' "
              "stroke='white' stroke-width='2' stroke-linecap='round' "
              "stroke-linejoin='round'/></svg>")
CHECK_URI = "data:image/svg+xml;utf8," + _up.quote(_CHECK_SVG)


def build_palette(p: dict) -> QPalette:
    """Paleta base (necesaria para que Fusion pinte tablas/campos con el tema)."""
    pal = QPalette()
    pal.setColor(QPalette.Window, QColor(p["bg"]))
    pal.setColor(QPalette.WindowText, QColor(p["text"]))
    pal.setColor(QPalette.Base, QColor(p["field"]))
    pal.setColor(QPalette.AlternateBase, QColor(p["surface_alt"]))
    pal.setColor(QPalette.Text, QColor(p["text"]))
    pal.setColor(QPalette.Button, QColor(p["surface"]))
    pal.setColor(QPalette.ButtonText, QColor(p["text"]))
    pal.setColor(QPalette.ToolTipBase, QColor(p["surface"]))
    pal.setColor(QPalette.ToolTipText, QColor(p["text"]))
    pal.setColor(QPalette.Highlight, QColor(p["accent"]))
    pal.setColor(QPalette.HighlightedText, QColor("#FFFFFF"))
    pal.setColor(QPalette.PlaceholderText, QColor(p["subtext"]))
    dis = QPalette.Disabled
    pal.setColor(dis, QPalette.Text, QColor(p["subtext"]))
    pal.setColor(dis, QPalette.ButtonText, QColor(p["subtext"]))
    pal.setColor(dis, QPalette.WindowText, QColor(p["subtext"]))
    return pal


def build_qss(p: dict) -> str:
    return f"""
* {{ font-family: 'Segoe UI', 'Inter', Arial; font-size: 12px; }}
QMainWindow, QWidget {{ color: {p['text']}; }}
QMainWindow {{ background: {p['bg']}; }}
#Root {{ background: {p['bg']}; }}

/* ---------- Barra de aplicacion ---------- */
#AppBar {{ background: {p['appbar']}; border: none; }}
#AppTitle {{ color: {p['appbar_text']}; font-size: 19px; font-weight: 800;
             letter-spacing: 0.5px; }}
#AppSub {{ color: {p['appbar_sub']}; font-size: 10px; font-weight: 700;
           letter-spacing: 2px; }}
#FileChip {{ color: {p['appbar_text']}; background: rgba(255,255,255,0.08);
             border: 1px solid rgba(255,255,255,0.10); border-radius: 8px;
             padding: 5px 12px; font-weight: 600; }}
#AppBar QLabel {{ color: {p['appbar_sub']}; }}
#AppBar QComboBox, #AppBar QCheckBox {{ color: {p['appbar_text']}; }}
#AppBar QComboBox {{ background: rgba(255,255,255,0.08);
             border: 1px solid rgba(255,255,255,0.12); }}

/* ---------- Tarjetas y secciones ---------- */
#Card {{ background: {p['surface']}; border: 1px solid {p['border']};
         border-radius: 14px; }}
#SectionTitle {{ font-size: 13px; font-weight: 800; color: {p['text']}; }}
#SectionHint {{ color: {p['subtext']}; font-size: 11px; }}
#ColHead {{ color: {p['subtext']}; font-weight: 700; font-size: 10px;
            letter-spacing: 0.5px; }}

/* ---------- Fila de filtro ---------- */
#FilterRow {{ background: {p['surface_alt']}; border: 1px solid {p['border']};
             border-radius: 10px; }}

/* ---------- Botones ---------- */
QPushButton {{ background: {p['surface']}; color: {p['text']};
    border: 1px solid {p['border']}; border-radius: 9px;
    padding: 7px 14px; font-weight: 600; }}
QPushButton:hover {{ background: {p['surface_alt']}; border-color: {p['accent']}; }}
QPushButton:disabled {{ color: {p['subtext']}; border-color: {p['border']};
    background: {p['surface']}; }}
QPushButton[primary="true"] {{ background: {p['accent']}; color: #FFFFFF;
    border: 1px solid {p['accent']}; }}
QPushButton[primary="true"]:hover {{ background: {p['accent_hover']};
    border-color: {p['accent_hover']}; }}
QPushButton[primary="true"]:disabled {{ background: {p['accent_soft']};
    color: rgba(255,255,255,0.85); border-color: {p['accent_soft']}; }}

QToolButton {{ border: 1px solid transparent; border-radius: 8px; padding: 3px; }}
QToolButton:hover {{ background: {p['surface']}; border-color: {p['border']}; }}
QToolButton:checked {{ background: {p['accent_soft']}; border-color: {p['accent']}; }}
#ThemeBtn {{ background: rgba(255,255,255,0.08); border-radius: 9px;
            padding: 6px 10px; font-size: 15px; }}
#ThemeBtn:hover {{ background: rgba(255,255,255,0.16); }}

/* ---------- Campos ---------- */
QComboBox, QLineEdit, QSpinBox {{ background: {p['field']}; color: {p['text']};
    border: 1px solid {p['border']}; border-radius: 8px; padding: 6px 9px;
    selection-background-color: {p['accent']}; selection-color: #FFFFFF; }}
QComboBox:focus, QLineEdit:focus, QSpinBox:focus {{ border: 1px solid {p['accent']}; }}
QComboBox:disabled, QLineEdit:disabled, QSpinBox:disabled {{ color: {p['subtext']}; }}
QComboBox::drop-down {{ border: none; width: 20px; }}
QComboBox QAbstractItemView {{ background: {p['surface']}; color: {p['text']};
    border: 1px solid {p['border']}; border-radius: 8px;
    selection-background-color: {p['accent_soft']}; selection-color: {p['text']};
    outline: none; padding: 4px; }}
QCheckBox {{ spacing: 7px; }}
QCheckBox::indicator {{ width: 17px; height: 17px; border-radius: 5px;
    border: 1px solid {p['border']}; background: {p['field']}; }}
QCheckBox::indicator:checked {{ background: {p['accent']};
    border-color: {p['accent']}; image: url("{CHECK_URI}"); }}

/* ---------- Tabla ---------- */
QTableView {{ background: {p['surface']}; alternate-background-color: {p['surface_alt']};
    gridline-color: {p['grid']}; border: 1px solid {p['border']};
    border-radius: 10px; selection-background-color: {p['selection']};
    selection-color: {p['text']}; }}
QTableView::item {{ padding: 5px 6px; }}
QHeaderView::section {{ background: {p['table_header']}; color: {p['subtext']};
    padding: 8px 8px; border: none; border-right: 1px solid {p['grid']};
    border-bottom: 1px solid {p['border']}; font-weight: 700; }}
QHeaderView::section:vertical {{ border-right: 1px solid {p['border']}; }}
QTableCornerButton::section {{ background: {p['table_header']};
    border: none; border-bottom: 1px solid {p['border']}; }}

/* ---------- Lista de valores unicos ---------- */
QListWidget {{ background: {p['field']}; color: {p['text']};
    border: 1px solid {p['border']}; border-radius: 8px; padding: 4px; outline: none; }}
QListWidget::item {{ padding: 5px 7px; border-radius: 6px; }}
QListWidget::item:selected {{ background: {p['accent_soft']}; color: {p['text']}; }}
QListWidget::item:hover {{ background: {p['surface_alt']}; }}

/* ---------- Barra de estado y scrollbars ---------- */
QStatusBar {{ background: {p['surface']}; color: {p['subtext']};
    border-top: 1px solid {p['border']}; }}
QStatusBar::item {{ border: none; }}
QScrollBar:vertical {{ background: transparent; width: 11px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {p['border']}; border-radius: 5px;
    min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: {p['subtext']}; }}
QScrollBar:horizontal {{ background: transparent; height: 11px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {p['border']}; border-radius: 5px;
    min-width: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QMenu {{ background: {p['surface']}; color: {p['text']};
    border: 1px solid {p['border']}; border-radius: 8px; padding: 4px; }}
QMenu::item {{ padding: 5px 22px 5px 12px; border-radius: 6px; }}
QMenu::item:selected {{ background: {p['accent_soft']}; }}
"""


# --------------------------------------------------------------------------- #
# Ejecucion en segundo plano (para no congelar la UI con archivos pesados)
# --------------------------------------------------------------------------- #
class Spinner(QWidget):
    """Icono de carga girando. Visible solo mientras hay trabajo en curso."""

    def __init__(self, size: int = 18, color: str = "#E4572E", parent=None):
        super().__init__(parent)
        self._size = size
        self._color = QColor(color)
        self._angle = 0
        self.setFixedSize(size, size)
        self._timer = QTimer(self)
        self._timer.setInterval(80)
        self._timer.timeout.connect(self._tick)
        self.hide()

    def set_color(self, color: str):
        self._color = QColor(color)
        self.update()

    def _tick(self):
        self._angle = (self._angle + 30) % 360
        self.update()

    def start(self):
        if not self._timer.isActive():
            self._timer.start()
        self.show()

    def stop(self):
        self._timer.stop()
        self.hide()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.translate(self._size / 2, self._size / 2)
        p.rotate(self._angle)
        n = 12
        r_out = self._size / 2 - 1
        r_in = r_out * 0.5
        pen = QPen()
        pen.setCapStyle(Qt.RoundCap)
        pen.setWidthF(max(1.4, self._size * 0.09))
        for i in range(n):
            c = QColor(self._color)
            c.setAlphaF((i + 1) / n)          # estela que se desvanece
            pen.setColor(c)
            p.setPen(pen)
            p.drawLine(0, int(r_in), 0, int(r_out))
            p.rotate(360 / n)
        p.end()


class WorkerSignals(QObject):
    done = Signal(object)
    error = Signal(str)


class Worker(QRunnable):
    def __init__(self, fn, *args, **kwargs):
        super().__init__()
        self.fn, self.args, self.kwargs = fn, args, kwargs
        self.signals = WorkerSignals()

    @Slot()
    def run(self):
        try:
            result = self.fn(*self.args, **self.kwargs)
        except Exception as exc:  # noqa: BLE001
            traceback.print_exc()
            self.signals.error.emit(f"{type(exc).__name__}: {exc}")
        else:
            self.signals.done.emit(result)


# --------------------------------------------------------------------------- #
# Modelo de tabla respaldado por un DataFrame de Polars (para el preview)
# --------------------------------------------------------------------------- #
class PolarsTableModel(QAbstractTableModel):
    def __init__(self, df: pl.DataFrame | None = None):
        super().__init__()
        self._df = df if df is not None else pl.DataFrame()
        self._muted = QColor("#9AA0AE")

    def set_df(self, df: pl.DataFrame):
        self.beginResetModel()
        self._df = df
        self.endResetModel()

    def sort(self, column: int, order=Qt.AscendingOrder):
        """Ordena la vista previa por una columna (a-z, z-a, fechas/numeros).
        Polars ordena segun el tipo real de la columna."""
        if self._df.height == 0 or column < 0 or column >= self._df.width:
            return
        name = self._df.columns[column]
        descending = order == Qt.DescendingOrder
        self.beginResetModel()
        self._df = self._df.sort(name, descending=descending, nulls_last=True)
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else self._df.height

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else self._df.width

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        if role in (Qt.DisplayRole, Qt.ToolTipRole):
            val = self._df.item(index.row(), index.column())
            return "" if val is None else str(val)
        if role == Qt.ForegroundRole:
            if self._df.item(index.row(), index.column()) is None:
                return self._muted
        return None

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role != Qt.DisplayRole:
            return None
        if orientation == Qt.Horizontal:
            return self._df.columns[section]
        return str(section + 1)


# --------------------------------------------------------------------------- #
# QLineEdit que avisa cuando recibe el foco (para saber a que filtro insertar)
# --------------------------------------------------------------------------- #
class FocusLineEdit(QLineEdit):
    focused = Signal(object)

    def focusInEvent(self, event):
        super().focusInEvent(event)
        self.focused.emit(self)


# --------------------------------------------------------------------------- #
# Una fila de filtro:  [x] columna  operador  valor  [NOT] [unicos] [borrar]
# --------------------------------------------------------------------------- #
class FilterRow(QFrame):
    changed = Signal()
    removed = Signal(object)
    value_focused = Signal(object)

    def __init__(self, window: "MainWindow"):
        super().__init__()
        self.window = window
        self.setObjectName("FilterRow")

        self.enabled = QCheckBox()
        self.enabled.setChecked(True)
        self.enabled.setToolTip("Activar / desactivar este filtro")

        self.column = QComboBox()
        self.column.setMinimumWidth(200)
        self.column.setToolTip("Columna a filtrar")

        self.op = QComboBox()
        self.op.setMinimumWidth(104)
        self.op.setToolTip("Operador")

        self.value = FocusLineEdit()
        self.value.setPlaceholderText("valor   ·   listas separadas por coma:  a, b, c")
        self.value.setToolTip("Valor(es) del filtro")

        self.not_btn = QToolButton()
        self.not_btn.setIcon(make_icon("not", 22))
        self.not_btn.setCheckable(True)
        self.not_btn.setToolTip("Negar SOLO este filtro (NOT)")

        self.uniq_btn = QToolButton()
        self.uniq_btn.setIcon(make_icon("search", 22, color=NEUTRAL_ICON))
        self.uniq_btn.setToolTip("Ver valores unicos de la columna")

        self.del_btn = QToolButton()
        self.del_btn.setIcon(make_icon("trash", 22, color=NEUTRAL_ICON))
        self.del_btn.setToolTip("Quitar este filtro")

        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(8)
        lay.addWidget(self.enabled)
        lay.addWidget(self.column)
        lay.addWidget(self.op)
        lay.addWidget(self.value, 1)
        lay.addWidget(self.not_btn)
        lay.addWidget(self.uniq_btn)
        lay.addWidget(self.del_btn)

        self.column.currentTextChanged.connect(self._on_column_changed)
        self.op.currentTextChanged.connect(self._on_op_changed)
        self.op.currentTextChanged.connect(self.changed)
        self.value.textChanged.connect(self.changed)
        self.enabled.stateChanged.connect(self.changed)
        self.not_btn.toggled.connect(self.changed)
        self.uniq_btn.clicked.connect(self._show_uniques)
        self.del_btn.clicked.connect(lambda: self.removed.emit(self))
        self.value.focused.connect(lambda _=None: self.value_focused.emit(self))

    def set_columns(self, schema: dict):
        self.column.blockSignals(True)
        self.column.clear()
        for name, dtype in schema.items():
            self.column.addItem(f"{name}   ·{core.dtype_label(dtype)}", userData=name)
        self.column.setCurrentIndex(-1)
        self.column.blockSignals(False)

    def _current_column(self):
        idx = self.column.currentIndex()
        return None if idx < 0 else self.column.itemData(idx)

    def _current_dtype(self):
        name = self._current_column()
        return None if name is None else self.window.schema.get(name)

    def _on_column_changed(self, _text):
        dtype = self._current_dtype()
        self.op.blockSignals(True)
        self.op.clear()
        if dtype is not None:
            self.op.addItems(core.ops_for(dtype))
        self.op.blockSignals(False)
        self._on_op_changed(self.op.currentText())
        self.changed.emit()

    def _on_op_changed(self, op):
        no_value = op in core.OPS_NO_VALUE
        self.value.setEnabled(not no_value)
        if no_value:
            self.value.clear()

    def _show_uniques(self):
        col = self._current_column()
        if not col:
            return
        self.uniq_btn.setEnabled(False)

        def done(result):
            self.uniq_btn.setEnabled(True)
            vals, ok = result
            menu = QMenu(self)
            if not ok:
                menu.addAction("Demasiados valores unicos (> umbral)").setEnabled(False)
            elif not vals:
                menu.addAction("(sin valores)").setEnabled(False)
            else:
                for v in vals[:300]:
                    menu.addAction(str(v)).setData(str(v))
            menu.triggered.connect(self._insert_value)
            menu.exec(self.uniq_btn.mapToGlobal(self.uniq_btn.rect().bottomLeft()))

        def err(msg):
            self.uniq_btn.setEnabled(True)
            self.window.error(msg)

        self.window.compute_unique(col, done, err)

    def _insert_value(self, action):
        text = action.data()
        if text is None:
            return
        cur = self.value.text().strip()
        self.value.setText(f"{cur}, {text}" if cur else text)

    def to_spec(self) -> core.FilterSpec:
        return core.FilterSpec(
            column=self._current_column() or "",
            op=self.op.currentText(),
            value=self.value.text(),
            negate=self.not_btn.isChecked(),
            enabled=self.enabled.isChecked(),
        )


# --------------------------------------------------------------------------- #
# Utilidades de UI
# --------------------------------------------------------------------------- #
def card(shadow_alpha: int = 45) -> QFrame:
    f = QFrame()
    f.setObjectName("Card")
    eff = QGraphicsDropShadowEffect(f)
    eff.setBlurRadius(28)
    eff.setXOffset(0)
    eff.setYOffset(7)
    eff.setColor(QColor(20, 24, 40, shadow_alpha))
    f.setGraphicsEffect(eff)
    return f


def primary(btn: QPushButton) -> QPushButton:
    btn.setProperty("primary", True)
    return btn


def section_title(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setObjectName("SectionTitle")
    return lbl


# --------------------------------------------------------------------------- #
# Ventana principal
# --------------------------------------------------------------------------- #
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Colossus")
        self.setWindowIcon(make_icon("logo", 64))
        self.resize(1380, 840)
        self.setMinimumSize(1060, 620)

        self.pool = QThreadPool.globalInstance()
        self.path: str | None = None
        self.sep: str = ","
        self.schema: dict = {}
        self.filter_rows: list[FilterRow] = []
        self.active_row: FilterRow | None = None
        self._busy = 0
        self._workers: set = set()
        self._theme = "light"
        self._uniq_overflow = False
        self._uniq_all: list = []

        self._build_ui()
        self.apply_theme("light")
        self._set_loaded(False)

    # ------------------------------------------------------------------ UI --
    def _build_ui(self):
        root = QWidget()
        root.setObjectName("Root")
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        outer.addWidget(self._build_appbar())

        body = QWidget()
        blay = QVBoxLayout(body)
        blay.setContentsMargins(18, 16, 18, 12)
        blay.setSpacing(14)
        outer.addWidget(body, 1)

        splitter = QSplitter(Qt.Vertical)
        splitter.setHandleWidth(10)
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(self._build_filters_card())

        bottom = QSplitter(Qt.Horizontal)
        bottom.setHandleWidth(10)
        bottom.setChildrenCollapsible(False)
        bottom.addWidget(self._build_results_card())
        bottom.addWidget(self._build_unique_card())
        bottom.setStretchFactor(0, 3)
        bottom.setStretchFactor(1, 1)
        splitter.addWidget(bottom)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([300, 520])
        blay.addWidget(splitter, 1)

        self.status = self.statusBar()
        self.status.showMessage("Abre un archivo para comenzar.")
        self.busy_lbl = QLabel("")
        self.busy_lbl.setObjectName("SectionHint")
        self.spinner = Spinner(16, PALETTES["light"]["accent"])
        self.status.addPermanentWidget(self.busy_lbl)
        self.status.addPermanentWidget(self.spinner)

    # ---- barra de aplicacion ---- #
    def _build_appbar(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("AppBar")
        bar.setFixedHeight(64)
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(18, 0, 16, 0)
        lay.setSpacing(12)

        logo = QLabel()
        logo.setPixmap(make_pixmap("logo", 38))
        lay.addWidget(logo)

        t = QLabel("Colossus")
        t.setObjectName("AppTitle")
        lay.addWidget(t)

        lay.addSpacing(18)
        self.open_btn = primary(QPushButton("  Abrir archivo"))
        self.open_btn.setIcon(make_icon("folder", 22, color="#FFFFFF"))
        self.open_btn.clicked.connect(self.open_file)
        lay.addWidget(self.open_btn)

        self.file_chip = QLabel("Ningun archivo")
        self.file_chip.setObjectName("FileChip")
        self.file_chip.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Preferred)
        lay.addWidget(self.file_chip)

        lay.addStretch(1)

        lay.addWidget(QLabel("Separador"))
        self.sep_combo = QComboBox()
        self.sep_combo.addItem("auto", None)
        self.sep_combo.addItem(",", ",")
        self.sep_combo.addItem("|", "|")
        self.sep_combo.addItem(";", ";")
        self.sep_combo.addItem("tab", "\t")
        self.sep_combo.currentIndexChanged.connect(self._reload_if_open)
        lay.addWidget(self.sep_combo)

        self.dates_chk = QCheckBox("Detectar fechas")
        self.dates_chk.setChecked(True)
        self.dates_chk.setToolTip(
            "Interpreta columnas de fecha (ISO + formatos dd/mm/aaaa, mm/dd/aaaa).\n"
            "Desactivalo para leer TODO como texto/numero.")
        self.dates_chk.stateChanged.connect(self._reload_if_open)
        lay.addWidget(self.dates_chk)

        self.date_order = QComboBox()
        self.date_order.addItem("Fecha: auto", "auto")
        self.date_order.addItem("AAAA-MM-DD", "YMD")
        self.date_order.addItem("DD/MM/AAAA", "DMY")
        self.date_order.addItem("MM/DD/AAAA", "MDY")
        self.date_order.setToolTip("Orden de dia/mes/ano para fechas ambiguas")
        self.date_order.currentIndexChanged.connect(self._reload_if_open)
        lay.addWidget(self.date_order)

        self.theme_btn = QToolButton()
        self.theme_btn.setObjectName("ThemeBtn")
        self.theme_btn.setText("🌙")
        self.theme_btn.setToolTip("Cambiar tema claro / oscuro")
        self.theme_btn.clicked.connect(self.toggle_theme)
        lay.addWidget(self.theme_btn)
        return bar

    # ---- tarjeta de filtros ---- #
    def _build_filters_card(self) -> QWidget:
        c = card()
        lay = QVBoxLayout(c)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(10)

        bar = QHBoxLayout()
        bar.setSpacing(10)
        icon = QLabel()
        icon.setPixmap(make_pixmap("funnel", 20))
        bar.addWidget(icon)
        bar.addWidget(section_title("Filtros"))

        self.add_btn = QPushButton("  Anadir filtro")
        self.add_btn.setIcon(make_icon("plus", 20, color=NEUTRAL_ICON))
        self.add_btn.clicked.connect(lambda: self.add_filter_row())
        bar.addWidget(self.add_btn)

        bar.addSpacing(6)
        bar.addWidget(QLabel("Combinar"))
        self.combine_combo = QComboBox()
        self.combine_combo.addItems(["AND", "OR"])
        self.combine_combo.setToolTip("AND = cumplir todos · OR = cumplir alguno")
        bar.addWidget(self.combine_combo)

        self.negate_chk = QCheckBox("Negar todo el resultado")
        self.negate_chk.setToolTip("Invierte el resultado final")
        bar.addWidget(self.negate_chk)

        bar.addStretch(1)
        bar.addWidget(QLabel("Exportar como"))
        self.export_name = QLineEdit()
        self.export_name.setPlaceholderText("nombre_salida")
        self.export_name.setFixedWidth(190)
        bar.addWidget(self.export_name)
        self.export_btn = primary(QPushButton("  Exportar CSV"))
        self.export_btn.setIcon(make_icon("export", 22, color="#FFFFFF"))
        self.export_btn.clicked.connect(self.do_export)
        bar.addWidget(self.export_btn)
        lay.addLayout(bar)

        head = QHBoxLayout()
        head.setContentsMargins(12, 0, 12, 0)
        head.setSpacing(8)
        for text, w in (("ON", 26), ("COLUMNA", 208), ("OPERADOR", 112),
                        ("VALOR", 0)):
            l = QLabel(text)
            l.setObjectName("ColHead")
            if w:
                l.setFixedWidth(w)
            head.addWidget(l, 0 if w else 1)
        head.addSpacing(110)
        lay.addLayout(head)

        self.rows_container = QWidget()
        self.rows_layout = QVBoxLayout(self.rows_container)
        self.rows_layout.setContentsMargins(0, 0, 0, 0)
        self.rows_layout.setSpacing(8)
        self.rows_layout.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(self.rows_container)
        scroll.setMinimumHeight(120)
        lay.addWidget(scroll)
        return c

    # ---- tarjeta de resultados ---- #
    def _build_results_card(self) -> QWidget:
        c = card()
        lay = QVBoxLayout(c)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(10)

        bar = QHBoxLayout()
        bar.setSpacing(8)
        icon = QLabel()
        icon.setPixmap(make_pixmap("eye", 20))
        bar.addWidget(icon)
        bar.addWidget(section_title("Resultados"))
        bar.addSpacing(6)

        self.preview_btn = primary(QPushButton("  Vista previa"))
        self.preview_btn.setIcon(make_icon("eye", 20, color="#FFFFFF"))
        self.preview_btn.clicked.connect(self.do_preview)
        bar.addWidget(self.preview_btn)

        bar.addWidget(QLabel("Desde"))
        self.offset_spin = QSpinBox()
        self.offset_spin.setRange(0, 2_000_000_000)
        self.offset_spin.setSingleStep(200)
        self.offset_spin.setFixedWidth(110)
        bar.addWidget(self.offset_spin)

        bar.addWidget(QLabel("Limite"))
        self.limit_spin = QSpinBox()
        self.limit_spin.setRange(1, 100000)
        self.limit_spin.setValue(500)
        self.limit_spin.setFixedWidth(90)
        bar.addWidget(self.limit_spin)

        self.count_btn = QPushButton("  Contar")
        self.count_btn.setIcon(make_icon("count", 20, color=NEUTRAL_ICON))
        self.count_btn.clicked.connect(self.do_count)
        bar.addWidget(self.count_btn)

        bar.addStretch(1)
        self.minmax_combo = QComboBox()
        self.minmax_combo.setMinimumWidth(150)
        self.minmax_combo.setToolTip("Columna para Min/Max")
        bar.addWidget(self.minmax_combo)
        self.minmax_btn = QPushButton("  Min / Max")
        self.minmax_btn.setIcon(make_icon("stats", 20, color=NEUTRAL_ICON))
        self.minmax_btn.clicked.connect(self.do_minmax)
        bar.addWidget(self.minmax_btn)
        lay.addLayout(bar)

        self.table = QTableView()
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(True)
        self.table.setSelectionBehavior(QTableView.SelectRows)
        self.table.verticalHeader().setDefaultSectionSize(28)
        hdr = self.table.horizontalHeader()
        hdr.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        hdr.setSectionResizeMode(QHeaderView.Interactive)
        hdr.setSectionsClickable(True)
        hdr.setSortIndicatorShown(True)
        hdr.sectionClicked.connect(self._sort_clicked)          # clic = ordenar
        hdr.setContextMenuPolicy(Qt.CustomContextMenu)
        hdr.customContextMenuRequested.connect(self._header_menu)  # clic der = menu
        self.model = PolarsTableModel()
        self.table.setModel(self.model)
        self._sort_col, self._sort_order = -1, Qt.AscendingOrder
        lay.addWidget(self.table, 1)

        self.preview_info = QLabel("Sin datos todavia. Carga un archivo y pulsa "
                                   "‘Vista previa’.  ·  Clic en una cabecera "
                                   "para ordenar; clic derecho para filtrar por valor.")
        self.preview_info.setObjectName("SectionHint")
        lay.addWidget(self.preview_info)
        return c

    # ---- ordenar / menu de cabecera (estilo Excel) ---- #
    def _sort_clicked(self, col: int):
        order = (Qt.DescendingOrder
                 if (self._sort_col == col and self._sort_order == Qt.AscendingOrder)
                 else Qt.AscendingOrder)
        self._sort_set(col, order)

    def _sort_set(self, col: int, order):
        self._sort_col, self._sort_order = col, order
        self.table.horizontalHeader().setSortIndicator(col, order)
        self.model.sort(col, order)

    def _header_menu(self, pos):
        hdr = self.table.horizontalHeader()
        col = hdr.logicalIndexAt(pos)
        df = self.model._df
        if col < 0 or df.width == 0:
            return
        name = df.columns[col]
        menu = QMenu(self)
        menu.addAction("Ordenar  A → Z   ·   menor a mayor",
                       lambda: self._sort_set(col, Qt.AscendingOrder))
        menu.addAction("Ordenar  Z → A   ·   mayor a menor",
                       lambda: self._sort_set(col, Qt.DescendingOrder))
        menu.addSeparator()

        try:
            vals = [v for v in df.get_column(name).unique().to_list() if v is not None]
            try:
                vals = sorted(vals)
            except TypeError:
                pass
        except Exception:
            vals = []
        sub = menu.addMenu(f"Filtrar por valor   ({len(vals)} en la vista)")
        if not vals:
            sub.addAction("(sin valores)").setEnabled(False)
        else:
            for v in vals[:100]:
                sub.addAction(str(v), lambda v=v: self._add_filter_from_header(name, v))
            if len(vals) > 100:
                sub.addSeparator()
                sub.addAction(f"... y {len(vals) - 100} mas").setEnabled(False)
        menu.exec(hdr.mapToGlobal(pos))

    def _add_filter_from_header(self, column: str, value):
        row = self.add_filter_row()
        for i in range(row.column.count()):
            if row.column.itemData(i) == column:
                row.column.setCurrentIndex(i)
                break
        if "=" in [row.op.itemText(i) for i in range(row.op.count())]:
            row.op.setCurrentText("=")
        row.value.setText(str(value))
        self.do_preview()

    # ---- tarjeta de valores unicos ---- #
    def _build_unique_card(self) -> QWidget:
        c = card()
        lay = QVBoxLayout(c)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(10)

        bar = QHBoxLayout()
        icon = QLabel()
        icon.setPixmap(make_pixmap("search", 20))
        bar.addWidget(icon)
        bar.addWidget(section_title("Valores unicos"))
        bar.addStretch(1)
        lay.addLayout(bar)

        self.uniq_col = QComboBox()
        self.uniq_col.setToolTip("Columna a explorar")
        self.uniq_col.currentIndexChanged.connect(self._load_unique_panel)
        lay.addWidget(self.uniq_col)

        row = QHBoxLayout()
        row.addWidget(QLabel("Umbral"))
        self.uniq_limit = QSpinBox()
        self.uniq_limit.setRange(1, 100000)
        self.uniq_limit.setValue(100)
        self.uniq_limit.setToolTip("Maximo de valores unicos a listar")
        self.uniq_limit.editingFinished.connect(self._load_unique_panel)
        row.addWidget(self.uniq_limit)
        row.addStretch(1)
        lay.addLayout(row)

        self.uniq_search = QLineEdit()
        self.uniq_search.setPlaceholderText("Buscar...")
        self.uniq_search.textChanged.connect(self._filter_unique_list)
        self.uniq_search.returnPressed.connect(self._search_unique_overflow)
        lay.addWidget(self.uniq_search)

        self.uniq_list = QListWidget()
        self.uniq_list.setToolTip("Doble clic para insertar en el filtro activo")
        self.uniq_list.itemDoubleClicked.connect(self._unique_to_filter)
        lay.addWidget(self.uniq_list, 1)

        self.uniq_status = QLabel("Elige una columna.")
        self.uniq_status.setObjectName("SectionHint")
        self.uniq_status.setWordWrap(True)
        lay.addWidget(self.uniq_status)
        return c

    # -------------------------------------------------------------- temas --
    def apply_theme(self, name: str):
        self._theme = name
        p = PALETTES[name]
        app = QApplication.instance()
        if app:
            app.setPalette(build_palette(p))
            app.setStyleSheet(build_qss(p))
        self.model._muted = QColor(p["subtext"])
        self.spinner.set_color(p["accent"])
        self.theme_btn.setText("☀️" if name == "dark" else "🌙")
        self._repolish(self)

    @staticmethod
    def _repolish(root: QWidget):
        """Fuerza re-pintado completo tras cambiar de tema (evita cache viejo)."""
        widgets = [root] + root.findChildren(QWidget)
        for w in widgets:
            w.style().unpolish(w)
            w.style().polish(w)
            w.update()

    def toggle_theme(self):
        self.apply_theme("dark" if self._theme == "light" else "light")

    # -------------------------------------------------------------- estado --
    def _set_loaded(self, ok: bool):
        for w in (self.add_btn, self.preview_btn, self.count_btn, self.minmax_btn,
                  self.minmax_combo, self.combine_combo, self.negate_chk,
                  self.offset_spin, self.limit_spin, self.uniq_col, self.uniq_limit,
                  self.uniq_search, self.uniq_list, self.export_btn, self.export_name):
            w.setEnabled(ok)

    # --------------------------------------------------------------- abrir --
    def open_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Selecciona el archivo masivo", "",
            "Datos (*.csv *.txt *.tsv *.parquet *.pq);;Todos (*.*)")
        if path:
            self.load_file(path)

    def _reload_if_open(self, *_):
        if self.path:
            self.load_file(self.path)

    def _date_order(self):
        return self.date_order.currentData()

    def load_file(self, path: str):
        sep_override = self.sep_combo.currentData()
        parse_dates = self.dates_chk.isChecked()
        order = self._date_order()

        def work():
            lf, sep = core.scan_file(path, sep_override, parse_dates, order)
            schema = core.get_schema(lf)
            return path, sep, schema

        def done(result):
            path_, sep, schema = result
            self.path, self.sep, self.schema = path_, sep, schema
            name = os.path.basename(path_)
            self.file_chip.setText(f"{name}   ·   {len(schema)} col")
            self._set_loaded(True)

            self.uniq_col.blockSignals(True)
            self.uniq_col.clear()
            self.minmax_combo.clear()
            for cname, dtype in schema.items():
                label = f"{cname}   ·{core.dtype_label(dtype)}"
                self.uniq_col.addItem(label, cname)
                self.minmax_combo.addItem(label, cname)
            self.uniq_col.setCurrentIndex(-1)
            self.uniq_col.blockSignals(False)
            self.uniq_status.setText("Elige una columna.")

            base = os.path.splitext(name)[0]
            self.export_name.setText(f"{base}_FILTER")

            for r in list(self.filter_rows):
                self._remove_row(r)
            self.add_filter_row()
            self.status.showMessage(
                f"Cargado: {name}  ·  separador '{'tab' if sep == chr(9) else sep}'  "
                f"·  {len(schema)} columnas")

        self.run_async(work, done, "Leyendo esquema...")

    # --------------------------------------------------------------- filas --
    def add_filter_row(self) -> FilterRow:
        row = FilterRow(self)
        row.set_columns(self.schema)
        row.removed.connect(self._remove_row)
        row.value_focused.connect(self._set_active_row)
        self.rows_layout.insertWidget(self.rows_layout.count() - 1, row)
        self.filter_rows.append(row)
        self.active_row = row
        return row

    def _remove_row(self, row: FilterRow):
        if row in self.filter_rows:
            self.filter_rows.remove(row)
        row.setParent(None)
        row.deleteLater()
        if self.active_row is row:
            self.active_row = self.filter_rows[-1] if self.filter_rows else None

    def _set_active_row(self, row: FilterRow):
        self.active_row = row

    # ------------------------------------------------------ filtrado lazy --
    def _current_specs(self) -> list[core.FilterSpec]:
        return [r.to_spec() for r in self.filter_rows]

    def _filtered_lf(self):
        lf, sep = core.scan_file(self.path, self.sep_combo.currentData(),
                                 self.dates_chk.isChecked(), self._date_order())
        lf = core.apply_filters(
            lf, self._current_specs(), self.schema,
            combine=self.combine_combo.currentText(),
            global_negate=self.negate_chk.isChecked())
        return lf, sep

    # ------------------------------------------------------------- acciones --
    def do_preview(self):
        offset = self.offset_spin.value()
        limit = self.limit_spin.value()

        def work():
            lf, _ = self._filtered_lf()
            return core.preview(lf, offset, limit)

        def done(df):
            self.model.set_df(df)
            self.table.resizeColumnsToContents()
            self.preview_info.setText(
                f"Mostrando {df.height:,} filas  (desde {offset:,}, limite {limit:,}).")
            self.status.showMessage("Vista previa lista.")

        self.run_async(work, done, "Filtrando (vista previa)...")

    def do_count(self):
        def work():
            lf, _ = self._filtered_lf()
            return core.count_rows(lf)

        def done(n):
            self.preview_info.setText(f"Filas que cumplen el filtro:  {n:,}")
            self.status.showMessage(f"Conteo: {n:,} filas.")

        self.run_async(work, done, "Contando filas...")

    def do_minmax(self):
        col = self.minmax_combo.currentData()
        if not col:
            return

        def work():
            lf, _ = self._filtered_lf()
            return core.min_max(lf, col)

        def done(res):
            mn, mx = res
            self.preview_info.setText(f'"{col}"   ·   Min: {mn}    Max: {mx}')
            self.status.showMessage(f"{col}:  min={mn}  max={mx}")

        self.run_async(work, done, "Calculando min/max...")

    def do_export(self):
        if not self.path:
            return
        specs_active = [s for s in self._current_specs() if s.is_active()]
        name = self.export_name.text().strip() or "salida"
        out_dir = os.path.dirname(self.path)
        default = os.path.join(out_dir, f"{name}.csv")
        out_path, _ = QFileDialog.getSaveFileName(
            self, "Guardar archivo filtrado", default, "CSV (*.csv)")
        if not out_path:
            return
        sep = self.sep_combo.currentData() or self.sep

        def work():
            lf, real_sep = self._filtered_lf()
            core.export_csv(lf, out_path, sep or real_sep)
            return out_path

        def done(p):
            self.preview_info.setText(
                f"✓ Exportado ({len(specs_active)} filtros):  {p}")
            self.status.showMessage(f"Exportado: {p}")

        self.run_async(work, done, "Exportando (streaming)...")

    # ------------------------------------------------------ valores unicos --
    def compute_unique(self, column, on_done, on_error, limit=None):
        lim = limit if limit is not None else self.uniq_limit.value()

        def work():
            lf, _ = core.scan_file(self.path, self.sep_combo.currentData(),
                                   self.dates_chk.isChecked(), self._date_order())
            return core.unique_values(lf, column, lim)

        self.run_async(work, on_done, "Calculando valores unicos...", on_error)

    def _load_unique_panel(self, *_):
        col = self.uniq_col.currentData()
        if not col:
            return
        self.uniq_list.clear()
        self.uniq_search.clear()
        self.uniq_status.setText("Calculando...")
        self._uniq_all = []
        self._uniq_overflow = False

        def done(result):
            vals, ok = result
            if not ok:
                # Demasiados valores: no listamos, pero permitimos verificar uno.
                self._uniq_overflow = True
                self.uniq_search.setPlaceholderText(
                    "Escribe un valor y pulsa Enter para verificar...")
                self.uniq_status.setText(
                    f"'{col}' supera {self.uniq_limit.value():,} valores unicos.\n"
                    "Escribe un valor y pulsa Enter para comprobar si existe.")
                return
            self._uniq_overflow = False
            self.uniq_search.setPlaceholderText("Buscar...")
            self._uniq_all = [str(v) for v in vals]
            self._filter_unique_list()
            self.uniq_status.setText(f"{len(vals):,} valores unicos.")

        self.compute_unique(col, done, self.error)

    def _filter_unique_list(self, *_):
        # En modo desbordado el filtrado local no aplica: la busqueda se hace
        # contra el archivo con Enter (_search_unique_overflow).
        if getattr(self, "_uniq_overflow", False):
            return
        needle = self.uniq_search.text().lower()
        self.uniq_list.clear()
        for v in getattr(self, "_uniq_all", []):
            if needle in v.lower():
                self.uniq_list.addItem(QListWidgetItem(v))

    def _search_unique_overflow(self):
        """Cuando la columna tiene demasiados valores unicos: busca el termino
        en TODO el archivo y muestra las coincidencias, para verificar que existe."""
        if not getattr(self, "_uniq_overflow", False):
            return
        col = self.uniq_col.currentData()
        query = self.uniq_search.text().strip()
        if not col or not query:
            return
        self.uniq_list.clear()
        self.uniq_status.setText(f"Buscando '{query}' en el archivo...")

        def work():
            lf, _ = core.scan_file(self.path, self.sep_combo.currentData(),
                                   self.dates_chk.isChecked(), self._date_order())
            return core.search_column_values(lf, col, query, 300)

        def done(vals):
            self.uniq_list.clear()
            for v in vals:
                self.uniq_list.addItem(QListWidgetItem(str(v)))
            if vals:
                extra = "  (mostrando las primeras)" if len(vals) >= 300 else ""
                self.uniq_status.setText(
                    f"✓ {len(vals):,} coincidencia(s) con '{query}'.{extra}")
            else:
                self.uniq_status.setText(f"✗ '{query}' no existe en '{col}'.")

        self.run_async(work, done, "Buscando valor...")

    def _unique_to_filter(self, item: QListWidgetItem):
        if self.active_row is None:
            if not self.filter_rows:
                self.add_filter_row()
            self.active_row = self.filter_rows[-1]
        row = self.active_row
        col = self.uniq_col.currentData()
        for i in range(row.column.count()):
            if row.column.itemData(i) == col:
                row.column.setCurrentIndex(i)
                break
        cur = row.value.text().strip()
        row.value.setText(f"{cur}, {item.text()}" if cur else item.text())

    # ------------------------------------------------------------- helpers --
    def run_async(self, fn, on_done, busy_msg="Procesando...", on_error=None):
        self._busy += 1
        self.busy_lbl.setText(busy_msg)
        self.spinner.start()
        worker = Worker(fn)
        # Mantener viva la referencia al worker hasta que termine: si Python lo
        # recolecta antes de que la senal cruce al hilo principal, el resultado
        # nunca llega a la UI.
        self._workers.add(worker)

        def finish():
            self._busy -= 1
            if self._busy <= 0:
                self.busy_lbl.setText("")
                self.spinner.stop()
            self._workers.discard(worker)

        def done(result):
            finish()
            on_done(result)

        def err(msg):
            finish()
            (on_error or self.error)(msg)

        worker.signals.done.connect(done)
        worker.signals.error.connect(err)
        self.pool.start(worker)

    def error(self, msg: str):
        self.status.showMessage(msg)
        QMessageBox.critical(self, "Error", msg)


# Compatibilidad: los controles de export ya viven en la UI. Se conserva por si
# algun script antiguo lo invoca.
def _add_export_controls(win: "MainWindow"):
    return


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
