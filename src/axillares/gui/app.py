"""Ponto de entrada da interface gráfica (`axil gui`)."""

from __future__ import annotations

import os
import sys

# O QtWebEngine (editor) precisa ser importado e configurado antes de existir a QApplication.
from PySide6 import QtWebEngineWidgets  # noqa: F401
from PySide6.QtCore import QCoreApplication, Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from axillares.gui import tema as t
from axillares.gui.janela import ICONE, JanelaPrincipal


def criar_aplicacao(argv: list[str] | None = None) -> QApplication:
    if QApplication.instance() is None:
        QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
        if os.environ.get("QT_QPA_PLATFORM") == "offscreen":
            # sem tela (testes e capturas): Chromium sem GPU
            os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu")
    app = QApplication.instance() or QApplication(argv or sys.argv)
    app.setApplicationName("Axillares")
    app.setOrganizationName("Axillares")
    app.setDesktopFileName("axillares")
    app.setWindowIcon(QIcon(str(ICONE)))
    t.carregar_fontes()
    fonte = t.fonte(t.Papel.CORPO)
    app.setFont(fonte)
    t.tema().aplicar()
    return app


def principal(argv: list[str] | None = None) -> int:
    app = criar_aplicacao(argv)
    janela = JanelaPrincipal()
    janela.show()
    return app.exec()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(principal())
