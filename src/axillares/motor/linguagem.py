"""Servidor de linguagem (Verible) dentro da imagem fixada, falado pelo protocolo LSP.

O Verible faz o trabalho de linguagem — erros de sintaxe ao digitar, formatação, definição,
referências, renomear, estrutura do arquivo. Aqui só há o transporte (JSON-RPC sobre stdin/stdout,
biblioteca padrão) e a tradução das respostas para o vocabulário do Axillares: linhas e colunas a
partir de 1, caminhos como `Path`, diagnósticos como `Local`.

O projeto é montado só para leitura **no mesmo caminho absoluto** dentro do contêiner, para as
URIs coincidirem dos dois lados. O texto em edição vai pelo protocolo (didOpen/didChange), nunca
pelo disco.

Sessão real gravada em tests/fixtures/verible/sessao-lsp.json.
"""

from __future__ import annotations

import itertools
import json
import os
import re
import subprocess
import tempfile
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote, unquote, urlparse

from axillares.ambiente import conteiner as ct
from axillares.ambiente.executor import ExecutorReal
from axillares.ambiente.perfil import Perfil, carregar_perfil
from axillares.core.modelos import Local
from axillares.motor.base import ErroMotor

# Opções do formatador: 4 espaços, como os modelos do Axillares; o resto fica no padrão do Verible.
OPCOES_FORMATO = ("--indentation_spaces=4", "--column_limit=100")
TEMPO_INICIAL_S = 30.0
_CONTADOR = itertools.count(1)

# SymbolKind do LSP → palavra em português. O Verible usa 6 (method) para módulo.
TIPOS_SIMBOLO = {
    2: "módulo", 3: "pacote", 5: "classe", 6: "módulo", 9: "construtor", 10: "enum",
    11: "interface", 12: "função", 13: "sinal", 14: "constante", 22: "valor do enum",
    23: "struct", 26: "tipo",
}  # fmt: skip


# --- tradução --------------------------------------------------------------------------------


def uri_de(caminho: Path) -> str:
    return "file://" + quote(str(caminho))


def caminho_de(uri: str) -> Path:
    return Path(unquote(urlparse(uri).path))


@dataclass(frozen=True)
class Faixa:
    """Trecho do texto. Linhas e colunas começam em 1 (como no editor); a coluna final é
    exclusiva."""

    linha: int
    coluna: int
    linha_fim: int
    coluna_fim: int

    @classmethod
    def do_lsp(cls, r: dict) -> Faixa:
        return cls(
            r["start"]["line"] + 1,
            r["start"]["character"] + 1,
            r["end"]["line"] + 1,
            r["end"]["character"] + 1,
        )

    def para_lsp(self) -> dict:
        return {
            "start": {"line": self.linha - 1, "character": self.coluna - 1},
            "end": {"line": self.linha_fim - 1, "character": self.coluna_fim - 1},
        }

    def como_dict(self) -> dict:
        return {"linha": self.linha, "coluna": self.coluna,
                "linha_fim": self.linha_fim, "coluna_fim": self.coluna_fim}  # fmt: skip


@dataclass(frozen=True)
class Edicao:
    faixa: Faixa
    texto: str

    def como_dict(self) -> dict:
        return {**self.faixa.como_dict(), "texto": self.texto}


@dataclass(frozen=True)
class Lugar:
    caminho: Path
    faixa: Faixa


@dataclass(frozen=True)
class Simbolo:
    nome: str
    tipo: str
    faixa: Faixa
    filhos: list[Simbolo] = field(default_factory=list)
    codigo: int = 13
    """SymbolKind do LSP (o editor escolhe o ícone por ele)."""

    def como_dict(self) -> dict:
        return {"nome": self.nome, "tipo": self.tipo, "codigo": self.codigo,
                **self.faixa.como_dict(),
                "filhos": [f.como_dict() for f in self.filhos]}  # fmt: skip


