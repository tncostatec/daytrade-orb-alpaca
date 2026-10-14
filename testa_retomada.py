"""Testes da retomada segura do live_orb.py. Sem rede, sem ordem real.

Rodar: .venv/Scripts/python testa_retomada.py
Guardam a trava 5 do CLAUDE.md: reinicio nunca abre segunda posicao nem entra atrasado.
"""
import csv
import pathlib
import sys
import tempfile
import types

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
sys.argv = ["live_orb.py", "SPY"]

import pandas as pd  # noqa: E402

import live_orb as lo  # noqa: E402

falhas = []


def checar(nome, cond):
    print(("  OK   " if cond else "  FALHA") + f"  {nome}")
    if not cond:
        falhas.append(nome)


def barras(closes):
    ts = pd.date_range("2026-09-08 09:45", periods=len(closes), freq="5min", tz="America/New_York")
    return pd.DataFrame({"timestamp": ts, "close": closes, "high": closes, "low": closes})


ORH, ORL = 100.0, 98.0
print("\n== decidir_entrada (fidelidade ao backtest) ==")

st, side, _ = lo.decidir_entrada(barras([99, 99.5, 99.2]), ORH, ORL)
checar("preço dentro do range -> aguardar", st == "aguardar" and side == 0)

st, side, b = lo.decidir_entrada(barras([99, 99.5, 100.5]), ORH, ORL)
checar("rompimento de ALTA na barra mais recente -> entra comprado", st == "entrar" and side == 1)

st, side, b = lo.decidir_entrada(barras([99, 97.5]), ORH, ORL)
checar("rompimento de BAIXA -> entra vendido", st == "entrar" and side == -1)

st, side, b = lo.decidir_entrada(barras([99, 100.5, 100.7]), ORH, ORL)
checar("dado atrasado 1 barra -> ainda entra (tolerância)", st == "entrar" and side == 1)

st, side, b = lo.decidir_entrada(barras([99, 100.5, 100.7, 100.9]), ORH, ORL)
checar("rompimento 2 barras atrás -> PERDIDO, não entra atrasado", st == "perdido" and side == 0)

st, side, b = lo.decidir_entrada(barras([99, 100.5, 99.0, 97.0, 99.0]), ORH, ORL)
checar("rompeu, voltou e rompeu de novo -> vale o PRIMEIRO, perdido", st == "perdido")

print("\n== retomar (posição que já existia) ==")


class PosFake:
    symbol = "SPY"
    side = lo.PositionSide.LONG
    qty = "10"
    avg_entry_price = "770.00"
    unrealized_pl = "25.00"


class OrdemFake:
    stop_price = "768.00"
    limit_price = "774.00"


print("\n== monitorar_saida no horário (22/09/2026: cancel_orders matou a ordem de fechamento) ==")
from datetime import timedelta  # noqa: E402

ev = []
fechada = {"ok": False}


class TradingFake:
    def cancel_orders(self):
        ev.append("cancel_orders")

    def get_orders(self, req):
        return []

    def close_position(self, s):
        ev.append("close_position")
        fechada["ok"] = True


exit_t = lo.at(lo.today, lo.EXIT_TIME)
lo.now = lambda: exit_t + timedelta(minutes=1)
lo.time = types.SimpleNamespace(sleep=lambda s: None)
lo.retry = lambda fn, *a, **k: fn(*a, **k)
lo.log = lambda m: ev.append(("log", m))
lo.position = lambda: None if fechada["ok"] else PosFake()
lo.trading = TradingFake()
res = lo.monitorar_saida(exit_t)
checar("devolve 'time'", res == "time")
checar("zerou a mercado", "close_position" in ev)
depois = ev[ev.index("close_position") + 1:] if "close_position" in ev else []
checar("NÃO chama cancel_orders depois do fechamento", "cancel_orders" not in depois)
checar("só declara encerrado depois de a posição sumir", any(isinstance(e, tuple) and "encerrada" in e[1] for e in depois))

ev.clear()
fechada["ok"] = False
lo.position = lambda: PosFake()
res = lo.monitorar_saida(exit_t)
checar("fechamento que não executa -> aviso AINDA ABERTA, sem travar", res == "time" and any(isinstance(e, tuple) and "AINDA ABERTA" in e[1] for e in ev))

eventos = []
tmp = pathlib.Path(tempfile.mkdtemp())
lo.JOURNAL_DIR = tmp
lo.log = lambda m: eventos.append(("log", m))
lo.equity = lambda: 100100.0
lo.monitorar_saida = lambda t: "stop_or_target"
lo.exit_fill = lambda i: 774.0
lo.retry = lambda fn, *a, **k: fn(*a, **k)
lo.time = types.SimpleNamespace(sleep=lambda s: None)
lo.trading = types.SimpleNamespace(
    get_orders=lambda req: [OrdemFake()],
    submit_order=lambda r: eventos.append(("submit_order", r)),
    close_position=lambda s: eventos.append(("close_position", s)),
)
lo.bracket = lambda *a: eventos.append(("bracket", a))

lo.retomar(PosFake())

linhas = list(csv.DictReader(open(tmp / "trades.csv", encoding="utf-8")))
checar("gravou exatamente uma linha no journal", len(linhas) == 1)
r = linhas[0]
checar("marcou como retomada", r["reason"] == "retomada_stop_or_target")
checar("quantidade e lado vieram da posição existente", r["qty"] == "10" and r["side"] == "1")
checar("entrada veio do preço médio da posição", r["entry"] == "770.0")
checar("stop e alvo vieram das pernas vivas", r["stop"] == "768.0" and r["target"] == "774.0")
checar("resultado do dia inclui o que a posição já acumulava", r["pnl"] == "25.0")
checar("NÃO abriu ordem nova", not [e for e in eventos if e[0] in ("bracket", "submit_order")])

print("\n== main() com posição aberta ==")
chamou = []
lo.position = lambda: PosFake()
lo.retomar = lambda p: chamou.append(p)


def nao_deveria():
    raise AssertionError("main() avaliou sinal com posição aberta")


lo.sessions = nao_deveria
lo.main()
checar("vai direto para a retomada, sem avaliar sinal", len(chamou) == 1)

print("\n== avisar_tela (30/09/2026: aviso de posição aberta) ==")


def msg_quebrado(*a, **k):
    raise OSError("msg.exe ausente")


avisos_log = []
lo.subprocess = types.SimpleNamespace(run=msg_quebrado)
lo.log = lambda m: avisos_log.append(m)
lo.avisar_tela("teste", 10)
checar("msg.exe falhando não derruba o executor, só loga", any("aviso na tela falhou" in m for m in avisos_log))

print()
if falhas:
    print(f"FALHARAM {len(falhas)}: {falhas}")
    sys.exit(1)
print("todos os testes passaram")
