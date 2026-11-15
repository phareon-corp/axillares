"""Testes automáticos do contador, em cocotb (Python).

Diferente do testbench clássico (tb_contador.v), aqui ninguém precisa olhar a onda: cada função
dirige o circuito e confere a resposta com assert. Passou ou falhou. Rode com “axil teste”.
"""

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, FallingEdge, Timer


async def ligar(dut):
    """Relógio de 100 MHz, en=0 e um pulso de reset."""
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    dut.en.value = 0
    dut.rst_n.value = 0
    await Timer(12, unit="ns")
    dut.rst_n.value = 1
    await FallingEdge(dut.clk)  # mude as entradas longe da borda de subida


@cocotb.test()
async def reset_zera_a_saida(dut):
    """Depois do reset, a contagem começa em zero."""
    await ligar(dut)
    assert dut.q.value == 0, f"depois do reset q = {int(dut.q.value)}, esperado 0"


@cocotb.test()
async def conta_com_en_e_para_sem(dut):
    """Com en=1 por 10 pulsos conta até 10; com en=0 fica parado."""
    await ligar(dut)
    dut.en.value = 1
    await ClockCycles(dut.clk, 10, rising=True)
    await FallingEdge(dut.clk)
    dut.en.value = 0
    assert dut.q.value == 10, f"depois de 10 pulsos q = {int(dut.q.value)}, esperado 10"
    await ClockCycles(dut.clk, 3)
    assert dut.q.value == 10, f"com en=0 a contagem mudou para {int(dut.q.value)}"