def diagnosticos(params: dict, raiz: Path) -> tuple[Path, list[Local]]:
    """publishDiagnostics → (arquivo, problemas). Regras de estilo do Verible vêm explicadas em
    português; as que só valem para SystemVerilog são descartadas em arquivos .v."""
    caminho = caminho_de(params["uri"])
    try:
        relativo = caminho.relative_to(raiz).as_posix()
    except ValueError:
        relativo = caminho.name
    verilog_classico = caminho.suffix.lower() in {".v", ".vh"}
    locais = []
    for d in params.get("diagnostics", []):
        inicio = d["range"]["start"]
        texto = d.get("message", "").strip()
        achado = _REGRA.search(texto)
        regra = achado["regra"] if achado else ""
        if regra and verilog_classico and regra in SO_SYSTEMVERILOG:
            continue
        locais.append(
            Local(
                arquivo=relativo,
                linha=inicio["line"] + 1,
                coluna=inicio["character"] + 1,
                mensagem=_explicar_regra(regra, texto) if regra else _traduzir_mensagem(texto),
                gravidade="erro" if d.get("severity", 1) == 1 else "aviso",
                origem="verible" + (f" · {regra}" if regra else ""),
            )
        )
    return caminho, locais


# "Texto da regra. [Style: constants] [explicit-parameter-storage-type]" — o último [] é o id.
_REGRA = re.compile(r"\[(?P<regra>[a-z0-9]+(?:-[a-z0-9]+)+)\]\s*$")
_ETIQUETAS = re.compile(r"\s*\[[^\]]*\]")
# Conselhos de SystemVerilog que não cabem em Verilog-2001 (always_comb, parameter int…).
SO_SYSTEMVERILOG = frozenset({
    "always-comb", "explicit-parameter-storage-type", "explicit-function-lifetime",
    "explicit-task-lifetime", "typedef-enums", "typedef-structs-unions",
})  # fmt: skip


def _explicar_regra(regra: str, texto: str) -> str:
    from axillares.core.explicacoes import regra_do_verible

    explicacao = regra_do_verible(regra)
    original = _ETIQUETAS.sub("", texto).strip()
    if explicacao is None:
        return original
    return f"{explicacao.o_que} {explicacao.fazer}"


def _traduzir_mensagem(texto: str) -> str:
    # o Verible diz "syntax error at \";\"" — o caso mais comum para quem está começando
    if texto.startswith("syntax error at "):
        return f"Erro de sintaxe perto de {texto.removeprefix('syntax error at ')}."
    if texto.startswith("syntax error"):
        return "Erro de sintaxe" + texto.removeprefix("syntax error") + "."
    return texto


def edicoes(resultado: list | None) -> list[Edicao]:
    return [Edicao(Faixa.do_lsp(e["range"]), e["newText"]) for e in (resultado or [])]


def lugares(resultado: list | dict | None) -> list[Lugar]:
    if not resultado:
        return []
    itens = resultado if isinstance(resultado, list) else [resultado]
    saida = []
    for x in itens:
        uri = x.get("uri") or x.get("targetUri")
        faixa = x.get("range") or x.get("targetSelectionRange")
        if uri and faixa:
            saida.append(Lugar(caminho_de(uri), Faixa.do_lsp(faixa)))
    return saida


def edicoes_de_espaco(resultado: dict | None) -> dict[Path, list[Edicao]]:
    """WorkspaceEdit → edições por arquivo."""
    if not resultado:
        return {}
    por_arquivo: dict[Path, list[Edicao]] = {}
    for uri, lista in (resultado.get("changes") or {}).items():
        por_arquivo[caminho_de(uri)] = edicoes(lista)
    for doc in resultado.get("documentChanges") or []:
        if "textDocument" in doc:
            por_arquivo[caminho_de(doc["textDocument"]["uri"])] = edicoes(doc.get("edits"))
    return por_arquivo


def simbolos(resultado: list | None) -> list[Simbolo]:
    def um(s: dict) -> Simbolo:
        faixa = s.get("selectionRange") or s.get("range") or s["location"]["range"]
        return Simbolo(
            nome=s["name"],
            tipo=TIPOS_SIMBOLO.get(s.get("kind", 0), "símbolo"),
            faixa=Faixa.do_lsp(faixa),
            filhos=[um(f) for f in s.get("children") or []],
            codigo=int(s.get("kind", 13)),
        )

    return [um(s) for s in resultado or []]


def dica(resultado: dict | None) -> str:
    if not resultado:
        return ""
    conteudo = resultado.get("contents")
    if isinstance(conteudo, dict):
        texto = conteudo.get("value", "")
    elif isinstance(conteudo, list):
        texto = "\n\n".join(c if isinstance(c, str) else c.get("value", "") for c in conteudo)
    else:
        texto = conteudo or ""
    for original, traducao in _DICAS:
        texto = texto.replace(original, traducao)
    return texto


