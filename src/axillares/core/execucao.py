"""Executar uma etapa: o ciclo de vida de uma execução, igual para CLI e GUI.

Não é orquestração de fluxo — quem encadeia ferramentas é o motor. Aqui só se cuida de abrir a
execução no caderno, entregar o contexto ao motor, guardar o log e fechar o registro imutável,
inclusive quando algo dá errado ou o usuário cancela.
"""

from __future__ import annotations

import threading
from collections.abc import Callable

from axillares.core.caderno import Caderno, RegistroExecucao
from axillares.core.modelos import Artefato, Etapa, Falha, Metrica, Situacao
from axillares.core.projeto import Projeto
from axillares.motor.base import Contexto, ErroMotor, Motor


def executar_etapa(
    projeto: Projeto,
    etapa: Etapa,
    motor: Motor,
    *,
    caderno: Caderno | None = None,
    ao_receber: Callable[[str], None] = lambda _linha: None,
    cancelar: threading.Event | None = None,
    ao_iniciar: Callable[[str], None] = lambda _id: None,
) -> RegistroExecucao:
    caderno = caderno or Caderno(projeto.dir_runs)
    cancelar = cancelar or threading.Event()
    andamento = caderno.iniciar(projeto, etapa, motor.nome, _versao(motor))
    ao_iniciar(andamento.id)

    with andamento.arquivo_log.open("a", encoding="utf-8") as log:

        def receber(linha: str) -> None:
            log.write(linha + "\n")
            log.flush()
            ao_receber(linha)

        ctx = Contexto(
            projeto=projeto,
            etapa=etapa,
            id_execucao=andamento.id,
            dir_trabalho=andamento.dir_trabalho,
            dir_saida=andamento.dir_saida,
            ao_receber=receber,
            cancelar=cancelar,
        )
        comando: list[str] = []
        metricas: list[Metrica] = []
        artefatos: list[Artefato] = []
        falha: Falha | None = None
        try:
            comando = motor.preparar(ctx)
            situacao = motor.executar(ctx)
            if cancelar.is_set():
                situacao = Situacao.INTERROMPIDA
            if situacao is not Situacao.INTERROMPIDA:
                artefatos = motor.coletar_artefatos(ctx)
                metricas = motor.coletar_metricas(ctx)
            if situacao is Situacao.FALHA:
                falha = motor.explicar_falha(ctx)
            elif situacao is Situacao.INTERROMPIDA:
                falha = Falha(
                    resumo="Execução interrompida a pedido.",
                    proximo_passo="Nada foi perdido: o log até o ponto da interrupção ficou "
                    "guardado. Execute de novo quando quiser.",
                )
        except ErroMotor as erro:
            situacao = Situacao.FALHA
            falha = Falha(resumo=str(erro), proximo_passo="Corrija o problema e execute de novo.")
            receber(f"[axil] {erro}")
        except Exception as erro:  # o registro precisa existir mesmo com defeito nosso
            situacao = Situacao.FALHA
            falha = Falha(
                resumo="Um erro inesperado do Axillares interrompeu a execução.",
                mensagens=[f"{type(erro).__name__}: {erro}"],
                proximo_passo="Isto é um defeito do Axillares. Relate o problema com o log.",
            )
            receber(f"[axil] erro interno: {type(erro).__name__}: {erro}")

    return caderno.finalizar(andamento, situacao, comando, metricas, artefatos, falha)


def _versao(motor: Motor) -> str:
    try:
        return motor.versao()
    except ErroMotor:
        return "?"
