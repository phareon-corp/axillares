"""Caderno de execuções: um diretório imutável por execução e um índice SQLite.

    runs/
      indice.sqlite                                 índice (reconstruível a partir dos diretórios)
      .andamento/<id>/                              execução em curso (some ao terminar)
      20261113-230455-gds-a1b2c3d/                  execução concluída — somente leitura
        meta.json      motor e versão, comando, hash do RTL, início, duração, situação, falha
        log.txt        log completo transmitido pelo motor
        metricas.json  métricas já no vocabulário de Axillares
        saida/         artefatos (GDS, netlist, …) e saida/motor/ com o manifesto do motor

O índice guarda métricas em chave-valor, para não migrar esquema a cada métrica nova.
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import stat
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from axillares import __version__
from axillares.core.modelos import Artefato, Etapa, Falha, Metrica, Situacao
from axillares.core.projeto import Projeto

ANDAMENTO = ".andamento"
INDICE = "indice.sqlite"
VERSAO_INDICE = 1


class RegistroExecucao(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    numero: int = 0
    """Número curto e sequencial, só do índice (não vai para o meta.json)."""
    projeto: str
    etapa: Etapa
    motor: str
    versao_motor: str
    comando: list[str] = Field(default_factory=list)
    hash_rtl: str
    inicio: datetime
    duracao_s: float = 0.0
    situacao: Situacao
    falha: Falha | None = None
    axillares: str = __version__
    metricas: list[Metrica] = Field(default_factory=list, exclude=True)
    artefatos: list[Artefato] = Field(default_factory=list)
    diretorio: Path | None = Field(default=None, exclude=True)

    @property
    def hash_curto(self) -> str:
        return self.hash_rtl[:7]

    def metrica(self, chave: str) -> Metrica | None:
        return next((m for m in self.metricas if m.chave == chave), None)


@dataclass
class Andamento:
    """Uma execução em curso, antes de virar registro imutável."""

    id: str
    projeto: Projeto
    etapa: Etapa
    motor: str
    versao_motor: str
    hash_rtl: str
    inicio: datetime
    diretorio: Path

    @property
    def dir_trabalho(self) -> Path:
        return self.diretorio / "trabalho"

    @property
    def dir_saida(self) -> Path:
        return self.diretorio / "saida"

    @property
    def arquivo_log(self) -> Path:
        return self.diretorio / "log.txt"


class ErroCaderno(Exception):
    """Execução não encontrada ou referência ambígua. Mensagem pronta para o usuário."""


class Caderno:
    def __init__(self, dir_runs: Path) -> None:
        self.dir = dir_runs

    # --- ciclo de vida ----------------------------------------------------------------------

    def iniciar(self, projeto: Projeto, etapa: Etapa, motor: str, versao_motor: str) -> Andamento:
        inicio = datetime.now().astimezone()
        hash_rtl = projeto.hash_rtl()
        base = f"{inicio:%Y%m%d-%H%M%S}-{etapa.value}-{hash_rtl[:7]}"
        ident, n = base, 2
        while (self.dir / ident).exists() or (self.dir / ANDAMENTO / ident).exists():
            ident, n = f"{base}-{n}", n + 1
        diretorio = self.dir / ANDAMENTO / ident
        (diretorio / "trabalho").mkdir(parents=True)
        (diretorio / "saida").mkdir()
        (diretorio / "log.txt").touch()
        andamento = Andamento(
            ident, projeto, etapa, motor, versao_motor, hash_rtl, inicio, diretorio
        )
        _escrever_json(
            diretorio / "andamento.json",
            {"id": ident, "etapa": etapa.value, "motor": motor, "versao_motor": versao_motor,
             "hash_rtl": hash_rtl, "inicio": inicio.isoformat(), "pid": os.getpid()},
        )  # fmt: skip
        return andamento

    def finalizar(
        self,
        andamento: Andamento,
        situacao: Situacao,
        comando: list[str],
        metricas: list[Metrica],
        artefatos: list[Artefato],
        falha: Falha | None,
    ) -> RegistroExecucao:
        duracao = (datetime.now().astimezone() - andamento.inicio).total_seconds()
        registro = RegistroExecucao(
            id=andamento.id,
            projeto=andamento.projeto.nome,
            etapa=andamento.etapa,
            motor=andamento.motor,
            versao_motor=andamento.versao_motor,
            comando=comando,
            hash_rtl=andamento.hash_rtl,
            inicio=andamento.inicio,
            duracao_s=round(duracao, 3),
            situacao=situacao,
            falha=falha,
            metricas=metricas,
            artefatos=artefatos,
        )
        shutil.rmtree(andamento.dir_trabalho, ignore_errors=True)
        (andamento.diretorio / "andamento.json").unlink(missing_ok=True)
        _escrever_json(andamento.diretorio / "meta.json", registro.model_dump(mode="json"))
        _escrever_json(
            andamento.diretorio / "metricas.json", [m.model_dump(mode="json") for m in metricas]
        )
        final = self.dir / andamento.id
        andamento.diretorio.rename(final)
        _somente_leitura(final)
        registro.diretorio = final
        registro.numero = self._indexar(registro)
        return registro

    # --- leitura ----------------------------------------------------------------------------

    def carregar(self, ident: str) -> RegistroExecucao:
        diretorio = self.dir / ident
        meta = diretorio / "meta.json"
        if not meta.is_file():
            raise ErroCaderno(f"A execução {ident} não existe em {self.dir}.")
        registro = RegistroExecucao.model_validate_json(meta.read_text(encoding="utf-8"))
        metricas = diretorio / "metricas.json"
        if metricas.is_file():
            registro.metricas = [
                Metrica.model_validate(m) for m in json.loads(metricas.read_text("utf-8"))
            ]
        registro.diretorio = diretorio
        with closing(self._conectar()) as con:
            linha = con.execute("SELECT numero FROM execucoes WHERE id = ?", (ident,)).fetchone()
        registro.numero = linha[0] if linha else 0
        return registro

    def listar(self, etapa: Etapa | None = None) -> list[RegistroExecucao]:
        """Execuções do índice, da mais nova para a mais antiga, com métricas."""
        with closing(self._conectar()) as con:
            sql = "SELECT * FROM execucoes"
            args: tuple = ()
            if etapa is not None:
                sql += " WHERE etapa = ?"
                args = (etapa.value,)
            linhas = con.execute(sql + " ORDER BY inicio DESC, numero DESC", args).fetchall()
            registros = []
            for linha in linhas:
                metricas = [
                    Metrica(chave=c, valor=v, unidade=u or "", rotulo=r or "")
                    for c, v, u, r in con.execute(
                        "SELECT chave, valor, unidade, rotulo FROM metricas WHERE execucao = ?",
                        (linha["id"],),
                    )
                ]
                registros.append(
                    RegistroExecucao(
                        id=linha["id"],
                        numero=linha["numero"],
                        projeto=linha["projeto"],
                        etapa=Etapa(linha["etapa"]),
                        motor=linha["motor"],
                        versao_motor=linha["versao_motor"],
                        hash_rtl=linha["hash_rtl"],
                        inicio=datetime.fromisoformat(linha["inicio"]),
                        duracao_s=linha["duracao_s"],
                        situacao=Situacao(linha["situacao"]),
                        metricas=metricas,
                        diretorio=self.dir / linha["id"],
                    )
                )
        return registros

    def resolver(self, referencia: str) -> RegistroExecucao:
        """Aceita `ultima`, `penultima`, o número curto (#3 ou 3) ou um prefixo único do id."""
        ref = referencia.strip().lower().lstrip("#")
        todas = self.listar()
        if not todas:
            raise ErroCaderno("Ainda não há execuções neste projeto. Rode “axil executar gds”.")
        apelidos = {"ultima": 0, "última": 0, "penultima": 1, "penúltima": 1}
        if ref in apelidos:
            pos = apelidos[ref]
            if pos >= len(todas):
                raise ErroCaderno("Só existe uma execução; não há penúltima para comparar.")
            return self.carregar(todas[pos].id)
        if ref.isdigit():
            achada = next((r for r in todas if r.numero == int(ref)), None)
            if achada is not None:
                return self.carregar(achada.id)
        casam = [r for r in todas if r.id.lower().startswith(ref)]
        if len(casam) == 1:
            return self.carregar(casam[0].id)
        if not casam:
            if ref.isdigit() and len(ref) < 6:
                raise ErroCaderno(f"Não há execução de número {ref}. Veja “axil runs”.")
            raise ErroCaderno(f"Nenhuma execução começa com “{referencia}”. Veja “axil runs”.")
        opcoes = ", ".join(f"#{r.numero}" for r in casam[:6])
        raise ErroCaderno(f"“{referencia}” é ambíguo: casa com {opcoes}. Use o número curto.")

    # --- índice -----------------------------------------------------------------------------

    def _conectar(self) -> sqlite3.Connection:
        self.dir.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(self.dir / INDICE)
        con.row_factory = sqlite3.Row
        versao = con.execute("PRAGMA user_version").fetchone()[0]
        if versao == 0:
            with con:
                con.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS execucoes (
                        numero       INTEGER PRIMARY KEY AUTOINCREMENT,
                        id           TEXT UNIQUE NOT NULL,
                        projeto      TEXT NOT NULL,
                        etapa        TEXT NOT NULL,
                        motor        TEXT NOT NULL,
                        versao_motor TEXT NOT NULL,
                        situacao     TEXT NOT NULL,
                        inicio       TEXT NOT NULL,
                        duracao_s    REAL NOT NULL,
                        hash_rtl     TEXT NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS metricas (
                        execucao TEXT NOT NULL REFERENCES execucoes(id) ON DELETE CASCADE,
                        chave    TEXT NOT NULL,
                        valor    REAL NOT NULL,
                        unidade  TEXT,
                        rotulo   TEXT,
                        PRIMARY KEY (execucao, chave)
                    );
                    CREATE INDEX IF NOT EXISTS metricas_por_chave ON metricas(chave);
                    """
                )
                con.execute(f"PRAGMA user_version = {VERSAO_INDICE}")
        return con

    def _indexar(self, r: RegistroExecucao) -> int:
        with closing(self._conectar()) as con, con:
            cursor = con.execute(
                "INSERT OR REPLACE INTO execucoes (id, projeto, etapa, motor, versao_motor, "
                "situacao, inicio, duracao_s, hash_rtl) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (r.id, r.projeto, r.etapa.value, r.motor, r.versao_motor, r.situacao.value,
                 r.inicio.isoformat(), r.duracao_s, r.hash_rtl),
            )  # fmt: skip
            con.execute("DELETE FROM metricas WHERE execucao = ?", (r.id,))
            con.executemany(
                "INSERT INTO metricas (execucao, chave, valor, unidade, rotulo) "
                "VALUES (?, ?, ?, ?, ?)",
                [(r.id, m.chave, m.valor, m.unidade, m.rotulo) for m in r.metricas],
            )
            return int(cursor.lastrowid or 0)

    def reconstruir_indice(self) -> int:
        """Refaz o índice a partir dos diretórios. Devolve quantas execuções achou."""
        (self.dir / INDICE).unlink(missing_ok=True)
        metas = sorted(self.dir.glob("*/meta.json"), key=lambda p: p.parent.name)
        for meta in metas:
            registro = self.carregar(meta.parent.name)
            self._indexar(registro)
        return len(metas)

    def abandonadas(self) -> list[Path]:
        """Execuções que ficaram em .andamento cujo processo não existe mais."""
        pasta = self.dir / ANDAMENTO
        if not pasta.is_dir():
            return []
        mortas = []
        for d in sorted(p for p in pasta.iterdir() if p.is_dir()):
            try:
                pid = json.loads((d / "andamento.json").read_text("utf-8")).get("pid", 0)
            except (OSError, ValueError):
                pid = 0
            if not _processo_vivo(pid):
                mortas.append(d)
        return mortas

    def recuperar(self, projeto: Projeto) -> list[RegistroExecucao]:
        """Fecha como interrompidas as execuções abandonadas, preservando o log."""
        recuperadas = []
        for d in self.abandonadas():
            try:
                dados = json.loads((d / "andamento.json").read_text("utf-8"))
                andamento = Andamento(
                    id=d.name, projeto=projeto, etapa=Etapa(dados["etapa"]),
                    motor=dados["motor"], versao_motor=dados["versao_motor"],
                    hash_rtl=dados["hash_rtl"], inicio=datetime.fromisoformat(dados["inicio"]),
                    diretorio=d,
                )  # fmt: skip
            except (OSError, ValueError, KeyError):
                continue  # sem andamento.json legível: não há como reconstituir
            falha = Falha(
                resumo="O Axillares foi encerrado no meio desta execução.",
                proximo_passo="O log até aquele ponto ficou guardado. Execute de novo.",
            )
            recuperadas.append(self.finalizar(andamento, Situacao.INTERROMPIDA, [], [], [], falha))
        return recuperadas


def _processo_vivo(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _escrever_json(caminho: Path, dados: object) -> None:
    caminho.write_text(json.dumps(dados, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _somente_leitura(raiz: Path) -> None:
    """Imutável depois de criado: arquivos 0444, diretórios 0555."""
    leitura = stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH
    for pasta, subpastas, arquivos in os.walk(raiz, topdown=False):
        for nome in arquivos:
            os.chmod(Path(pasta) / nome, leitura)
        for nome in subpastas:
            os.chmod(Path(pasta) / nome, leitura | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    os.chmod(raiz, leitura | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
