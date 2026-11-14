"""Projeto do usuário, descrito em `axil.toml`.

Exemplo mínimo:

    [projeto]
    nome = "contador"
    topo = "contador"

    [fontes]
    rtl = ["rtl/**/*.v"]

    [asic]
    pdk = "skywater130"
    frequencia_mhz = 100
"""

from __future__ import annotations

import hashlib
import tomllib
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from axillares.core.modelos import Etapa

ARQUIVO = "axil.toml"


class Pdk(StrEnum):
    SKYWATER130 = "skywater130"
    GF180 = "gf180"
    IHP130 = "ihp130"


BIBLIOTECAS_PADRAO = {
    Pdk.SKYWATER130: "sky130hd",
    Pdk.GF180: "gf180mcu_fd_sc_mcu9t5v0",
    Pdk.IHP130: "sg13g2_stdcell",
}


class _Secao(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SecaoProjeto(_Secao):
    nome: str = Field(min_length=1, pattern=r"^[A-Za-z_][A-Za-z0-9_\-]*$")
    topo: str = Field(min_length=1, pattern=r"^[A-Za-z_][A-Za-z0-9_$]*$")
    descricao: str = ""


class SecaoFontes(_Secao):
    rtl: list[str] = Field(min_length=1, description="Padrões glob relativos ao axil.toml.")
    testbenches: list[str] = Field(default_factory=list)
    sdc: str | None = Field(default=None, description="Restrições; sem SDC, gera-se um relógio.")


class SecaoAsic(_Secao):
    pdk: Pdk = Pdk.SKYWATER130
    biblioteca: str | None = None
    frequencia_mhz: float = Field(default=100.0, gt=0, le=5000)
    relogio: str = Field(default="clk", description="Porta de relógio do módulo de topo.")
    chip_um: tuple[float, float] | None = Field(
        default=None,
        description="Tamanho fixo do chip (largura, altura) em µm. Sem ele, o motor decide pela "
        "densidade — o que deixa circuitos minúsculos pequenos demais para a malha de "
        "alimentação.",
    )

    @field_validator("chip_um")
    @classmethod
    def _chip_razoavel(cls, valor: tuple[float, float] | None) -> tuple[float, float] | None:
        if valor is not None and not all(10 <= v <= 20000 for v in valor):
            raise ValueError("cada lado do chip precisa estar entre 10 e 20000 µm")
        return valor

    @property
    def biblioteca_efetiva(self) -> str:
        return self.biblioteca or BIBLIOTECAS_PADRAO[self.pdk]

    @property
    def periodo_ns(self) -> float:
        return 1000.0 / self.frequencia_mhz


class SecaoFpga(_Secao):
    placa: str | None = Field(default=None, description="Placa alvo (templates/placas/<id>.toml).")
    pinos: dict[str, dict[str, str]] = Field(
        default_factory=dict,
        description="Por placa: porta do módulo de topo → recurso da placa (clk, btn0, led3…).",
    )


class SecaoMotores(_Secao):
    sintese: str = "siliconcompiler"
    gds: str = "siliconcompiler"
    fpga: str = "edalize"

    def para(self, etapa: Etapa) -> str:
        return getattr(self, etapa.value)


class Projeto(_Secao):
    projeto: SecaoProjeto
    fontes: SecaoFontes
    asic: SecaoAsic = Field(default_factory=SecaoAsic)
    fpga: SecaoFpga = Field(default_factory=SecaoFpga)
    motores: SecaoMotores = Field(default_factory=SecaoMotores)

    raiz: Path = Field(default=Path("."), exclude=True)

    @field_validator("raiz")
    @classmethod
    def _absoluta(cls, valor: Path) -> Path:
        return valor.resolve()

    # --- caminhos ---------------------------------------------------------------------------

    @property
    def nome(self) -> str:
        return self.projeto.nome

    @property
    def dir_runs(self) -> Path:
        return self.raiz / "runs"

    def _expandir(self, padroes: list[str]) -> list[Path]:
        achados: dict[Path, None] = {}
        for padrao in padroes:
            for caminho in sorted(self.raiz.glob(padrao)):
                if caminho.is_file():
                    achados[caminho.resolve()] = None
        return list(achados)

    def arquivos_rtl(self) -> list[Path]:
        return self._expandir(self.fontes.rtl)

    def arquivos_testbench(self) -> list[Path]:
        return self._expandir(self.fontes.testbenches)

    def arquivo_sdc(self) -> Path | None:
        return (self.raiz / self.fontes.sdc).resolve() if self.fontes.sdc else None

    def relativo(self, caminho: Path) -> str:
        return caminho.resolve().relative_to(self.raiz).as_posix()

    def hash_rtl(self) -> str:
        """Hash das fontes RTL (nome relativo + conteúdo). Mesma RTL → mesmo hash."""
        h = hashlib.sha256()
        for arquivo in self.arquivos_rtl():
            h.update(self.relativo(arquivo).encode())
            h.update(b"\0")
            h.update(arquivo.read_bytes())
            h.update(b"\0")
        return h.hexdigest()


class ErroProjeto(Exception):
    """Projeto ausente ou inválido. A mensagem já está pronta para o usuário."""


def encontrar_raiz(inicio: Path | None = None) -> Path:
    """Sobe a partir de `inicio` até achar um axil.toml."""
    atual = (inicio or Path.cwd()).resolve()
    for pasta in (atual, *atual.parents):
        if (pasta / ARQUIVO).is_file():
            return pasta
    raise ErroProjeto(
        f"Nenhum {ARQUIVO} encontrado em {atual} nem nas pastas acima. Entre na pasta do projeto "
        "ou crie um com “axil novo <nome>”."
    )


_ROTULOS = {
    "projeto.nome": "o nome do projeto",
    "projeto.topo": "o módulo de topo",
    "fontes.rtl": "a lista de fontes RTL",
    "asic.pdk": "o PDK",
    "asic.frequencia_mhz": "a frequência alvo",
    "asic.chip_um": "o tamanho do chip",
}


def carregar_projeto(caminho: Path | None = None) -> Projeto:
    """Lê e valida o axil.toml. `caminho` pode ser a pasta ou o próprio arquivo."""
    if caminho is None:
        raiz = encontrar_raiz()
    elif caminho.is_dir():
        raiz = caminho
    else:
        raiz = caminho.parent
    arquivo = raiz / ARQUIVO
    if not arquivo.is_file():
        raise ErroProjeto(f"Não existe {ARQUIVO} em {raiz}.")
    try:
        dados = tomllib.loads(arquivo.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as erro:
        raise ErroProjeto(f"O {ARQUIVO} não é TOML válido: {erro}.") from erro
    try:
        projeto = Projeto.model_validate({**dados, "raiz": raiz})
    except ValidationError as erro:
        problemas = []
        for e in erro.errors():
            campo = ".".join(str(p) for p in e["loc"])
            problemas.append(f"{campo} ({_ROTULOS.get(campo, 'campo')}): {_traduzir(e)}")
        raise ErroProjeto(f"O {ARQUIVO} tem problemas — " + "; ".join(problemas) + ".") from erro
    if not projeto.arquivos_rtl():
        raise ErroProjeto(
            f"Nenhum arquivo RTL casa com {projeto.fontes.rtl} a partir de {raiz}. Confira o "
            "campo fontes.rtl do axil.toml."
        )
    sdc = projeto.arquivo_sdc()
    if sdc is not None and not sdc.is_file():
        raise ErroProjeto(f"O arquivo de restrições {projeto.fontes.sdc} não existe.")
    return projeto


def _traduzir(e: dict) -> str:
    tipo = e.get("type", "")
    if tipo == "missing":
        return "é obrigatório e está faltando"
    if tipo == "extra_forbidden":
        return "não é um campo conhecido (erro de digitação?)"
    if tipo == "enum":
        return f"precisa ser um destes: {e.get('ctx', {}).get('expected', '')}"
    if tipo == "string_pattern_mismatch":
        return "só pode ter letras, números e _ (começando por letra)"
    if tipo in {"greater_than", "less_than_equal"}:
        return f"valor fora da faixa ({e.get('msg', '')})"
    return e.get("msg", "valor inválido")


def definir_placa(raiz: Path, placa: str) -> None:
    """Troca a placa em [fpga] do axil.toml, preservando o resto do arquivo (e os comentários)."""
    import re
    import tempfile

    from axillares.core.placas import ErroPlaca, carregar

    try:
        carregar(placa)
    except ErroPlaca as erro:
        raise ErroProjeto(str(erro)) from erro
    arquivo = Path(raiz) / ARQUIVO
    texto = arquivo.read_text(encoding="utf-8")
    secao = re.search(r"^\[fpga\]\s*$", texto, flags=re.MULTILINE)
    linha_nova = f'placa = "{placa}"'
    if secao is None:
        texto = texto.rstrip("\n") + f"\n\n[fpga]\n{linha_nova}\n"
    else:
        fim = re.search(r"^\[", texto[secao.end() :], flags=re.MULTILINE)
        corpo_fim = secao.end() + (fim.start() if fim else len(texto) - secao.end())
        corpo = texto[secao.end() : corpo_fim]
        if re.search(r"^placa\s*=", corpo, flags=re.MULTILINE):
            corpo = re.sub(r'^placa\s*=\s*"[^"]*"', linha_nova, corpo, count=1, flags=re.MULTILINE)
        else:
            corpo = "\n" + linha_nova + corpo
        texto = texto[: secao.end()] + corpo + texto[corpo_fim:]
    fd, temporario = tempfile.mkstemp(prefix=".axil.", dir=arquivo.parent)
    with open(fd, "w", encoding="utf-8") as saida:
        saida.write(texto)
    Path(temporario).replace(arquivo)
