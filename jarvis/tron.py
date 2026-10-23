"""Tema TRON: rosto 3D feito de bits, piso de grade em perspectiva e motos de luz."""
from __future__ import annotations

import math
import random

import numpy as np
from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPen, QPixmap, QPolygonF

ORANGE = QColor(255, 140, 0)


def _alpha(color: QColor, a: float) -> QColor:
    c = QColor(color)
    c.setAlphaF(max(0.0, min(1.0, a)))
    return c


def _width(y: np.ndarray) -> np.ndarray:
    """Meia-largura da cabeça em cada altura: queixo afinando, testa levemente estreita."""
    base = 0.72 * np.sqrt(np.clip(1 - (y / 0.98) ** 2, 0, 1))
    jaw = np.clip((-0.12 - y) / 0.86, 0, 1)
    brow = np.clip((y - 0.55) / 0.43, 0, 1)
    return base * (1 - 0.42 * jaw**1.25) * (1 - 0.08 * brow)


def _depth(y: np.ndarray) -> np.ndarray:
    jaw = np.clip((-0.2 - y) / 0.78, 0, 1)
    return 0.8 * np.sqrt(np.clip(1 - (y / 0.98) ** 2, 0, 1)) * (1 - 0.25 * jaw)


def _surface_z(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    w = np.maximum(_width(y), 1e-3)
    return _depth(y) * np.sqrt(np.clip(1 - (x / w) ** 2, 0, 1))


class Face:
    """Nuvem de pontos de um rosto. Os traços (olhos, sobrancelhas, boca) se mexem a cada quadro."""

    EYE_X, EYE_Y, EYE_RX, EYE_RY = 0.27, 0.13, 0.13, 0.065
    MOUTH_Y, MOUTH_W = -0.47, 0.22

    def __init__(self, seed: int = 7):
        rng = np.random.default_rng(seed)
        rows = []
        for y in np.linspace(-0.93, 0.95, 34):
            w = float(_width(np.array([y]))[0])
            n = int(12 + 70 * w)
            theta = np.linspace(-math.pi * 0.62, math.pi * 0.62, n)
            d = float(_depth(np.array([y]))[0])
            rows.append(np.column_stack([w * np.sin(theta), np.full(n, y), d * np.cos(theta)]))
        self.skin = np.vstack(rows)
        self.skin_phase = rng.uniform(0, 2 * math.pi, len(self.skin))
        # Pescoço: alguns anéis abaixo do queixo, mais apagados.
        neck = []
        for y in np.linspace(-1.05, -1.45, 5):
            theta = np.linspace(-math.pi * 0.55, math.pi * 0.55, 26)
            neck.append(np.column_stack([0.3 * np.sin(theta), np.full(26, y), 0.3 * np.cos(theta)]))
        self.neck = np.vstack(neck)
        # Tira os pontos de pele onde ficam os olhos, para eles aparecerem como recortes.
        ex = (np.abs(self.skin[:, 0]) - self.EYE_X) / (self.EYE_RX * 1.25)
        ey = (self.skin[:, 1] - self.EYE_Y) / (self.EYE_RY * 2.0)
        self.skin_keep = (ex**2 + ey**2 > 1) & (self.skin[:, 2] > -0.6)

    def features(self, eye_open: float, mouth_open: float, brow: float, look: float) -> tuple[np.ndarray, np.ndarray]:
        """Pontos dos traços e o brilho de cada um."""
        pts, glow = [], []

        def add(xs, ys, dz=0.0, g=1.0):
            xs, ys = np.asarray(xs, float), np.asarray(ys, float)
            zs = _surface_z(xs, ys) + dz
            pts.append(np.column_stack([xs, ys, zs]))
            glow.append(np.full(len(xs), g))

        a = np.linspace(0, 2 * math.pi, 26, endpoint=False)
        for side in (-1, 1):
            cx = side * self.EYE_X
            # Contorno do olho (pálpebras) e íris que acompanha o "olhar".
            add(cx + self.EYE_RX * np.cos(a), self.EYE_Y + self.EYE_RY * eye_open * np.sin(a), 0.01, 0.9)
            if eye_open > 0.3:
                ia = np.linspace(0, 2 * math.pi, 12, endpoint=False)
                ix = cx + look * 0.05
                add(ix + 0.035 * np.cos(ia), self.EYE_Y + 0.035 * eye_open * np.sin(ia), 0.02, 1.3)
                add([ix], [self.EYE_Y], 0.025, 1.6)
            # Sobrancelha: sobe quando escuta, a ponta interna desce quando "pensa".
            bx = np.linspace(0.12, 0.43, 14)
            by = 0.29 + brow * 0.04 + 0.03 * np.sin((bx - 0.12) / 0.31 * math.pi) - (brow < 0) * 0.04 * (0.43 - bx) / 0.31
            add(side * bx, by, 0.02, 0.85)
        # Nariz: ponte, ponta saliente e narinas.
        ny = np.linspace(0.1, -0.2, 11)
        add(np.zeros_like(ny), ny, 0.03 + 0.14 * (0.1 - ny) / 0.3, 0.7)
        na = np.linspace(math.pi * 0.15, math.pi * 0.85, 9)
        add(0.07 * np.cos(na), -0.24 + 0.03 * np.sin(na) * -1, 0.08, 0.7)
        # Boca: lábios superior e inferior; abre com o volume da voz.
        mx = np.linspace(-self.MOUTH_W, self.MOUTH_W, 24)
        shape = 1 - (mx / self.MOUTH_W) ** 2
        add(mx, self.MOUTH_Y + 0.025 * shape + mouth_open * 0.05 * shape, 0.03, 1.0)
        add(mx, self.MOUTH_Y - 0.02 * shape - mouth_open * 0.13 * shape, 0.03, 1.0)
        # Maçãs do rosto e mandíbula, linhas finas que dão volume.
        for side in (-1, 1):
            cy = np.linspace(0.0, -0.32, 9)
            add(side * (0.5 - 0.06 * np.abs(cy + 0.16) * 3), cy, 0.0, 0.45)
        return np.vstack(pts), np.concatenate(glow)


class TronScene:
    def __init__(self):
        self.face = Face()
        self.t = 0.0
        self.scroll = 0.0
        self.yaw = 0.0
        self.pitch = 0.0
        self.mouth = 0.0
        self.blink_at = 3.0
        self.glitch_until = 0.0
        self.glitch_band = 0.0
        self.next_glitch = 6.0
        self.particles: list[list] = []  # [x, y, vy, vida, caractere]
        self.cycles = [
            {"x": -14.0, "z": 12.0, "dir": 1, "speed": 7.0, "color": None},
            {"x": 14.0, "z": 18.0, "dir": -1, "speed": 9.0, "color": ORANGE},
        ]
        self.waveform = [0.0] * 90
        self._state = "pronto"
        # Camadas que quase não mudam ficam pré-desenhadas (as linhas custavam ~40 ms por quadro).
        self._static_key = None
        self._static: QPixmap | None = None
        self._scan_key = None
        self._scan: QPixmap | None = None

    # ── Animação ──────────────────────────────────────────────────────────
    def update(self, dt: float, state: str, level: float, speed: float) -> None:
        self.t += dt
        self._state = state
        t = self.t
        self.scroll = (self.scroll + dt * (0.6 + 0.5 * speed)) % 1.0
        thinking = state in ("processando", "executando")
        listening = state == "ouvindo"
        target_yaw = 0.35 * math.sin(t * 1.3) if thinking else 0.18 * math.sin(t * 0.35)
        target_pitch = 0.08 if listening else 0.04 * math.sin(t * 0.27)
        self.yaw += (target_yaw - self.yaw) * min(1, dt * 2.5)
        self.pitch += (target_pitch - self.pitch) * min(1, dt * 2.5)
        self.mouth += ((level * 1.4 if state == "falando" else 0.0) - self.mouth) * min(1, dt * 18)
        if t > self.blink_at + 0.14:
            self.blink_at = t + random.uniform(2.5, 6.0)
        if t > self.next_glitch:
            self.glitch_until = t + random.uniform(0.08, 0.2)
            self.glitch_band = random.uniform(-0.8, 0.8)
            self.next_glitch = t + random.uniform(4, 10) / (2 if thinking else 1)
        for c in self.cycles:
            c["x"] += c["dir"] * c["speed"] * dt * (1 + speed * 0.3)
            if abs(c["x"]) > 16:
                c["x"] = -16 * c["dir"]
                c["z"] = random.choice([11.0, 14.0, 18.0, 23.0])
        # Bits que se soltam do contorno do rosto e sobem.
        if random.random() < dt * (14 if thinking or state == "falando" else 5):
            side = random.choice((-1, 1))
            y = random.uniform(-0.6, 0.8)
            x = side * float(_width(np.array([y]))[0]) * 1.02
            self.particles.append([x, y, random.uniform(0.15, 0.45), 1.0, random.choice("01")])
        for p in self.particles:
            p[1] += p[2] * dt
            p[0] += np.sign(p[0]) * 0.05 * dt
            p[3] -= dt * 0.6
        self.particles = [p for p in self.particles if p[3] > 0]
        self.waveform = self.waveform[1:] + [level]

    def eye_open(self) -> float:
        d = self.t - self.blink_at
        return 0.12 if 0 <= d <= 0.14 else 1.0

    # ── Desenho ───────────────────────────────────────────────────────────
    def paint_background(self, p: QPainter, w: int, h: int, horizon: float, color: QColor) -> None:
        key = (w, h, round(horizon), color.rgb())
        if key != self._static_key:
            self._static_key = key
            self._static = self._render_static(w, h, horizon, color)
        p.drawPixmap(0, 0, self._static)
        self._paint_floor(p, w, h, horizon, color)
        p.setPen(QPen(_alpha(color, 0.9), 1.5))
        p.drawLine(QPointF(0, horizon), QPointF(w, horizon))

    def _render_static(self, w: int, h: int, horizon: float, color: QColor) -> QPixmap:
        """Céu, chão, linhas do piso que vão até o horizonte e o brilho do horizonte."""
        pix = QPixmap(w, h)
        p = QPainter(pix)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        sky = QLinearGradient(0, 0, 0, horizon)
        sky.setColorAt(0, QColor(0, 2, 6))
        sky.setColorAt(1, QColor(2, 14, 26))
        p.fillRect(QRectF(0, 0, w, horizon), sky)
        p.fillRect(QRectF(0, horizon, w, h - horizon), QColor(0, 3, 8))
        f, cx = h * 0.55, w / 2
        for k in range(-40, 41):
            p.setPen(QPen(_alpha(color, 0.35 if k % 5 == 0 else 0.16), 1))
            p.drawLine(QPointF(cx + k * f / 0.9, horizon + f / 0.9), QPointF(cx + k * f / 40, horizon + f / 40))
        glow = QLinearGradient(0, horizon - 40, 0, horizon + 6)
        glow.setColorAt(0, _alpha(color, 0.0))
        glow.setColorAt(1, _alpha(color, 0.22))
        p.fillRect(QRectF(0, horizon - 40, w, 46), glow)
        p.end()
        return pix

    def _paint_floor(self, p: QPainter, w: int, h: int, horizon: float, color: QColor) -> None:
        """Parte animada do piso: linhas que vêm na direção da câmera e as motos de luz."""
        f = h * 0.55
        cx = w / 2

        def proj(x: float, z: float) -> QPointF:
            return QPointF(cx + x * f / z, horizon + 1.0 * f / z)

        near = 0.9
        p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        for n in range(1, 40):
            z = n - self.scroll
            if z < near:
                continue
            p.setPen(QPen(_alpha(color, 0.4 * min(1.0, 4 / z)), 1))
            y = horizon + f / z
            p.drawLine(QPointF(0, y), QPointF(w, y))
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        # Motos de luz com rastro.
        for c in self.cycles:
            col = c["color"] or color
            tail = c["x"] - c["dir"] * 6
            a, b = proj(tail, c["z"]), proj(c["x"], c["z"])
            for wd, al in ((10, 0.08), (5, 0.25), (2, 1.0)):
                p.setPen(QPen(_alpha(col, al), wd * 6 / c["z"] + 0.5))
                p.drawLine(a, b)
            p.setPen(QPen(QColor(255, 255, 255, 230), max(2.0, 18 / c["z"])))
            p.drawPoint(b)

    def paint_scanlines(self, p: QPainter, w: int, h: int) -> None:
        if self._scan_key != (w, h):
            self._scan_key = (w, h)
            self._scan = QPixmap(w, h)
            self._scan.fill(Qt.GlobalColor.transparent)
            sp = QPainter(self._scan)
            sp.setPen(QPen(QColor(0, 0, 0, 55), 1))
            for y in range(0, h, 3):
                sp.drawLine(0, y, w, y)
            sp.end()
        p.drawPixmap(0, 0, self._scan)

    def paint_face(self, p: QPainter, cx: float, cy: float, scale: float, color: QColor, level: float) -> None:
        face = self.face
        t = self.t
        cy_, sy_ = math.cos(self.yaw), math.sin(self.yaw)
        cp, sp = math.cos(self.pitch), math.sin(self.pitch)
        rot = np.array([[cy_, 0, sy_], [0, 1, 0], [-sy_, 0, cy_]]) @ np.array([[1, 0, 0], [0, cp, -sp], [0, sp, cp]])

        def project(pts: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
            r = pts @ rot.T
            persp = 4.0 / (4.0 - r[:, 2])
            return cx + r[:, 0] * scale * persp, cy - r[:, 1] * scale * persp, r[:, 2]

        glitching = t < self.glitch_until
        accent = ORANGE if glitching else color
        band = 0.95 - ((t * 0.45) % 1.0) * 2.1  # faixa de varredura descendo pelo rosto

        # Pele: anéis de bits; o brilho depende de estar de frente, da varredura e de uma cintilação.
        skin = face.skin[face.skin_keep]
        phase = face.skin_phase[face.skin_keep]
        mouth_hole = (np.abs(skin[:, 0]) < Face.MOUTH_W * 1.05) & (
            np.abs(skin[:, 1] - (Face.MOUTH_Y - 0.04 * self.mouth)) < 0.02 + 0.07 * self.mouth
        )
        skin, phase = skin[~mouth_hole], phase[~mouth_hole]
        xs, ys, zs = project(skin)
        if glitching:
            hit = np.abs(skin[:, 1] - self.glitch_band) < 0.12
            xs = xs + hit * scale * 0.06 * np.sin(skin[:, 1] * 40)
        facing = np.clip((zs + 0.3) / 1.1, 0, 1)
        bright = (0.18 + 0.62 * facing) * (0.75 + 0.25 * np.sin(t * 3 + phase))
        bright += 0.6 * np.exp(-(((skin[:, 1] - band) / 0.05) ** 2)) * facing
        bright *= 0.85 + 0.4 * level
        self._dots(p, xs, ys, bright, color, max(1.6, scale * 0.012))

        nx, ny, nz = project(face.neck)
        self._dots(p, nx, ny, np.full(len(nx), 0.22) * np.clip((nz + 0.3), 0.2, 1), color, max(1.4, scale * 0.01))

        # Traços do rosto, mais brilhantes.
        brow = 1.0 if self._state == "ouvindo" else (-1.0 if self._state in ("processando", "executando") else 0.0)
        look = math.sin(t * 2.2) if self._state in ("processando", "executando") else 0.25 * math.sin(t * 0.5)
        pts, glow = face.features(self.eye_open(), self.mouth, brow, look)
        fx, fy, fz = project(pts)
        self._dots(p, fx, fy, glow * np.clip((fz + 0.4) / 0.9, 0.2, 1.2), accent, max(2.0, scale * 0.016), core=True)

        # Bits soltos subindo como dados se dissolvendo.
        p.setFont(QFont("Consolas", max(7, int(scale * 0.05))))
        for x, y, _, life, ch in self.particles:
            px, py, _ = project(np.array([[x, y, 0.1]]))
            p.setPen(_alpha(color, life * 0.8))
            p.drawText(QPointF(px[0], py[0]), ch)

    @staticmethod
    def _dots(p: QPainter, xs, ys, bright, color: QColor, size: float, core: bool = False) -> None:
        """Desenha pontos em lotes por faixa de brilho (bem mais rápido que um a um)."""
        levels = np.clip((bright * 4).astype(int), 0, 6)
        pen = QPen()
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        for lvl in range(1, 7):
            idx = np.nonzero(levels == lvl)[0]
            if len(idx) == 0:
                continue
            poly = QPolygonF([QPointF(float(xs[i]), float(ys[i])) for i in idx])
            a = lvl / 4
            pen.setColor(_alpha(color, 0.12 * a))
            pen.setWidthF(size * 3.2)
            p.setPen(pen)
            p.drawPoints(poly)
            pen.setColor(_alpha(QColor(235, 255, 255) if (core and lvl >= 4) else color, min(1.0, 0.35 + 0.25 * a)))
            pen.setWidthF(size)
            p.setPen(pen)
            p.drawPoints(poly)

    def paint_waveform(self, p: QPainter, cx: float, y: float, width: float, color: QColor) -> None:
        """Linha de áudio estilo osciloscópio, embaixo do rosto."""
        n = len(self.waveform)
        step = width / (n - 1)
        poly = QPolygonF()
        for i, v in enumerate(self.waveform):
            amp = v * 16 * math.sin(i * 0.9 + self.t * 12)
            poly.append(QPointF(cx - width / 2 + i * step, y + amp))
        for wd, al in ((6, 0.12), (1.6, 0.9)):
            p.setPen(QPen(_alpha(color, al), wd))
            p.drawPolyline(poly)
