"""Projetos abertos recentemente — compartilhado entre CLI e GUI.

Guardado em ~/.config/axillares/recentes.json (ou $XDG_CONFIG_HOME). É preferência do usuário,
não dado de projeto: perder o arquivo não perde nada além da lista.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

LIMITE = 12


def arquivo() -> Path:
    base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "axillares" / "recentes.json"


def listar() -> list[dict]:
    """[{caminho, nome, aberto_em}], do mais recente ao mais antigo, só os que ainda existem."""
    try:
        dados = json.loads(arquivo().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [
        d for d in dados if isinstance(d, dict) and (Path(d["caminho"]) / "axil.toml").is_file()
    ]


def registrar(raiz: Path, nome: str) -> None:
    raiz = raiz.resolve()
    atuais = [d for d in listar() if Path(d["caminho"]) != raiz]
    novo = {
        "caminho": str(raiz),
        "nome": nome,
        "aberto_em": datetime.now().isoformat(timespec="seconds"),
    }
    destino = arquivo()
    try:
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_text(
            json.dumps([novo, *atuais][:LIMITE], indent=2, ensure_ascii=False), encoding="utf-8"
        )
    except OSError:
        pass  # lista de recentes nunca impede o trabalho
