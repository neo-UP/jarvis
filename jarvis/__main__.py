"""Ponto de entrada: python -m jarvis"""
from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler

from PyQt6.QtWidgets import QApplication

from .assistant import Assistant
from .config import LOG_DIR, load_config
from .hud import Hud


def setup_logging() -> None:
    handlers: list[logging.Handler] = [
        RotatingFileHandler(LOG_DIR / "jarvis.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    ]
    if sys.stderr is not None:  # pythonw não tem console
        handlers.append(logging.StreamHandler())
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s", handlers=handlers)
    for noisy in ("httpx", "httpx2", "faster_whisper"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def main() -> None:
    setup_logging()
    app = QApplication(sys.argv)
    app.setApplicationName("Vektor")
    cfg = load_config()
    assistant = Assistant(cfg)
    activity_log = logging.getLogger("jarvis.atividade")
    assistant.activity.connect(activity_log.info)
    assistant.heard.connect(lambda text: activity_log.info("Você: %s", text))
    assistant.replied.connect(lambda text: activity_log.info("%s: %s", cfg.name.title(), text))
    hud = Hud(assistant, cfg)
    hud.show()
    assistant.start()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
