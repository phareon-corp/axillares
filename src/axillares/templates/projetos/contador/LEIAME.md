# {{ nome }}

Projeto criado pelo Axillares a partir do exemplo “contador”.

```
rtl/contador.v          o circuito (Verilog)
restricoes/contador.sdc o relógio: 100 MHz
tb/tb_contador.v        testbench clássico
axil.toml               a descrição do projeto para o Axillares
runs/                   execuções (criada na primeira vez; não versione)
```

Experimente:

```bash
axil executar sintese   # síntese lógica — segundos
axil executar gds       # do RTL ao GDSII no sky130 — cerca de um minuto
axil runs               # o caderno de execuções
axil comparar penultima ultima
```

Depois, mude algo — a frequência no SDC, a largura `N` do contador — execute de novo e compare.
