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
import tempfile
import traceback
import uuid

import polars as pl
from PySide6.QtCore import (
    Qt, QAbstractTableModel, QModelIndex, QObject, QRunnable, QThreadPool,
    Signal, Slot, QTimer, QSize, QRectF,
)
from PySide6.QtGui import (
    QColor, QPalette, QPainter, QPen, QFont, QBrush, QLinearGradient,
    QPainterPath, QFontMetrics, QPolygonF, QPixmap, QIcon,
)
from PySide6.QtCore import QPointF
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QLabel, QLineEdit, QComboBox, QCheckBox,
    QPushButton, QToolButton, QHBoxLayout, QVBoxLayout, QSplitter, QScrollArea,
    QFrame, QListWidget, QListWidgetItem, QTableView, QSpinBox, QFileDialog,
    QMessageBox, QHeaderView, QMenu, QGraphicsDropShadowEffect, QSizePolicy,
    QDialog, QDialogButtonBox, QFormLayout,
)

import colossus_core as core
from colossus_icons import make_icon, make_pixmap

# Assets de marca (junto a este archivo).
_HERE = os.path.dirname(os.path.abspath(__file__))
LOGO_MARK = os.path.join(_HERE, "logo_mark.png")   # monograma "C" recortado


# --------------------------------------------------------------------------- #
# Paletas de color (sistema de diseno)
# --------------------------------------------------------------------------- #
# Degradado de marca del logo: esmeralda -> azul -> violeta -> fucsia.
# Se usa para botones primarios, la barra superior y los graficos.
_GRAD = ("qlineargradient(x1:0, y1:0, x2:1, y2:0, "
         "stop:0 #15C9A6, stop:0.5 #3B7FDB, stop:1 #7A3CE0)")
_GRAD_HOVER = ("qlineargradient(x1:0, y1:0, x2:1, y2:0, "
               "stop:0 #19D9B4, stop:0.5 #4B8FEB, stop:1 #8A4CF0)")
_APPBAR_LIGHT = ("qlineargradient(x1:0, y1:0, x2:1, y2:0, "
                 "stop:0 #0E1030, stop:0.55 #241C5A, stop:1 #3A1C6E)")
_APPBAR_DARK = ("qlineargradient(x1:0, y1:0, x2:1, y2:0, "
                "stop:0 #080A1C, stop:0.55 #17123A, stop:1 #241148)")

# Paradas del degradado del logo como colores solidos, para pintar los graficos.
BRAND_STOPS = ["#15C9A6", "#3B7FDB", "#7A3CE0", "#B02FD6"]

PALETTES = {
    "light": {
        "bg": "#EEF0F7", "appbar": _APPBAR_LIGHT, "appbar_text": "#F4F6FB",
        "appbar_sub": "#AEB2E0", "surface": "#FFFFFF", "surface_alt": "#F5F5FB",
        "border": "#E4E2F0", "text": "#232838", "subtext": "#6B7280",
        "accent": "#7A3CE0", "accent_hover": "#6A2FD0", "accent_soft": "#EBE3FB",
        "accent_grad": _GRAD, "accent_grad_hover": _GRAD_HOVER,
        "table_header": "#F3F1FB", "selection": "#EBE3FB", "grid": "#ECEAF6",
        "field": "#FFFFFF", "shadow": 45,
    },
    "dark": {
        "bg": "#0C0E24", "appbar": _APPBAR_DARK, "appbar_text": "#EAECF3",
        "appbar_sub": "#9A9FD6", "surface": "#14163A", "surface_alt": "#1C1F48",
        "border": "#2A2E5C", "text": "#E4E7F0", "subtext": "#9AA0B2",
        "accent": "#8B5CF6", "accent_hover": "#9B6CFF", "accent_soft": "#2C2856",
        "accent_grad": _GRAD, "accent_grad_hover": _GRAD_HOVER,
        "table_header": "#1C1F48", "selection": "#2C2856", "grid": "#232752",
        "field": "#0F1130", "shadow": 120,
    },
}
NEUTRAL_ICON = "#8A90A2"   # gris que se ve bien en claro y oscuro

