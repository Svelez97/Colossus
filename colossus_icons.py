"""
colossus_icons.py
-----------------
Iconos dibujados por codigo con QPainter (vectoriales), para no depender de
archivos de imagen (los .png/.ico originales se perdieron).

Cada funcion make_icon(kind, ...) devuelve un QIcon nitido en cualquier tamano.
"""
from __future__ import annotations

from PySide6.QtCore import QRectF, QPointF, Qt
from PySide6.QtGui import (
    QIcon, QPixmap, QPainter, QPen, QColor, QBrush, QPainterPath, QPolygonF,
    QLinearGradient,
)

# Paleta base de la app
ACCENT = "#7A3CE0"      # violeta de marca (degradado del logo)
ACCENT_DK = "#5B2FB0"
INK = "#2B2B33"         # gris tinta para iconos neutros
MUTED = "#6B7280"


def _new_pixmap(size: int) -> QPixmap:
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    return pm


def _painter(pm: QPixmap) -> QPainter:
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing, True)
    p.setRenderHint(QPainter.SmoothPixmapTransform, True)
    return p


def _pen(color: str, w: float, cap=Qt.RoundCap, join=Qt.RoundJoin) -> QPen:
    pen = QPen(QColor(color))
    pen.setWidthF(w)
    pen.setCapStyle(cap)
    pen.setJoinStyle(join)
    return pen


