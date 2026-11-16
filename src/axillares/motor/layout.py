"""Renderização de layout pelo KLayout da imagem, sem janela, para o visualizador embutido.

Um processo do KLayout fica vivo dentro do contêiner enquanto o GDS estiver aberto e responde a
pedidos de renderização (JSON por linha). Assim cada zoom custa ~0,1 s em vez de subir um
contêiner. Quem lê o GDS é o KLayout, em outro processo — o Axillares não tem leitor de GDS.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import threading
from dataclasses import dataclass, field
from pathlib import Path

from axillares.ambiente import conteiner as ct
from axillares.ambiente.executor import ExecutorReal
from axillares.ambiente.perfil import Perfil, carregar_perfil
from axillares.motor.base import ErroMotor

SERVIDOR = Path(__file__).parent / "conteiner" / "servidor_layout.py"
PREFIXO = "@@axil "


@dataclass(frozen=True)
class Camada:
    indice: int
    nome: str
    fonte: str
    cor: str

    @property
    def nome_curto(self) -> str:
        return self.nome.split(" - ")[0]


@dataclass(frozen=True)
class InfoLayout:
    celula: str
    caixa: tuple[float, float, float, float]
    """Em µm: x1, y1, x2, y2."""
    camadas: list[Camada] = field(default_factory=list)
    analise: bool = False
    """Se há regras do PDK para destaques e ponteiras."""


@dataclass(frozen=True)
class Imagem:
    arquivo: Path
    caixa: tuple[float, float, float, float]
    largura: int
    altura: int
    pedido: int


def regras_do_pdk(pdk: str) -> dict:
    """Camadas de dispositivos e de conectividade do PDK (dado, em templates/explicacoes)."""
    from axillares.core import explicacoes as ex

    return ex.regras_de_layout(pdk)


class RenderizadorLayout:
    def __init__(
        self,
        gds: Path,
        pdk: str = "skywater130",
        perfil: Perfil | None = None,
        programa: ct.ProgramaConteiner | None = None,
    ) -> None:
        self.gds = gds.resolve()
        self.perfil = perfil or carregar_perfil()
        self.pdk = pdk
        self._programa = programa
        self._processo: subprocess.Popen[str] | None = None
        self._trava = threading.Lock()
        self._saida = Path(tempfile.mkdtemp(prefix="axil-layout-"))
        self._contador = 0
        self.info: InfoLayout | None = None

    def comando(self) -> list[str]:
        prog = self._programa or ct.detectar_programa(ExecutorReal())
        if prog is None:
            raise ErroMotor(
                "Nem podman nem docker estão instalados; veja “axil ambiente situacao”."
            )
        self._programa = prog
        klayout = self.perfil.visualizador.get("klayout", "klayout")
        lyp = self.perfil.camadas.get(self.pdk, "")
        extras = []
        celulas = self.perfil.celulas_gds.get(self.pdk)
        if celulas:
            extras += ["-rd", f"celulas={celulas}"]
        regras = regras_do_pdk(self.pdk)
        if regras:
            (self._saida / "regras.json").write_text(json.dumps(regras), encoding="utf-8")
            extras += ["-rd", "regras=/saida/regras.json"]
        usuario = (
            ["--userns=keep-id"] if prog.nome == "podman"
            else ["--user", f"{os.getuid()}:{os.getgid()}"]
        )  # fmt: skip
        return [
            prog.nome, "run", "-i", "--rm", "--init", "--network=none", *usuario,
            "-v", f"{self.gds.parent}:/gds:ro,z",
            "-v", f"{self._saida}:/saida:z",
            "-v", f"{SERVIDOR.parent}:/axil:ro,z",
            "-e", "HOME=/tmp", "--entrypoint", klayout, self.perfil.imagem.referencia,
            "-zz", "-r", f"/axil/{SERVIDOR.name}",
            "-rd", f"gds=/gds/{self.gds.name}", "-rd", f"lyp={lyp}", "-rd", "saida=/saida",
            *extras,
        ]  # fmt: skip

    def _ler_resposta(self) -> dict:
        assert self._processo is not None and self._processo.stdout is not None
        ruido: list[str] = []
        for linha in self._processo.stdout:
            if linha.startswith(PREFIXO):
                return json.loads(linha[len(PREFIXO) :])
            ruido.append(linha.rstrip())
        detalhe = "\n".join(ruido[-6:])
        raise ErroMotor(f"O KLayout da imagem encerrou sem responder.\n{detalhe}".strip())

    def iniciar(self) -> InfoLayout:
        if not self.gds.is_file():
            raise ErroMotor(f"O arquivo {self.gds.name} não existe.")
        with self._trava:
            if self._processo is None:
                self._processo = subprocess.Popen(
                    self.comando(),
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    bufsize=1,
                )
                pronto = self._ler_resposta()
                self.info = InfoLayout(
                    celula=pronto["celula"],
                    caixa=tuple(pronto["caixa"]),
                    camadas=[
                        Camada(c["indice"], c["nome"], c["fonte"], c["cor"])
                        for c in pronto["camadas"]
                    ],
                    analise=bool(pronto.get("analise")),
                )
        assert self.info is not None
        return self.info

    def renderizar(
        self,
        largura: int,
        altura: int,
        caixa: tuple[float, float, float, float] | None = None,
        ocultas: set[int] | None = None,
        fundo: str = "#000000",
        niveis: int = 99,
        extras: str = "sem",
    ) -> Imagem:
        self.iniciar()
        with self._trava:
            assert self._processo is not None and self._processo.stdin is not None
            self._contador += 1
            pedido = {
                "op": "render", "id": self._contador, "largura": max(64, int(largura)),
                "altura": max(64, int(altura)), "caixa": list(caixa) if caixa else None,
                "ocultas": sorted(ocultas or ()), "fundo": fundo, "niveis": niveis,
                "extras": extras,
            }  # fmt: skip
            self._processo.stdin.write(json.dumps(pedido) + "\n")
            self._processo.stdin.flush()
            resposta = self._ler_resposta()
        if resposta.get("op") == "erro":
            raise ErroMotor(f"O KLayout não conseguiu desenhar: {resposta.get('mensagem')}")
        arquivo = self._saida / Path(resposta["arquivo"]).name
        return Imagem(arquivo, tuple(resposta["caixa"]), resposta["largura"],
                      resposta["altura"], resposta["id"])  # fmt: skip

    def _pedir(self, pedido: dict, acao: str) -> dict:
        self.iniciar()
        with self._trava:
            assert self._processo is not None and self._processo.stdin is not None
            self._contador += 1
            self._processo.stdin.write(json.dumps({**pedido, "id": self._contador}) + "\n")
            self._processo.stdin.flush()
            resposta = self._ler_resposta()
        if resposta.get("op") == "erro":
            raise ErroMotor(f"O KLayout não conseguiu {acao}: {resposta.get('mensagem')}")
        return resposta

    def destaques(self, ativos: set[str]) -> dict[str, dict]:
        """Liga os destaques pedidos (pmos, nmos, poco_n, diodo, tap, contato); devolve, para
        cada um, título, cor e quantos o KLayout achou."""
        resposta = self._pedir({"op": "destaques", "ativos": sorted(ativos)}, "destacar")
        return resposta.get("contagem", {})

    def sondar(self, x: float, y: float, raio: float, n: int, cor: str) -> dict:
        """Ponteira n no ponto (µm): o nó elétrico ali, as camadas e os pinos ligados a ele."""
        pedido = {"op": "sondar", "x": x, "y": y, "raio": raio, "n": n, "cor": cor}
        return self._pedir(pedido, "seguir o nó")

    def remover_sonda(self, n: int) -> None:
        self._pedir({"op": "remover_sonda", "n": n}, "remover a ponteira")

    def inspecionar(self, x: float, y: float, raio: float = 0.05) -> dict:
        """Células e formas no ponto (µm), segundo o KLayout."""
        self.iniciar()
        with self._trava:
            assert self._processo is not None and self._processo.stdin is not None
            self._contador += 1
            pedido = {"op": "inspecionar", "id": self._contador, "x": x, "y": y, "raio": raio}
            self._processo.stdin.write(json.dumps(pedido) + "\n")
            self._processo.stdin.flush()
            resposta = self._ler_resposta()
        if resposta.get("op") == "erro":
            raise ErroMotor(f"O KLayout não conseguiu inspecionar: {resposta.get('mensagem')}")
        return resposta

    def encerrar(self) -> None:
        with self._trava:
            processo, self._processo = self._processo, None
        if processo is not None:
            try:
                if processo.stdin:
                    processo.stdin.write('{"op": "sair"}\n')
                    processo.stdin.flush()
                processo.wait(5)
            except (OSError, subprocess.TimeoutExpired, ValueError):
                processo.kill()
        shutil.rmtree(self._saida, ignore_errors=True)

    def __enter__(self) -> RenderizadorLayout:
        return self

    def __exit__(self, *_: object) -> None:
        self.encerrar()
