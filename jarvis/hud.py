"""Interface HUD: reator animado, painéis de sistema, legendas e entrada de texto."""
from __future__ import annotations

import ctypes
import math
import time
from collections import deque
from datetime import datetime

import psutil
from PyQt6.QtCore import QPointF, QRectF, Qt, QTimer
from PyQt6.QtGui import (
    QBrush,
    QColor,
    QConicalGradient,
    QFont,
    QKeySequence,
    QPainter,
    QPainterPath,
    QPen,
    QRadialGradient,
    QShortcut,
)
from PyQt6.QtWidgets import QInputDialog, QLineEdit, QMessageBox, QWidget

from .assistant import Assistant
from .config import Config

STATES = {
    "inicializando": ("INICIALIZANDO", QColor(0, 150, 255), 0.6),
    "pronto": ("ONLINE", QColor(0, 200, 255), 1.0),
    "ouvindo": ("OUVINDO", QColor(0, 255, 190), 1.6),
    "processando": ("PROCESSANDO", QColor(255, 180, 0), 4.0),
    "executando": ("EXECUTANDO", QColor(255, 120, 20), 5.0),
    "aguardando": ("AGUARDANDO CONFIRMAÇÃO", QColor(255, 210, 60), 0.8),
    "falando": ("FALANDO", QColor(70, 210, 255), 1.4),
    "erro": ("ERRO", QColor(255, 60, 60), 0.5),
}

MONTHS = ["JAN", "FEV", "MAR", "ABR", "MAI", "JUN", "JUL", "AGO", "SET", "OUT", "NOV", "DEZ"]


def alpha(color: QColor, a: float) -> QColor:
    c = QColor(color)
    c.setAlphaF(max(0.0, min(1.0, a)))
    return c


def lerp_color(a: QColor, b: QColor, t: float) -> QColor:
    return QColor(
        round(a.red() + (b.red() - a.red()) * t),
        round(a.green() + (b.green() - a.green()) * t),
        round(a.blue() + (b.blue() - a.blue()) * t),
    )


def hud_font(size: float, bold: bool = False, spacing: float = 2.0) -> QFont:
    f = QFont("Segoe UI", 10)
    f.setPointSizeF(size)
    f.setWeight(QFont.Weight.DemiBold if bold else QFont.Weight.Normal)
    f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, spacing)
    return f


