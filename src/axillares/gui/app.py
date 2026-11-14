"""Ponto de entrada da interface gráfica (`axil gui`)."""

from __future__ import annotations

import sys

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from axillares.gui import tema as t
from axillares.gui.janela import ICONE, JanelaPrincipal


def criar_aplicacao(argv: list[str] | None = None) -> QApplication:
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
