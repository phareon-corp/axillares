"""Adaptador: a única fronteira com motores de terceiros. Nunca importa Qt.

Motores disponíveis por nome (o mesmo usado em [motores] no axil.toml).
"""

from __future__ import annotations

from axillares.motor.base import Contexto, ErroMotor, Motor

MOTORES = ("siliconcompiler", "edalize")


def obter_motor(nome: str) -> Motor:
    if nome == "siliconcompiler":
        from axillares.motor.silicon import MotorSiliconCompiler

        return MotorSiliconCompiler()
    if nome == "edalize":
        from axillares.motor.edalize_fpga import MotorEdalize

        return MotorEdalize()
    disponiveis = ", ".join(MOTORES)
    raise ErroMotor(f"Motor “{nome}” desconhecido. Disponíveis: {disponiveis}.")


__all__ = ["MOTORES", "Contexto", "ErroMotor", "Motor", "obter_motor"]