# Paleta activa (para que los graficos lean los colores del tema actual).
ACTIVE_PALETTE = PALETTES["light"]

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
QPushButton[primary="true"] {{ background: {p['accent_grad']}; color: #FFFFFF;
    border: 1px solid {p['accent']}; }}
QPushButton[primary="true"]:hover {{ background: {p['accent_grad_hover']};
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
# Dialogo de opciones de Excel:  hoja / fila de encabezado / columnas
# --------------------------------------------------------------------------- #
class ExcelOptionsDialog(QDialog):
    """Permite definir DESDE DONDE esta la data en una hoja de calculo, con una
    vista previa en vivo de las primeras filas. Si el archivo no se puede leer con
    las opciones actuales, muestra el error pero NO cierra la ventana."""

    def __init__(self, path: str, parent=None):
        super().__init__(parent)
        self.path = path
        self.setWindowTitle("Opciones de Excel")
        self.setModal(True)
        self.resize(760, 560)

        # Refresco de la vista previa con un pequeno retardo (asi escribir en el
        # campo de columnas actualiza en vivo sin releer en cada tecla).
        self._deb = QTimer(self)
        self._deb.setSingleShot(True)
        self._deb.setInterval(250)
        self._deb.timeout.connect(self.refresh)

        try:
            sheets = core.excel_sheet_names(path)
        except Exception:
            sheets = []

        form = QFormLayout()
        form.setSpacing(10)

        self.sheet_combo = QComboBox()
        for s in sheets:
            self.sheet_combo.addItem(s, s)
        self.sheet_combo.currentIndexChanged.connect(self._schedule)
        form.addRow("Hoja", self.sheet_combo)

        self.detect_btn = QPushButton("  Identificar automáticamente la tabla")
        self.detect_btn.setIcon(make_icon("search", 20, color=NEUTRAL_ICON))
        self.detect_btn.setToolTip(
            "Busca sola la fila de encabezado y el rango de columnas con datos.")
        self.detect_btn.clicked.connect(self._auto_detect)
        form.addRow("", self.detect_btn)

        self.header_chk = QCheckBox("La primera fila es el encabezado")
        self.header_chk.setChecked(True)
        self.header_chk.stateChanged.connect(self._toggle_header)
        self.header_chk.stateChanged.connect(self._schedule)
        form.addRow("", self.header_chk)

        self.header_spin = QSpinBox()
        self.header_spin.setRange(1, 1_048_576)
        self.header_spin.setValue(1)
        self.header_spin.setToolTip("Numero de fila (en Excel) que contiene los titulos.")
        self.header_spin.valueChanged.connect(self._schedule)
        form.addRow("Fila del encabezado", self.header_spin)

        self.skip_spin = QSpinBox()
        self.skip_spin.setRange(0, 1_000_000)
        self.skip_spin.setValue(0)
        self.skip_spin.setToolTip("Filas de datos a descartar justo despues del encabezado.")
        self.skip_spin.valueChanged.connect(self._schedule)
        form.addRow("Saltar filas de datos", self.skip_spin)

        self.cols_edit = QLineEdit()
        self.cols_edit.setPlaceholderText("Todas   ·   ej.  A:F   o   A,C,E")
        self.cols_edit.setToolTip("Rango o lista de columnas de Excel. Vacio = todas.")
        self.cols_edit.textChanged.connect(self._schedule)   # en vivo
        form.addRow("Columnas", self.cols_edit)

        self.hint = QLabel("")
        self.hint.setObjectName("SectionHint")
        self.hint.setWordWrap(True)

        self.preview = QTableView()
        self.preview.setModel(PolarsTableModel())
        self.preview.horizontalHeader().setStretchLastSection(True)
        self.preview.setAlternatingRowColors(True)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Cargar")
        buttons.button(QDialogButtonBox.Cancel).setText("Cancelar")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 12)
        lay.setSpacing(10)
        lay.addLayout(form)
        lay.addWidget(QLabel("Vista previa (primeras filas)"))
        lay.addWidget(self.preview, 1)
        lay.addWidget(self.hint)
        lay.addWidget(buttons)

        self._ok = False        # ultima lectura fue valida?
        self.refresh()

    # --------------------------------------------------------------- helpers --
    def _schedule(self, *_):
        self._deb.start()

    def _toggle_header(self):
        self.header_spin.setEnabled(self.header_chk.isChecked())

    def get_opts(self) -> dict:
        return {
            "sheet": self.sheet_combo.currentData(),
            "has_header": self.header_chk.isChecked(),
            "header_row": self.header_spin.value() - 1,   # 1-based -> 0-based
            "skip_rows": self.skip_spin.value(),
            "use_columns": self.cols_edit.text().strip(),
        }

    def _auto_detect(self):
        sheet = self.sheet_combo.currentData()
        try:
            det = core.detect_excel_table(self.path, sheet)
        except Exception:
            det = None
        if not det:
            QMessageBox.information(
                self, "Identificar tabla",
                "No se encontró una tabla clara en esta hoja.\n"
                "Ajusta la fila y las columnas manualmente.")
            return
        # Aplica lo detectado (bloquea señales para no disparar lecturas de mas).
        for w in (self.header_chk, self.header_spin, self.skip_spin, self.cols_edit):
            w.blockSignals(True)
        self.header_chk.setChecked(True)
        self.header_spin.setEnabled(True)
        self.header_spin.setValue(det["header_row_1based"])
        self.skip_spin.setValue(0)
        self.cols_edit.setText(det["use_columns"])
        for w in (self.header_chk, self.header_spin, self.skip_spin, self.cols_edit):
            w.blockSignals(False)
        self.refresh()
        self.hint.setText(
            f"Detectado: encabezado en la fila {det['header_row_1based']}, "
            f"columnas {det['use_columns']}.")

    def refresh(self, *_):
        # Vista previa acotada (rapida) con las opciones actuales.
        opts = dict(self.get_opts(), n_rows=200)
        try:
            lf, _ = core.scan_file(self.path, excel_opts=opts)
            df = core.preview(lf, 0, 20)
            self.preview.model().set_df(df)
            self.hint.setText(f"{df.width} columnas · vista previa de {df.height} filas.")
            self._ok = True
        except Exception as exc:
            self.preview.model().set_df(pl.DataFrame())
            self.hint.setText(f"⚠  No se pudo leer con estas opciones: {exc}")
            self._ok = False

    def accept(self):
        """Solo cierra (y carga) si el archivo SI se puede leer. Si no, avisa y
        mantiene la ventana abierta para corregir."""
        opts = self.get_opts()
        try:
            lf, _ = core.scan_file(self.path, excel_opts=opts)
            core.get_schema(lf)          # fuerza a resolver el esquema real
        except Exception as exc:
            QMessageBox.warning(
                self, "No se pudo cargar el archivo",
                "No se pudo leer la hoja con estas opciones:\n\n"
                f"{exc}\n\n"
                "Corrige la fila de encabezado o el rango de columnas, "
                "usa «Identificar automáticamente», o presiona Cancelar.")
            return                       # <-- NO cierra la ventana
        super().accept()


# --------------------------------------------------------------------------- #
# Dialogo selector de tabla para bases SQLite
# --------------------------------------------------------------------------- #
class SqliteTableDialog(QDialog):
    """Elige QUE TABLA de la base SQLite abrir, con vista previa. Si la tabla no
    se puede leer, avisa y NO cierra la ventana."""

    def __init__(self, path: str, parent=None):
        super().__init__(parent)
        self.path = path
        self.setWindowTitle("Elegir tabla de la base")
        self.setModal(True)
        self.resize(720, 520)

        try:
            tables = core.sqlite_table_names(path)
        except Exception:
            tables = []

        form = QFormLayout()
        form.setSpacing(10)
        self.table_combo = QComboBox()
        for t in tables:
            self.table_combo.addItem(t, t)
        self.table_combo.currentIndexChanged.connect(self.refresh)
        form.addRow("Tabla", self.table_combo)

        self.hint = QLabel("")
        self.hint.setObjectName("SectionHint")
        self.hint.setWordWrap(True)

        self.preview = QTableView()
        self.preview.setModel(PolarsTableModel())
        self.preview.horizontalHeader().setStretchLastSection(True)
        self.preview.setAlternatingRowColors(True)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Cargar")
        buttons.button(QDialogButtonBox.Cancel).setText("Cancelar")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 12)
        lay.setSpacing(10)
        lay.addLayout(form)
        lay.addWidget(QLabel("Vista previa (primeras filas)"))
        lay.addWidget(self.preview, 1)
        lay.addWidget(self.hint)
        lay.addWidget(buttons)

        if not tables:
            self.hint.setText("⚠  La base no tiene tablas legibles.")
        self.refresh()

    def get_table(self):
        return self.table_combo.currentData()

    def refresh(self, *_):
        table = self.get_table()
        if not table:
            return
        try:
            df = core.read_sqlite(self.path, table, limit=50)
            self.preview.model().set_df(df)
            self.hint.setText(f"{df.width} columnas · vista previa de {df.height} filas.")
        except Exception as exc:
            self.preview.model().set_df(pl.DataFrame())
            self.hint.setText(f"⚠  No se pudo leer la tabla: {exc}")

    def accept(self):
        table = self.get_table()
        try:
            lf, _ = core.scan_file(self.path, table=table)
            core.get_schema(lf)
        except Exception as exc:
            QMessageBox.warning(
                self, "No se pudo cargar la tabla",
                f"No se pudo leer la tabla seleccionada:\n\n{exc}\n\n"
                "Elige otra tabla o presiona Cancelar.")
            return
        super().accept()