def _draw(kind: str, p: QPainter, s: float, color: str, accent: str) -> None:
    """Dibuja el icono 'kind' en un lienzo s x s."""
    lw = max(1.6, s * 0.085)          # grosor de linea proporcional
    p.setPen(_pen(color, lw))
    p.setBrush(Qt.NoBrush)
    m = s * 0.16                       # margen

    if kind == "folder":
        # Carpeta abierta
        p.setBrush(QBrush(QColor(accent)))
        p.setPen(_pen(ACCENT_DK, lw))
        path = QPainterPath()
        path.moveTo(m, s * 0.34)
        path.lineTo(s * 0.42, s * 0.34)
        path.lineTo(s * 0.50, s * 0.25)
        path.lineTo(s - m, s * 0.25)
        path.lineTo(s - m, s * 0.72)
        path.lineTo(m, s * 0.72)
        path.closeSubpath()
        p.drawPath(path)

    elif kind == "funnel":
        # Embudo (filtro)
        p.setBrush(QBrush(QColor(accent)))
        p.setPen(_pen(ACCENT_DK, lw))
        poly = QPolygonF([
            QPointF(m, m * 1.2),
            QPointF(s - m, m * 1.2),
            QPointF(s * 0.60, s * 0.52),
            QPointF(s * 0.60, s - m),
            QPointF(s * 0.40, s * 0.82),
            QPointF(s * 0.40, s * 0.52),
        ])
        p.drawPolygon(poly)

    elif kind == "export":
        # Bandeja con flecha hacia abajo (guardar/exportar)
        p.setPen(_pen(color, lw))
        # flecha
        cx = s * 0.5
        p.drawLine(QPointF(cx, m), QPointF(cx, s * 0.58))
        p.drawLine(QPointF(cx, s * 0.58), QPointF(cx - s * 0.14, s * 0.42))
        p.drawLine(QPointF(cx, s * 0.58), QPointF(cx + s * 0.14, s * 0.42))
        # bandeja
        p.drawLine(QPointF(m, s * 0.70), QPointF(m, s - m))
        p.drawLine(QPointF(s - m, s * 0.70), QPointF(s - m, s - m))
        p.drawLine(QPointF(m, s - m), QPointF(s - m, s - m))

    elif kind == "eye":
        # Ojo (preview)
        path = QPainterPath()
        path.moveTo(m, s * 0.5)
        path.quadTo(s * 0.5, m, s - m, s * 0.5)
        path.quadTo(s * 0.5, s - m, m, s * 0.5)
        p.drawPath(path)
        p.setBrush(QBrush(QColor(accent)))
        p.setPen(_pen(ACCENT_DK, lw * 0.8))
        r = s * 0.13
        p.drawEllipse(QPointF(s * 0.5, s * 0.5), r, r)

    elif kind == "search":
        # Lupa
        r = s * 0.26
        c = QPointF(s * 0.42, s * 0.42)
        p.drawEllipse(c, r, r)
        p.drawLine(QPointF(c.x() + r * 0.72, c.y() + r * 0.72),
                   QPointF(s - m * 0.7, s - m * 0.7))

    elif kind == "count":
        # Filas / lista con numeros
        y = s * 0.30
        for _ in range(3):
            p.drawLine(QPointF(m, y), QPointF(m + s * 0.10, y))
            p.drawLine(QPointF(s * 0.42, y), QPointF(s - m, y))
            y += s * 0.20

    elif kind == "stats":
        # Barras (min/max)
        p.setBrush(QBrush(QColor(accent)))
        p.setPen(_pen(ACCENT_DK, lw * 0.7))
        bw = s * 0.16
        base = s - m
        for i, h in enumerate((0.30, 0.55, 0.42)):
            x = m + i * (bw + s * 0.06)
            p.drawRoundedRect(QRectF(x, base - s * h, bw, s * h), 2, 2)

    elif kind == "plus":
        p.drawLine(QPointF(s * 0.5, m), QPointF(s * 0.5, s - m))
        p.drawLine(QPointF(m, s * 0.5), QPointF(s - m, s * 0.5))

    elif kind == "trash":
        # Papelera (quitar)
        p.drawLine(QPointF(m, s * 0.28), QPointF(s - m, s * 0.28))
        p.drawLine(QPointF(s * 0.38, s * 0.28), QPointF(s * 0.42, s * 0.18))
        p.drawLine(QPointF(s * 0.42, s * 0.18), QPointF(s * 0.58, s * 0.18))
        p.drawLine(QPointF(s * 0.58, s * 0.18), QPointF(s * 0.62, s * 0.28))
        path = QPainterPath()
        path.moveTo(s * 0.28, s * 0.32)
        path.lineTo(s * 0.34, s - m)
        path.lineTo(s * 0.66, s - m)
        path.lineTo(s * 0.72, s * 0.32)
        p.drawPath(path)

    elif kind == "not":
        # Simbolo de negacion (circulo con barra)
        p.setPen(_pen(accent, lw))
        r = s * 0.32
        c = QPointF(s * 0.5, s * 0.5)
        p.drawEllipse(c, r, r)
        d = r * 0.72
        p.drawLine(QPointF(c.x() - d, c.y() + d), QPointF(c.x() + d, c.y() - d))

    elif kind == "logo":
        # Logo: embudo dentro de circulo con degradado esmeralda -> violeta.
        grad = QLinearGradient(s * 0.15, s * 0.15, s * 0.85, s * 0.85)
        grad.setColorAt(0.0, QColor("#15C9A6"))
        grad.setColorAt(0.5, QColor("#3B7FDB"))
        grad.setColorAt(1.0, QColor("#7A3CE0"))
        p.setBrush(QBrush(grad))
        p.setPen(_pen(ACCENT_DK, lw))
        c = QPointF(s * 0.5, s * 0.5)
        p.drawEllipse(c, s * 0.40, s * 0.40)
        p.setBrush(QBrush(QColor("#FFFFFF")))
        p.setPen(_pen("#FFFFFF", lw * 0.4))
        poly = QPolygonF([
            QPointF(s * 0.30, s * 0.32),
            QPointF(s * 0.70, s * 0.32),
            QPointF(s * 0.56, s * 0.52),
            QPointF(s * 0.56, s * 0.70),
            QPointF(s * 0.44, s * 0.62),
            QPointF(s * 0.44, s * 0.52),
        ])
        p.drawPolygon(poly)

    else:
        # fallback: circulo
        p.drawEllipse(QRectF(m, m, s - 2 * m, s - 2 * m))


def make_icon(kind: str, size: int = 40, color: str = INK, accent: str = ACCENT) -> QIcon:
    pm = _new_pixmap(size)
    p = _painter(pm)
    _draw(kind, p, float(size), color, accent)
    p.end()
    return QIcon(pm)


def make_pixmap(kind: str, size: int = 40, color: str = INK, accent: str = ACCENT) -> QPixmap:
    pm = _new_pixmap(size)
    p = _painter(pm)
    _draw(kind, p, float(size), color, accent)
    p.end()
    return pm
