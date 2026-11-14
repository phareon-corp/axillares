"""Axillares — ambiente integrado de desktop para projeto de CI com ferramentas abertas."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("axillares")
except PackageNotFoundError:  # executando direto do código-fonte, sem instalar
    __version__ = "0.0.0+fonte"

__all__ = ["__version__"]