class Hud(QWidget):
    def __init__(self, assistant: Assistant, cfg: Config):
        super().__init__()
        self.assistant = assistant
        self.cfg = cfg
        self.setWindowTitle(".".join(cfg.name))
        self.resize(1280, 760)
        self.setMinimumSize(640, 480)

        self.state = "inicializando"
        self.color = QColor(STATES["inicializando"][1])
        self.level = 0.0
        self.level_target = 0.0
        self.spin = 0.0
        self.t0 = time.monotonic()
        self.last_tick = self.t0
        self.heard_text = ""
        self.reply_text = ""
        self.text_time = 0.0
        self.log: deque[tuple[str, str]] = deque(maxlen=9)
        self.cpu = self.ram = self.disk = 0.0
        self.center = QPointF()
        self.radius = 100.0

        self.input = QLineEdit(self)
        self.input.setPlaceholderText("Digite um comando e pressione Enter…")
        self.input.setStyleSheet(
            "QLineEdit { background: rgba(0, 25, 40, 190); color: #c8f4ff; border: 1px solid rgba(0, 200, 255, 110);"
            " border-radius: 4px; padding: 9px 12px; font: 11pt 'Consolas'; selection-background-color: #0088aa; }"
            "QLineEdit:focus { border: 1px solid rgba(0, 220, 255, 220); }"
        )
        self.input.returnPressed.connect(self._submit)

        QShortcut(QKeySequence("Escape"), self, self._escape)
        QShortcut(QKeySequence("F11"), self, self._toggle_fullscreen)
        QShortcut(QKeySequence("Ctrl+N"), self, self.assistant.new_conversation)
        QShortcut(QKeySequence("Ctrl+Space"), self, self.assistant.toggle_listen)

        assistant.state_changed.connect(self._on_state)
        assistant.level_changed.connect(self._on_level)
        assistant.heard.connect(self._on_heard)
        assistant.replied.connect(self._on_reply)
        assistant.activity.connect(self._on_activity)
        assistant.confirm_requested.connect(self._on_confirm)
        assistant.confirm_answered.connect(self._on_confirm_answered)
        assistant.key_missing.connect(self.ask_api_key)

        self._frame = QTimer(self, interval=16, timeout=self._tick)
        self._frame.start()
        self._stats = QTimer(self, interval=1000, timeout=self._update_stats)
        self._stats.start()
        psutil.cpu_percent()

    def showEvent(self, event):
        super().showEvent(event)
        # Some com o Jarvis das capturas de tela (ver_tela enxerga o que está atrás dele).
        try:
            ctypes.windll.user32.SetWindowDisplayAffinity(int(self.winId()), 0x11)
        except Exception:
            pass

    # ── Sinais do assistente ──────────────────────────────────────────────
    def _on_state(self, state: str) -> None:
        self.state = state

    def _on_level(self, level: float) -> None:
        self.level_target = level

    def _on_heard(self, text: str) -> None:
        self.heard_text = text
        self.reply_text = ""
        self.text_time = time.monotonic()

    def _on_reply(self, text: str) -> None:
        self.reply_text = text
        self.text_time = time.monotonic()

    def _on_activity(self, text: str) -> None:
        self.log.append((datetime.now().strftime("%H:%M:%S"), text))

    def _on_confirm(self, question: str) -> None:
        if self.isMinimized():
            self.showNormal()
        self.raise_()
        self.activateWindow()
        box = QMessageBox(self)
        box.setWindowTitle(f"{self.cfg.name.title()} precisa de confirmação")
        box.setText(question)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        box.setDefaultButton(QMessageBox.StandardButton.No)
        box.setStyleSheet(
            "QMessageBox { background: #04121c; } QLabel { color: #c8f4ff; font: 10.5pt 'Segoe UI'; }"
            "QPushButton { background: #06283a; color: #c8f4ff; border: 1px solid #00a8d8; padding: 6px 18px; }"
            "QPushButton:hover { background: #0a3d57; }"
        )
        # Não bloqueia: a resposta também pode vir por voz, e aí a janela fecha sozinha.
        yes = QMessageBox.StandardButton.Yes.value
        box.finished.connect(lambda result: self.assistant.answer_confirm(result == yes))
        self._confirm_box = box
        box.open()

    def _on_confirm_answered(self) -> None:
        box = getattr(self, "_confirm_box", None)
        if box is not None and box.isVisible():
            box.done(QMessageBox.StandardButton.No.value)
        self._confirm_box = None

    def ask_api_key(self) -> None:
        key, ok = QInputDialog.getText(
            self,
            "Chave da Anthropic",
            "Cole sua ANTHROPIC_API_KEY (console.anthropic.com → API Keys).\nEla fica salva no arquivo .env:",
            QLineEdit.EchoMode.Password,
        )
        if ok and key.strip():
            self.assistant.set_api_key(key.strip())
            self._on_activity("Chave da API salva")

    # ── Entrada do usuário ────────────────────────────────────────────────
    def _submit(self) -> None:
        text = self.input.text()
        self.input.clear()
        self.assistant.submit_text(text)

    def _escape(self) -> None:
        if self.state in ("ouvindo", "processando", "executando", "falando"):
            self.assistant.stop()
        elif self.isFullScreen():
            self.showNormal()

    def _toggle_fullscreen(self) -> None:
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()

    def mousePressEvent(self, event):
        p = event.position()
        if math.hypot(p.x() - self.center.x(), p.y() - self.center.y()) <= self.radius * 1.05:
            self.assistant.toggle_listen()

    def resizeEvent(self, event):
        w, h = self.width(), self.height()
        iw = min(720, w - 48)
        self.input.setGeometry(round((w - iw) / 2), h - 70, iw, 40)

    # ── Animação ──────────────────────────────────────────────────────────
    def _tick(self) -> None:
        now = time.monotonic()
        dt = min(0.1, now - self.last_tick)
        self.last_tick = now
        _, target, speed = STATES.get(self.state, STATES["pronto"])
        self.color = lerp_color(self.color, target, min(1.0, dt * 6))
        self.level += (self.level_target - self.level) * min(1.0, dt * 14)
        self.spin += dt * 30 * speed
        self.update()

    def _update_stats(self) -> None:
        self.cpu = psutil.cpu_percent()
        self.ram = psutil.virtual_memory().percent
        try:
            self.disk = psutil.disk_usage("C:\\").percent
        except OSError:
            self.disk = 0.0

    # ── Desenho ───────────────────────────────────────────────────────────
    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        t = time.monotonic() - self.t0

        bg = QRadialGradient(QPointF(w / 2, h / 2), max(w, h) * 0.7)
        bg.setColorAt(0, QColor(4, 22, 34))
        bg.setColorAt(1, QColor(0, 3, 7))
        p.fillRect(self.rect(), QBrush(bg))
        self._draw_grid(p, w, h)

        top, bottom = 100, h - 180  # entre o cabeçalho e as legendas
        self.radius = max(60.0, min(w * 0.28, (bottom - top) / 2 / 1.25))
        self.center = QPointF(w / 2, (top + bottom) / 2)
        self._draw_reactor(p, self.center, self.radius, t)
        self._draw_header(p, w)
        if w >= 980:
            self._draw_system_panel(p, QRectF(28, 110, 230, 180))
            self._draw_activity_panel(p, QRectF(w - 318, 110, 290, 250))
        self._draw_subtitles(p, w, h)
        p.end()

    def _draw_grid(self, p: QPainter, w: int, h: int) -> None:
        p.setPen(QPen(alpha(self.color, 0.045), 1))
        step = 40
        for x in range(0, w, step):
            p.drawLine(x, 0, x, h)
        for y in range(0, h, step):
            p.drawLine(0, y, w, y)

    def _glow_ellipse(self, p: QPainter, c: QPointF, r: float, width: float, a: float = 1.0) -> None:
        for wmul, amul in ((6, 0.06), (3, 0.15), (1, 1.0)):
            p.setPen(QPen(alpha(self.color, a * amul), width * wmul))
            p.drawEllipse(c, r, r)

    def _glow_arc(self, p: QPainter, c: QPointF, r: float, start: float, span: float, width: float, a: float = 1.0) -> None:
        rect = QRectF(c.x() - r, c.y() - r, 2 * r, 2 * r)
        for wmul, amul in ((4, 0.08), (2, 0.2), (1, 1.0)):
            pen = QPen(alpha(self.color, a * amul), width * wmul)
            pen.setCapStyle(Qt.PenCapStyle.FlatCap)
            p.setPen(pen)
            p.drawArc(rect, round(start * 16), round(span * 16))

    def _draw_reactor(self, p: QPainter, c: QPointF, R: float, t: float) -> None:
        lvl = self.level
        breath = 0.5 + 0.5 * math.sin(t * 1.6)
        p.setBrush(Qt.BrushStyle.NoBrush)

        # Varredura de radar no anel externo.
        sweep = QConicalGradient(c, -self.spin * 1.5)
        sweep.setColorAt(0.0, alpha(self.color, 0.28))
        sweep.setColorAt(0.12, alpha(self.color, 0.0))
        sweep.setColorAt(1.0, alpha(self.color, 0.0))
        ring = QPainterPath()
        ring.addEllipse(c, R * 1.22, R * 1.22)
        inner = QPainterPath()
        inner.addEllipse(c, R * 1.06, R * 1.06)
        p.fillPath(ring.subtracted(inner), QBrush(sweep))
        self._glow_ellipse(p, c, R * 1.22, 1, 0.35)

        # Régua de marcações girando devagar.
        p.save()
        p.translate(c)
        p.rotate(self.spin * 0.25)
        for i in range(120):
            long = i % 10 == 0
            p.setPen(QPen(alpha(self.color, 0.9 if long else 0.45), 2 if long else 1))
            p.drawLine(QPointF(R, 0), QPointF(R - (R * 0.07 if long else R * 0.03), 0))
            p.rotate(3)
        p.restore()

        # Arcos grossos em sentidos opostos.
        for k in range(3):
            self._glow_arc(p, c, R * 0.9, -self.spin + k * 120, 68, R * 0.035, 0.85)
        for k in range(4):
            self._glow_arc(p, c, R * 0.8, self.spin * 1.6 + k * 90 + 20, 40, R * 0.012, 0.7)

        # Anel tracejado.
        p.save()
        p.translate(c)
        p.rotate(-self.spin * 0.6)
        dash = QPen(alpha(self.color, 0.55), R * 0.018)
        dash.setDashPattern([2, 3])
        p.setPen(dash)
        p.drawEllipse(QPointF(0, 0), R * 0.72, R * 0.72)
        p.restore()

        # Anel de segmentos que acende com o volume da voz.
        segments = 48
        lit = lvl * segments if lvl > 0.02 else breath * 6
        p.save()
        p.translate(c)
        for i in range(segments):
            d = min(i, segments - i)
            on = d < lit / 2
            pen = QPen(alpha(self.color, 0.95 if on else 0.13), R * 0.06)
            pen.setCapStyle(Qt.PenCapStyle.FlatCap)
            p.setPen(pen)
            r = R * 0.62
            start = 90 + i * (360 / segments) + 1.2
            p.drawArc(QRectF(-r, -r, 2 * r, 2 * r), round(start * 16), round((360 / segments - 2.4) * 16))
        p.restore()

        # Núcleo brilhante que pulsa.
        core_r = R * (0.36 + 0.05 * breath + 0.12 * lvl)
        glow = QRadialGradient(c, core_r * 1.6)
        glow.setColorAt(0.0, QColor(235, 252, 255, 240))
        glow.setColorAt(0.18, alpha(self.color, 0.95))
        glow.setColorAt(0.55, alpha(self.color, 0.28))
        glow.setColorAt(1.0, alpha(self.color, 0.0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(glow)
        p.drawEllipse(c, core_r * 1.6, core_r * 1.6)
        p.setBrush(Qt.BrushStyle.NoBrush)
        self._glow_ellipse(p, c, R * 0.44, R * 0.008, 0.8)

        # Triângulo interno girando, estilo reator.
        p.save()
        p.translate(c)
        p.rotate(self.spin * 0.9)
        tri = QPainterPath()
        for k in range(3):
            ang = math.radians(-90 + k * 120)
            pt = QPointF(math.cos(ang) * R * 0.3, math.sin(ang) * R * 0.3)
            if k == 0:
                tri.moveTo(pt)
            else:
                tri.lineTo(pt)
        tri.closeSubpath()
        p.setPen(QPen(alpha(QColor(230, 250, 255), 0.55), R * 0.01))
        p.drawPath(tri)
        p.restore()

        # Rótulos.
        label, _, _ = STATES.get(self.state, STATES["pronto"])
        p.setPen(QColor(235, 252, 255))
        p.setFont(hud_font(max(10, R * 0.075), True, 4))
        p.drawText(QRectF(c.x() - R, c.y() - R * 0.12, 2 * R, R * 0.14), Qt.AlignmentFlag.AlignCenter, self.cfg.name)
        p.setPen(QColor(10, 30, 45) if self.level < 0.5 else QColor(235, 252, 255))
        p.setFont(hud_font(max(7, R * 0.038), True, 3))
        p.drawText(QRectF(c.x() - R, c.y() + R * 0.04, 2 * R, R * 0.1), Qt.AlignmentFlag.AlignCenter, label)

    def _corners(self, p: QPainter, r: QRectF, size: float = 14) -> None:
        p.setPen(QPen(alpha(self.color, 0.8), 2))
        for x, y, dx, dy in (
            (r.left(), r.top(), 1, 1),
            (r.right(), r.top(), -1, 1),
            (r.left(), r.bottom(), 1, -1),
            (r.right(), r.bottom(), -1, -1),
        ):
            p.drawLine(QPointF(x, y), QPointF(x + dx * size, y))
            p.drawLine(QPointF(x, y), QPointF(x, y + dy * size))
        p.setPen(QPen(alpha(self.color, 0.15), 1))
        p.drawRect(r)

    def _draw_header(self, p: QPainter, w: int) -> None:
        p.setPen(QColor(220, 248, 255))
        p.setFont(hud_font(20, True, 8))
        p.drawText(QPointF(30, 50), ".".join(self.cfg.name))
        p.setPen(alpha(self.color, 0.75))
        p.setFont(hud_font(8.5, False, 2))
        p.drawText(QPointF(32, 72), "ASSISTENTE PESSOAL INTELIGENTE")

        now = datetime.now()
        p.setPen(QColor(220, 248, 255))
        p.setFont(hud_font(22, True, 3))
        p.drawText(QRectF(w - 330, 22, 300, 36), Qt.AlignmentFlag.AlignRight, now.strftime("%H:%M:%S"))
        p.setPen(alpha(self.color, 0.75))
        p.setFont(hud_font(9, False, 3))
        p.drawText(
            QRectF(w - 330, 60, 300, 20), Qt.AlignmentFlag.AlignRight, f"{now.day:02d} {MONTHS[now.month - 1]} {now.year}"
        )
        p.setPen(QPen(alpha(self.color, 0.35), 1))
        p.drawLine(QPointF(30, 88), QPointF(w - 30, 88))

    def _draw_system_panel(self, p: QPainter, r: QRectF) -> None:
        self._corners(p, r)
        p.setPen(alpha(self.color, 0.9))
        p.setFont(hud_font(9, True, 3))
        p.drawText(QPointF(r.left() + 16, r.top() + 26), "SISTEMA")
        for i, (name, value) in enumerate((("CPU", self.cpu), ("MEMÓRIA", self.ram), ("DISCO C:", self.disk))):
            y = r.top() + 58 + i * 40
            p.setPen(QColor(200, 240, 255))
            p.setFont(hud_font(8.5, False, 2))
            p.drawText(QPointF(r.left() + 16, y), name)
            p.drawText(QRectF(r.left(), y - 13, r.width() - 16, 16), Qt.AlignmentFlag.AlignRight, f"{value:.0f}%")
            bar = QRectF(r.left() + 16, y + 7, r.width() - 32, 6)
            p.fillRect(bar, alpha(self.color, 0.15))
            p.fillRect(QRectF(bar.left(), bar.top(), bar.width() * value / 100, bar.height()), alpha(self.color, 0.85))
        brain = self.cfg.ollama_model if self.cfg.brain == "ollama" else self.cfg.model
        p.setPen(alpha(self.color, 0.7))
        p.setFont(hud_font(7.5, False, 1.5))
        p.drawText(
            QPointF(r.left() + 16, r.bottom() + 22),
            p.fontMetrics().elidedText(f"CÉREBRO  {brain.upper()}", Qt.TextElideMode.ElideRight, round(r.width() - 16)),
        )

    def _draw_activity_panel(self, p: QPainter, r: QRectF) -> None:
        self._corners(p, r)
        p.setPen(alpha(self.color, 0.9))
        p.setFont(hud_font(9, True, 3))
        p.drawText(QPointF(r.left() + 16, r.top() + 26), "ATIVIDADE")
        p.setFont(QFont("Consolas", 9))
        fm = p.fontMetrics()
        for i, (stamp, text) in enumerate(self.log):
            y = r.top() + 52 + i * 21
            p.setPen(alpha(self.color, 0.6))
            p.drawText(QPointF(r.left() + 16, y), stamp)
            p.setPen(QColor(200, 240, 255))
            p.drawText(QPointF(r.left() + 84, y), fm.elidedText(text, Qt.TextElideMode.ElideRight, round(r.width() - 98)))

    def _draw_subtitles(self, p: QPainter, w: int, h: int) -> None:
        age = time.monotonic() - self.text_time
        fade = 1.0 if age < 45 else max(0.0, 1 - (age - 45) / 5)
        if fade <= 0:
            self._draw_hint(p, w, h)
            return
        box_w = min(980, w - 60)
        x = (w - box_w) / 2
        if self.heard_text:
            p.setPen(alpha(QColor(150, 210, 230), fade))
            p.setFont(hud_font(10, False, 1))
            p.drawText(
                QRectF(x, h - 168, box_w, 22),
                Qt.AlignmentFlag.AlignCenter,
                p.fontMetrics().elidedText(f"VOCÊ › {self.heard_text}", Qt.TextElideMode.ElideRight, round(box_w)),
            )
        if self.reply_text:
            p.setPen(alpha(QColor(225, 250, 255), fade))
            p.setFont(hud_font(12, False, 0.5))
            p.drawText(
                QRectF(x, h - 144, box_w, 66),
                Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap,
                self.reply_text,
            )
        else:
            self._draw_hint(p, w, h)

    def _draw_hint(self, p: QPainter, w: int, h: int) -> None:
        p.setPen(alpha(self.color, 0.55))
        p.setFont(hud_font(8.5, False, 2))
        p.drawText(
            QRectF(0, h - 100, w, 20),
            Qt.AlignmentFlag.AlignCenter,
            (f'DIGA "{self.cfg.name}"  ·  ' if self.cfg.wake_word else "")
            + f"{self.cfg.hotkey.upper()} OU CLIQUE NO REATOR  ·  ESC PARA PARAR  ·  F11 TELA CHEIA  ·  CTRL+N NOVA CONVERSA",
        )