# O Verible responde em inglês; os termos da dica viram português.
_DICAS = (
    ("data/net/var/instance", "sinal"),
    ("Type: ", "Tipo: "),
    ("Value: ", "Valor: "),
)


# --- transporte ------------------------------------------------------------------------------


class ClienteLinguagem:
    """Um servidor Verible por projeto. Seguro entre threads: quem chama não espera resposta —
    `pedir` devolve pelo `ao_responder`, chamado na thread de leitura."""

    def __init__(
        self,
        raiz: Path,
        arquivos: list[Path],
        perfil: Perfil | None = None,
        programa: ct.ProgramaConteiner | None = None,
        ao_notificar: Callable[[str, dict], None] = lambda _m, _p: None,
        ao_terminar: Callable[[str], None] = lambda _motivo: None,
    ) -> None:
        self.raiz = raiz.resolve()
        self.arquivos = [a.resolve() for a in arquivos]
        self.perfil = perfil or carregar_perfil()
        self._programa = programa
        self.ao_notificar = ao_notificar
        self.ao_terminar = ao_terminar
        self._processo: subprocess.Popen[bytes] | None = None
        self._escrita = threading.Lock()
        self._pendentes: dict[int, Callable[[object, str | None], None]] = {}
        self._ids = itertools.count(1)
        self._nome = f"axil-ls-{os.getpid()}-{next(_CONTADOR)}"
        self._pasta = Path(tempfile.mkdtemp(prefix="axil-ls-"))
        self._encerrando = False
        self.versoes: dict[Path, int] = {}

    @property
    def vivo(self) -> bool:
        return self._processo is not None and self._processo.poll() is None

    def _lista(self) -> Path:
        lista = self._pasta / "verible.filelist"
        lista.write_text("".join(f"{a}\n" for a in self.arquivos), encoding="utf-8")
        return lista

    def comando(self) -> list[str]:
        prog = self._programa or ct.detectar_programa(ExecutorReal())
        if prog is None:
            raise ErroMotor(
                "Nem podman nem docker estão instalados; veja “axil ambiente situacao”."
            )
        self._programa = prog
        usuario = (
            ["--userns=keep-id"] if prog.nome == "podman"
            else ["--user", f"{os.getuid()}:{os.getgid()}"]
        )  # fmt: skip
        servidor = self.perfil.editor.get("verible_ls", "verible-verilog-ls")
        lista = self._lista()
        return [
            prog.nome, "run", "-i", "--rm", "--init", "--network=none", "--name", self._nome,
            *usuario,
            "-v", f"{self.raiz}:{self.raiz}:ro,z",
            "-v", f"{self._pasta}:{self._pasta}:ro,z",
            "-w", str(self.raiz), "-e", "HOME=/tmp",
            "--entrypoint", servidor, self.perfil.imagem.referencia,
            "--rules_config_search", f"--file_list_path={lista}", *OPCOES_FORMATO,
        ]  # fmt: skip

    def iniciar(self, tempo: float = TEMPO_INICIAL_S) -> dict:
        """Sobe o servidor e faz o aperto de mão; devolve as capacidades anunciadas."""
        self._processo = subprocess.Popen(
            self.comando(), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )  # fmt: skip
        threading.Thread(target=self._ler, name=self._nome, daemon=True).start()
        resposta = self.pedir_e_esperar(
            "initialize",
            {"processId": os.getpid(), "rootUri": uri_de(self.raiz), "capabilities": {}},
            tempo,
        )
        self.notificar("initialized", {})
        return (resposta or {}).get("capabilities", {})

    def _enviar(self, mensagem: dict) -> None:
        if not self.vivo:
            raise ErroMotor("O servidor de linguagem não está rodando.")
        corpo = json.dumps(mensagem, ensure_ascii=False).encode("utf-8")
        assert self._processo is not None and self._processo.stdin is not None
        with self._escrita:
            self._processo.stdin.write(b"Content-Length: %d\r\n\r\n" % len(corpo) + corpo)
            self._processo.stdin.flush()

    def _ler(self) -> None:
        assert self._processo is not None and self._processo.stdout is not None
        saida = self._processo.stdout
        try:
            while True:
                tamanho = 0
                while True:
                    linha = saida.readline()
                    if not linha:
                        raise EOFError
                    if linha in (b"\r\n", b"\n"):
                        break
                    nome, _, valor = linha.decode("ascii", "replace").partition(":")
                    if nome.strip().lower() == "content-length":
                        tamanho = int(valor)
                mensagem = json.loads(saida.read(tamanho))
                self._despachar(mensagem)
        except (EOFError, OSError, ValueError):
            pass
        finally:
            for ao_responder in self._pendentes.values():
                ao_responder(None, "O servidor de linguagem encerrou.")
            self._pendentes.clear()
            if not self._encerrando:
                self.ao_terminar("O servidor de linguagem (Verible) encerrou sozinho.")

    def _despachar(self, mensagem: dict) -> None:
        if "id" in mensagem and "method" not in mensagem:
            ao_responder = self._pendentes.pop(mensagem["id"], None)
            if ao_responder is not None:
                erro = mensagem.get("error")
                ao_responder(mensagem.get("result"), erro.get("message") if erro else None)
        elif "method" in mensagem and "id" in mensagem:
            # pedido do servidor (configuração, progresso): responder vazio para não travá-lo
            self._enviar({"jsonrpc": "2.0", "id": mensagem["id"], "result": None})
        elif "method" in mensagem:
            self.ao_notificar(mensagem["method"], mensagem.get("params") or {})

    def notificar(self, metodo: str, params: dict) -> None:
        self._enviar({"jsonrpc": "2.0", "method": metodo, "params": params})

    def pedir(
        self, metodo: str, params: dict | None, ao_responder: Callable[[object, str | None], None]
    ) -> None:
        ident = next(self._ids)
        self._pendentes[ident] = ao_responder
        try:
            self._enviar({"jsonrpc": "2.0", "id": ident, "method": metodo, "params": params})
        except ErroMotor as erro:
            self._pendentes.pop(ident, None)
            ao_responder(None, str(erro))

    def pedir_e_esperar(self, metodo: str, params: dict | None, tempo: float = 5.0) -> object:
        pronto = threading.Event()
        caixa: list = [None, None]

        def guardar(resultado: object, erro: str | None) -> None:
            caixa[0], caixa[1] = resultado, erro
            pronto.set()

        self.pedir(metodo, params, guardar)
        if not pronto.wait(tempo):
            raise ErroMotor(f"O servidor de linguagem não respondeu a {metodo} em {tempo:g} s.")
        if caixa[1]:
            raise ErroMotor(f"O servidor de linguagem recusou {metodo}: {caixa[1]}")
        return caixa[0]

    # --- documentos ----------------------------------------------------------------------------

    def abrir(self, caminho: Path, texto: str) -> None:
        self.versoes[caminho] = 1
        documento_ = {"uri": uri_de(caminho), "languageId": "systemverilog", "version": 1}
        self.notificar("textDocument/didOpen", {"textDocument": {**documento_, "text": texto}})

    def mudar(self, caminho: Path, texto: str) -> None:
        if caminho not in self.versoes:
            self.abrir(caminho, texto)
            return
        self.versoes[caminho] += 1
        self.notificar("textDocument/didChange", {
            "textDocument": {"uri": uri_de(caminho), "version": self.versoes[caminho]},
            "contentChanges": [{"text": texto}]})  # fmt: skip

    def fechar(self, caminho: Path) -> None:
        if self.versoes.pop(caminho, None) is not None:
            self.notificar("textDocument/didClose", {"textDocument": {"uri": uri_de(caminho)}})

    # --- encerrar ----------------------------------------------------------------------------

    def encerrar(self) -> None:
        self._encerrando = True
        processo, self._processo = self._processo, None
        if processo is not None and processo.poll() is None:
            self._processo = processo
            try:
                self.pedir_e_esperar("shutdown", None, 2.0)
                self.notificar("exit", {})
            except (ErroMotor, OSError):
                pass
            self._processo = None
            try:
                processo.wait(3)
            except subprocess.TimeoutExpired:
                processo.kill()
                if self._programa is not None:
                    subprocess.run([self._programa.nome, "rm", "-f", self._nome],
                                   capture_output=True, timeout=20, check=False)  # fmt: skip
        for arquivo in self._pasta.glob("*"):
            arquivo.unlink(missing_ok=True)
        self._pasta.rmdir() if self._pasta.exists() else None


# Parâmetros prontos para os pedidos mais comuns.


def em(caminho: Path, linha: int, coluna: int) -> dict:
    return {"textDocument": {"uri": uri_de(caminho)},
            "position": {"line": linha - 1, "character": coluna - 1}}  # fmt: skip


def documento(caminho: Path) -> dict:
    return {"textDocument": {"uri": uri_de(caminho)}}