# --------------------------------------------------------------------------- #
# Grafico de distribucion (barras + curva tipo campana), dibujado a mano
# --------------------------------------------------------------------------- #
class DistChart(QWidget):
    """Dibuja la distribucion de una columna como un grafico de barras. Para
    columnas numericas superpone una curva suave (forma de campana de Gauss).
    Los colores siguen el degradado del logo (esmeralda -> violeta -> fucsia)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._data: dict | None = None
        self.setMinimumHeight(320)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def set_data(self, data: dict | None):
        self._data = data
        self.update()

    @staticmethod
    def _brand_color(t: float) -> QColor:
        """Interpola un color a lo largo del degradado del logo (t en 0..1)."""
        stops = [QColor(c) for c in BRAND_STOPS]
        if t <= 0:
            return stops[0]
        if t >= 1:
            return stops[-1]
        seg = t * (len(stops) - 1)
        i = int(seg)
        f = seg - i
        a, b = stops[i], stops[i + 1]
        return QColor(int(a.red() + (b.red() - a.red()) * f),
                      int(a.green() + (b.green() - a.green()) * f),
                      int(a.blue() + (b.blue() - a.blue()) * f))

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        pal = ACTIVE_PALETTE
        rect = self.rect()
        p.fillRect(rect, QColor(pal["surface"]))

        data = self._data
        if not data or not data.get("counts"):
            p.setPen(QColor(pal["subtext"]))
            p.drawText(rect, Qt.AlignCenter, "Sin datos para graficar.")
            p.end()
            return

        counts = data["counts"]
        labels = data["labels"]
        numeric = data["numeric"]
        n = len(counts)
        maxc = max(counts) or 1

        ml, mr, mt, mb = 62, 18, 18, 70
        W = rect.width() - ml - mr
        H = rect.height() - mt - mb
        if W <= 10 or H <= 10:
            p.end()
            return
        x0, y0 = ml, mt + H

        grid = QColor(pal["grid"])
        axis = QColor(pal["subtext"])
        sub = QColor(pal["subtext"])

        # --- rejilla + eje Y ---
        p.setFont(QFont("Segoe UI", 8))
        steps = 4
        for i in range(steps + 1):
            frac = i / steps
            y = y0 - H * frac
            p.setPen(QPen(grid, 1))
            p.drawLine(int(x0), int(y), int(x0 + W), int(y))
            p.setPen(axis)
            p.drawText(QRectF(0, y - 8, ml - 8, 16),
                       Qt.AlignRight | Qt.AlignVCenter, f"{int(round(maxc * frac)):,}")

        # --- barras ---
        gap = 0.06 if numeric else 0.2
        slot = W / n
        bw = slot * (1 - gap)
        centers = []
        for i, c in enumerate(counts):
            t = i / (n - 1) if n > 1 else 0.5
            col = self._brand_color(t)
            bx = x0 + slot * i + (slot - bw) / 2
            bh = H * (c / maxc)
            by = y0 - bh
            centers.append((bx + bw / 2, by))
            g = QLinearGradient(0, by, 0, y0)
            c_top = QColor(col)
            c_bot = QColor(col)
            c_bot.setAlpha(150)
            g.setColorAt(0, c_top)
            g.setColorAt(1, c_bot)
            p.fillRect(QRectF(bx, by, bw, max(1.0, bh)), QBrush(g))

        # --- curva suave tipo campana (solo numerica) ---
        if numeric and n > 2:
            pts = [QPointF(cx, cy) for cx, cy in centers]
            path = QPainterPath(pts[0])
            for i in range(len(pts) - 1):
                a, b = pts[i], pts[i + 1]
                mx = (a.x() + b.x()) / 2
                path.cubicTo(mx, a.y(), mx, b.y(), b.x(), b.y())
            pen = QPen(QColor(pal["accent"]), 2.2)
            pen.setCapStyle(Qt.RoundCap)
            pen.setJoinStyle(Qt.RoundJoin)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            p.drawPath(path)
            for pt in pts:
                p.setBrush(QColor(pal["surface"]))
                p.setPen(QPen(QColor(pal["accent"]), 1.6))
                p.drawEllipse(pt, 2.4, 2.4)

        # --- eje X + etiquetas ---
        p.setPen(QPen(axis, 1.4))
        p.drawLine(int(x0), int(y0), int(x0 + W), int(y0))
        p.setFont(QFont("Segoe UI", 8))
        if numeric and data.get("edges"):
            edges = data["edges"]
            ne = len(edges)
            ticks = min(6, ne)
            for k in range(ticks):
                idx = round(k * (ne - 1) / (ticks - 1)) if ticks > 1 else 0
                x = x0 + W * (idx / (ne - 1))
                p.setPen(sub)
                p.drawText(QRectF(x - 42, y0 + 6, 84, 14),
                           Qt.AlignHCenter | Qt.AlignTop, f"{edges[idx]:.3g}")
        else:
            rotate = slot < 74
            for i, lab in enumerate(labels):
                cx = x0 + slot * i + slot / 2
                short = lab if len(lab) <= 16 else lab[:14] + "…"
                p.setPen(sub)
                if rotate:
                    p.save()
                    p.translate(cx, y0 + 8)
                    p.rotate(35)
                    p.drawText(0, 0, short)
                    p.restore()
                else:
                    p.drawText(QRectF(cx - slot / 2, y0 + 6, slot, 16),
                               Qt.AlignHCenter | Qt.AlignTop, short)
        p.end()


# --------------------------------------------------------------------------- #
# Dialogo de resumen estadistico + distribucion (todo sobre el dataset filtrado)
# --------------------------------------------------------------------------- #
class StatsDialog(QDialog):
    """Resumen estadistico (solo columnas numericas) y distribucion de cualquier
    columna, calculados de forma LAZY sobre TODO el resultado filtrado. La
    distribucion se muestra como un grafico (barras + curva tipo campana)."""

    def __init__(self, lf, schema: dict, window: "MainWindow"):
        super().__init__(window)
        self.lf = lf
        self.schema = schema
        self.window = window
        self.setWindowTitle("Resumen estadístico")
        self.setModal(True)
        self.resize(980, 740)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 12)
        root.setSpacing(10)

        self.head = QLabel("Resumen del resultado filtrado (dataset completo)")
        self.head.setObjectName("SectionTitle")
        root.addWidget(self.head)

        split = QSplitter(Qt.Vertical)
        split.setHandleWidth(10)
        split.setChildrenCollapsible(False)

        # --- Resumen (solo numericas) ---
        top = QWidget()
        tl = QVBoxLayout(top)
        tl.setContentsMargins(0, 0, 0, 0)
        tl.setSpacing(6)
        tl.addWidget(QLabel("Estadísticas de columnas numéricas "
                            "(count · media · std · min · cuartiles · max)"))
        self.desc_table = QTableView()
        self.desc_table.setAlternatingRowColors(True)
        self.desc_table.setModel(PolarsTableModel(
            pl.DataFrame({"estadística": ["Calculando…"]})))
        tl.addWidget(self.desc_table, 1)
        split.addWidget(top)

        # --- Distribucion (grafico) ---
        bot = QWidget()
        bl = QVBoxLayout(bot)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setSpacing(6)
        picker = QHBoxLayout()
        picker.addWidget(QLabel("Distribución de:"))
        self.dist_combo = QComboBox()
        for cname, dtype in schema.items():
            self.dist_combo.addItem(f"{cname}   ·{core.dtype_label(dtype)}", cname)
        picker.addWidget(self.dist_combo, 1)
        self.dist_btn = primary(QPushButton("  Ver distribución"))
        self.dist_btn.setIcon(make_icon("stats", 20, color="#FFFFFF"))
        self.dist_btn.clicked.connect(self._show_distribution)
        picker.addWidget(self.dist_btn)
        bl.addLayout(picker)

        self.chart = DistChart()
        bl.addWidget(self.chart, 1)
        self.dist_hint = QLabel("")
        self.dist_hint.setObjectName("SectionHint")
        self.dist_hint.setWordWrap(True)
        bl.addWidget(self.dist_hint)
        split.addWidget(bot)

        split.setSizes([230, 430])
        root.addWidget(split, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.button(QDialogButtonBox.Close).setText("Cerrar")
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        root.addWidget(buttons)

        self._load_describe()
        if self.dist_combo.count():
            self._show_distribution()

    def _load_describe(self):
        def work():
            return core.describe_numeric(self.lf)

        def done(df):
            self.desc_table.setModel(PolarsTableModel(df))
            self.desc_table.resizeColumnsToContents()

        def err(msg):
            self.desc_table.setModel(PolarsTableModel(
                pl.DataFrame({"error": [f"No se pudo calcular: {msg}"]})))

        self.window.run_async(work, done, "Calculando resumen…", err)

    def _show_distribution(self):
        col = self.dist_combo.currentData()
        if not col:
            return
        self.dist_btn.setEnabled(False)
        self.dist_hint.setText("Calculando distribución…")

        def work():
            return core.distribution_data(self.lf, col)

        def done(data):
            self.dist_btn.setEnabled(True)
            self.chart.set_data(data)
            kind = "histograma (rangos)" if data["numeric"] else "conteo por valor"
            extra = "  ·  +categorías no mostradas" if data.get("truncated") else ""
            nulls = data.get("nulls", 0)
            nul = f"  ·  {nulls:,} nulos" if nulls else ""
            self.head.setText(
                f"Resultado filtrado · {data['total']:,} filas (dataset completo)")
            self.dist_hint.setText(
                f"«{col}» · {kind} · {len(data['counts'])} barras{nul}{extra}")

        def err(msg):
            self.dist_btn.setEnabled(True)
            self.chart.set_data(None)
            self.dist_hint.setText(f"⚠  No se pudo calcular la distribución: {msg}")

        self.window.run_async(work, done, "Calculando distribución…", err)


# --------------------------------------------------------------------------- #
# Ventana principal
# --------------------------------------------------------------------------- #
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Colossus")
        _mark = QPixmap(LOGO_MARK)
        self.setWindowIcon(QIcon(_mark) if not _mark.isNull()
                           else make_icon("logo", 64))
        self.resize(1380, 840)
        self.setMinimumSize(1060, 620)

        self.pool = QThreadPool.globalInstance()
        self.path: str | None = None
        self.parquet_path: str | None = None   # cache Parquet del archivo abierto
        self.sep: str = ","
        self.excel_opts: dict | None = None
        self.sqlite_table: str | None = None
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
        mark = QPixmap(LOGO_MARK)
        if not mark.isNull():
            logo.setPixmap(mark.scaledToHeight(
                42, Qt.SmoothTransformation))
        else:                                   # respaldo: logo dibujado
            logo.setPixmap(make_pixmap("logo", 40))
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
        self.export_name.setFixedWidth(160)
        bar.addWidget(self.export_name)

        bar.addWidget(QLabel("Sep."))
        self.export_sep = QComboBox()
        self.export_sep.addItem(",  (coma)", ",")
        self.export_sep.addItem(";  (punto y coma)", ";")
        self.export_sep.addItem("|  (barra)", "|")
        self.export_sep.addItem("tab", "\t")
        self.export_sep.setToolTip(
            "Separador del CSV de salida. Usa ';' si tu Excel abre con ese "
            "separador; ',' es el estandar universal.")
        bar.addWidget(self.export_sep)

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

        self.stats_btn = QPushButton("  Resumen")
        self.stats_btn.setIcon(make_icon("stats", 20, color=NEUTRAL_ICON))
        self.stats_btn.setToolTip("Resumen estadistico (count, media, std, min, "
                                  "cuartiles, max) y distribucion por columna.")
        self.stats_btn.clicked.connect(self.do_stats)
        bar.addWidget(self.stats_btn)
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
        global ACTIVE_PALETTE
        self._theme = name
        p = PALETTES[name]
        ACTIVE_PALETTE = p
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
                  self.stats_btn, self.minmax_combo, self.combine_combo, self.negate_chk,
                  self.offset_spin, self.limit_spin, self.uniq_col, self.uniq_limit,
                  self.uniq_search, self.uniq_list, self.export_btn, self.export_name,
                  self.export_sep):
            w.setEnabled(ok)

    # --------------------------------------------------------------- abrir --
    def open_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Selecciona el archivo masivo", "",
            "Datos (*.csv *.txt *.tsv *.csv.gz *.parquet *.pq *.arrow *.feather *.ipc "
            "*.ndjson *.jsonl *.json *.xlsx *.xlsm *.xls *.xlsb *.ods "
            "*.db *.sqlite *.sqlite3 *.db3);;"
            "Texto delimitado (*.csv *.txt *.tsv *.csv.gz);;"
            "Parquet (*.parquet *.pq);;"
            "Arrow / Feather (*.arrow *.feather *.ipc);;"
            "JSON (*.ndjson *.jsonl *.json);;"
            "Excel / hojas de calculo (*.xlsx *.xlsm *.xls *.xlsb *.ods);;"
            "SQLite (*.db *.sqlite *.sqlite3 *.db3);;"
            "Todos (*.*)")
        if not path:
            return
        # Reinicia opciones especificas de formato.
        self.excel_opts = None
        self.sqlite_table = None
        # Para Excel, preguntamos DONDE esta la data (hoja/fila/columnas).
        if core.is_excel(path):
            dlg = ExcelOptionsDialog(path, self)
            if dlg.exec() != QDialog.Accepted:
                return
            self.excel_opts = dlg.get_opts()
        # Para SQLite, preguntamos QUE TABLA abrir.
        elif core.is_sqlite(path):
            dlg = SqliteTableDialog(path, self)
            if dlg.exec() != QDialog.Accepted:
                return
            self.sqlite_table = dlg.get_table()
        self.load_file(path)

    def _reload_if_open(self, *_):
        if self.path:
            self.load_file(self.path)

    def _date_order(self):
        return self.date_order.currentData()

    def _scan(self):
        """LazyFrame de las operaciones: SIEMPRE lee del Parquet de cache (rapido).
        El archivo original ya fue convertido una vez al abrirlo."""
        return core.scan_parquet_cache(self.parquet_path), self.sep

    @staticmethod
    def _new_cache_path() -> str:
        return os.path.join(tempfile.gettempdir(),
                            f"colossus_{uuid.uuid4().hex}.parquet")

    def _clear_cache(self):
        """Borra el Parquet temporal del archivo anterior (si lo hay)."""
        if self.parquet_path and os.path.exists(self.parquet_path):
            try:
                os.remove(self.parquet_path)
            except OSError:
                pass
        self.parquet_path = None

    def closeEvent(self, event):
        self._clear_cache()
        super().closeEvent(event)

    def load_file(self, path: str):
        # Convierte el archivo (de cualquier formato) a un Parquet temporal una
        # sola vez; a partir de ahi todo se lee de ese Parquet ultrarrapido.
        def work():
            pq = self._new_cache_path()
            _, sep = core.materialize_parquet(
                path, pq, self.sep_combo.currentData(),
                self.dates_chk.isChecked(), self._date_order(),
                excel_opts=self.excel_opts, table=self.sqlite_table)
            schema = core.get_schema(core.scan_parquet_cache(pq))
            return path, pq, sep, schema

        def done(result):
            path_, pq, sep, schema = result
            self._clear_cache()                 # borra el cache anterior
            self.path, self.parquet_path, self.sep, self.schema = \
                path_, pq, sep, schema
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
                f"Cargado: {name}  ·  {len(schema)} columnas  ·  "
                f"en cache Parquet (lectura ultrarrapida)")
            # Muestra la vista previa automaticamente al terminar de cargar.
            self.do_preview()

        self.run_async(work, done, "Convirtiendo a Parquet (una sola vez)...")

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
        lf, sep = self._scan()
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

    def do_stats(self):
        """Abre el resumen estadistico. El calculo (describe + distribucion) se
        hace de forma LAZY sobre TODO el resultado filtrado, dentro del dialogo."""
        try:
            lf, _ = self._filtered_lf()
        except Exception as exc:  # noqa: BLE001
            self.error(f"{type(exc).__name__}: {exc}")
            return
        StatsDialog(lf, dict(self.schema), self).exec()

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
        # La exportacion es SIEMPRE CSV, con el separador que elija el usuario
        # (para poder abrir/manipular comodo en Excel).
        sep = self.export_sep.currentData() or ","

        def work():
            lf, _ = self._filtered_lf()
            core.export_csv(lf, out_path, sep)
            return out_path

        def done(p):
            sep_name = "tab" if sep == "\t" else sep
            self.preview_info.setText(
                f"✓ Exportado CSV ({len(specs_active)} filtros · sep '{sep_name}'):  {p}")
            self.status.showMessage(f"Exportado: {p}")

        self.run_async(work, done, "Exportando (streaming)...")

    # ------------------------------------------------------ valores unicos --
    def compute_unique(self, column, on_done, on_error, limit=None):
        lim = limit if limit is not None else self.uniq_limit.value()

        def work():
            lf, _ = self._scan()
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
            lf, _ = self._scan()
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
