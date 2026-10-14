"""Ponto de entrada da tarefa agendada `daytrade-orb-spy`, rodado por `pythonw.exe`.

Existe por causa de 08/09/2026: a tarefa chamava `run_daily.cmd`, que abria uma
janela de console. Alguém fechou a janela às 10:33 BRT e o Windows matou o
executor (código 0xC000013A) 12 minutos depois da abertura, antes do range de
abertura fechar — o pregão foi perdido sem nenhum aviso.

`pythonw.exe` não cria console: não há janela para fechar. Em compensação
`sys.stdout`/`sys.stderr` são nulos, então tudo é redirecionado para
`journal/scheduler.log` ANTES de importar o executor — assim até uma falha de
import (`.env` ausente, chave errada) deixa rastro em vez de sumir em silêncio.
"""
import runpy
import sys
import traceback
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
(ROOT / "journal").mkdir(exist_ok=True)
saida = open(ROOT / "journal" / "scheduler.log", "a", encoding="utf-8", buffering=1)
sys.stdout = sys.stderr = saida

sys.argv = ["live_orb.py", *(sys.argv[1:] or ["SPY"])]
saida.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} tarefa iniciada: {' '.join(sys.argv[1:])}\n")
try:
    runpy.run_path(str(ROOT / "live_orb.py"), run_name="__main__")
except BaseException:
    saida.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} FALHA NA TAREFA:\n")
    traceback.print_exc(file=saida)
    raise
finally:
    saida.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} tarefa encerrada\n")
