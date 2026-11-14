"""Diagnósticos: toda falha vira "o que aconteceu, por que importa, o que fazer agora".

Regra de produto: quem está começando nunca é abandonado diante de um log bruto.
O log continua disponível em `detalhe`, mas nunca é a primeira coisa mostrada.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

LINHAS_DE_DETALHE = 6


class Gravidade(StrEnum):
    BLOQUEANTE = "bloqueante"
    """Impede o fluxo de rodar."""
    AVISO = "aviso"
    """O fluxo roda, mas algo vai faltar ou pode divergir."""


@dataclass(frozen=True)
class Diagnostico:
    codigo: str
    o_que: str
    por_que: str
    proximo_passo: str
    gravidade: Gravidade = Gravidade.BLOQUEANTE
    detalhe: str = ""

    @property
    def bloqueante(self) -> bool:
        return self.gravidade is Gravidade.BLOQUEANTE


def resumir_log(saida: str, linhas: int = LINHAS_DE_DETALHE) -> str:
    """Últimas linhas não vazias, que é onde as ferramentas costumam dizer o erro."""
    uteis = [linha for linha in saida.splitlines() if linha.strip()]
    return "\n".join(uteis[-linhas:])


# --- Distribuição Linux ----------------------------------------------------------------------

_GERENCIADORES = {
    "fedora": "sudo dnf install {pacote}",
    "rhel": "sudo dnf install {pacote}",
    "debian": "sudo apt install {pacote}",
    "ubuntu": "sudo apt install {pacote}",
    "arch": "sudo pacman -S {pacote}",
    "opensuse": "sudo zypper install {pacote}",
    "suse": "sudo zypper install {pacote}",
}


def familia_da_distribuicao(os_release: Path = Path("/etc/os-release")) -> str | None:
    try:
        texto = os_release.read_text(encoding="utf-8")
    except OSError:
        return None
    campos: dict[str, str] = {}
    for linha in texto.splitlines():
        chave, _, valor = linha.partition("=")
        campos[chave.strip()] = valor.strip().strip('"')
    candidatos = [campos.get("ID", ""), *campos.get("ID_LIKE", "").split()]
    for candidato in candidatos:
        for familia in _GERENCIADORES:
            if candidato.startswith(familia):
                return familia
    return None


def comando_de_instalacao(pacote: str, os_release: Path = Path("/etc/os-release")) -> str:
    familia = familia_da_distribuicao(os_release)
    if familia is None:
        return f"instale o pacote “{pacote}” pelo gerenciador de pacotes da sua distribuição"
    return _GERENCIADORES[familia].format(pacote=pacote)


# --- Catálogo -------------------------------------------------------------------------------


def sem_conteiner(os_release: Path = Path("/etc/os-release")) -> Diagnostico:
    return Diagnostico(
        codigo="sem-conteiner",
        o_que="Nem podman nem docker estão instalados.",
        por_que=(
            "As ferramentas de EDA chegam numa imagem de contêiner fixada; sem um programa de "
            "contêiner não há como baixá-las nem executá-las."
        ),
        proximo_passo=(
            f"Instale o podman ({comando_de_instalacao('podman', os_release)}) e depois rode "
            "“axil ambiente instalar”. O podman não exige serviço em segundo plano nem root."
        ),
    )


def conteiner_sem_permissao(programa: str, saida: str) -> Diagnostico:
    if programa == "docker":
        passo = (
            "Acrescente seu usuário ao grupo docker (sudo usermod -aG docker $USER), saia da "
            "sessão e entre de novo — ou instale o podman, que não precisa disso."
        )
    else:
        passo = (
            "Rode “podman system migrate” e tente de novo. Se persistir, confira se seu usuário "
            "tem faixas em /etc/subuid e /etc/subgid (sudo usermod --add-subuids 100000-165535 "
            "--add-subgids 100000-165535 $USER)."
        )
    return Diagnostico(
        codigo="conteiner-sem-permissao",
        o_que=f"O {programa} está instalado, mas recusou a operação por falta de permissão.",
        por_que="Sem permissão o Axillares não consegue consultar, baixar nem rodar a imagem.",
        proximo_passo=passo,
        detalhe=resumir_log(saida),
    )


def conteiner_falhou(programa: str, acao: str, saida: str) -> Diagnostico:
    return Diagnostico(
        codigo="conteiner-falhou",
        o_que=f"O {programa} falhou ao {acao}.",
        por_que="Sem essa operação o Axillares não consegue confirmar o estado das ferramentas.",
        proximo_passo=(
            f"Rode “{programa} info” num terminal: se ele também falhar, o problema está na "
            f"instalação do {programa}, não no Axillares. As últimas linhas do erro estão abaixo."
        ),
        detalhe=resumir_log(saida),
    )


def imagem_ausente(referencia: str, tamanho_gb: float) -> Diagnostico:
    return Diagnostico(
        codigo="imagem-ausente",
        o_que="A imagem de ferramentas ainda não foi baixada.",
        por_que=(
            "Ela contém yosys, openroad, magic e as demais ferramentas; sem ela nenhuma etapa do "
            "fluxo roda."
        ),
        proximo_passo=(
            f"Rode “axil ambiente instalar”. É um download único de cerca de {tamanho_gb:.0f} GB, "
            "que pode ser retomado se a conexão cair."
        ),
        detalhe=referencia,
    )


def sem_rede(saida: str) -> Diagnostico:
    return Diagnostico(
        codigo="sem-rede",
        o_que="Não foi possível falar com o registro de imagens.",
        por_que="O download da imagem precisa de internet (só desta vez).",
        proximo_passo=(
            "Confira a conexão e rode “axil ambiente instalar” de novo — as camadas já baixadas "
            "não são baixadas outra vez. Atrás de proxy, configure HTTPS_PROXY antes."
        ),
        detalhe=resumir_log(saida),
    )


def digest_inexistente(referencia: str, saida: str) -> Diagnostico:
    return Diagnostico(
        codigo="digest-inexistente",
        o_que="O registro não tem a imagem com o digest fixado no perfil.",
        por_que=(
            "O Axillares só usa a versão exata declarada no perfil; outra versão poderia mudar "
            "resultados sem aviso."
        ),
        proximo_passo=(
            "Atualize o Axillares (o perfil pode ter sido renovado) ou escolha outro perfil com "
            "“--perfil”. Não troque o digest à mão sem verificar as versões das ferramentas."
        ),
        detalhe=resumir_log(saida) or referencia,
    )


def digest_divergente(esperado: str, encontrados: list[str]) -> Diagnostico:
    return Diagnostico(
        codigo="digest-divergente",
        o_que="A imagem baixada não corresponde ao digest do perfil.",
        por_que="Sem essa garantia não dá para afirmar quais versões de ferramenta estão em uso.",
        proximo_passo=(
            "Apague a imagem (podman rmi <imagem>) e rode “axil ambiente instalar” de novo."
        ),
        detalhe=f"esperado {esperado}\nencontrado: {', '.join(encontrados) or 'nenhum'}",
    )


def ferramenta_ausente_na_imagem(nome: str, saida: str) -> Diagnostico:
    return Diagnostico(
        codigo="ferramenta-ausente-na-imagem",
        o_que=f"{nome} não foi encontrado dentro da imagem.",
        por_que="O perfil promete essa ferramenta; sem ela a etapa correspondente não roda.",
        proximo_passo=(
            "O perfil e a imagem não combinam. Rode “axil ambiente instalar” para baixar a imagem "
            "correta; se persistir, relate o problema com a saída de “axil ambiente situacao”."
        ),
        detalhe=resumir_log(saida),
    )


def ferramenta_nativa_ausente(
    nome: str,
    descricao: str,
    pacote: str | None,
    instrucao: str | None,
    os_release: Path = Path("/etc/os-release"),
    flatpak: str | None = None,
    tem_flatpak: bool = True,
) -> Diagnostico:
    if flatpak:
        passo = f"Instale pelo Flathub, sem sudo: flatpak install --user flathub {flatpak}"
        if not tem_flatpak:
            passo = (
                f"Instale o Flatpak ({comando_de_instalacao('flatpak', os_release)}), "
                f"adicione o Flathub e depois: flatpak install --user flathub {flatpak}"
            )
    elif instrucao:
        passo = instrucao
    elif pacote:
        passo = f"Instale com: {comando_de_instalacao(pacote, os_release)}"
    else:
        passo = f"Instale o {nome} pela loja de aplicativos da sua distribuição."
    return Diagnostico(
        codigo="ferramenta-nativa-ausente",
        o_que=f"O {nome} ({descricao}) não está instalado nesta máquina.",
        por_que=(
            "Ele não é necessário para rodar o fluxo, mas sem ele o Axillares não abre o "
            "resultado com um clique."
        ),
        proximo_passo=passo,
        gravidade=Gravidade.AVISO,
    )


def versao_divergente(
    nome: str, encontrada: str, esperada: str, minima: bool, essencial: bool
) -> Diagnostico:
    if minima:
        o_que = f"O {nome} está na versão {encontrada}, mais antiga que a mínima ({esperada})."
        passo = f"Atualize o {nome} pelo gerenciador de pacotes."
    else:
        o_que = f"O {nome} está na versão {encontrada}, mas o perfil espera {esperada}."
        passo = (
            "Rode “axil ambiente instalar” para obter a imagem fixada no perfil. Resultados com "
            "outra versão podem não ser comparáveis com os de outras pessoas."
        )
    return Diagnostico(
        codigo="versao-divergente",
        o_que=o_que,
        por_que="Versões diferentes produzem métricas e até erros diferentes para o mesmo projeto.",
        proximo_passo=passo,
        gravidade=Gravidade.BLOQUEANTE if essencial else Gravidade.AVISO,
    )


def versao_ilegivel(nome: str, saida: str) -> Diagnostico:
    return Diagnostico(
        codigo="versao-ilegivel",
        o_que=f"O {nome} respondeu, mas não foi possível ler a versão na resposta.",
        por_que="Sem a versão não dá para garantir que é a ferramenta que o perfil espera.",
        proximo_passo=(
            f"Rode o {nome} num terminal para conferir se ele funciona; se funcionar, relate o "
            "problema anexando a saída abaixo."
        ),
        detalhe=resumir_log(saida),
    )
