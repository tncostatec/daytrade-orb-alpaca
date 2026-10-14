"""Aviso de fim de dia da prova de uso.

Rodado pela tarefa `daytrade-check-dia` às 16:57 BRT, dois minutos depois da saída forçada
do executor (15:55 ET = 16:55 BRT). Só aparece na tela quando algo merece atenção: pregão
sem linha no journal, posição ainda aberta depois do fechamento, ou prova concluída. Dia sem
pregão nos EUA e dia normal já fechado passam em silêncio.

Até 30/09/2026 a tarefa era às 17:15 e o PC costuma ser desligado antes disso: o aviso não
rodou em 24, 25 e 29/09. A execução atrasada do dia seguinte (StartWhenAvailable) esperava
o fechamento do dia NOVO, o Agendador a matava no limite de 4 h e o dia perdido nunca era
conferido. Agora, atrasada, ela confere na hora o último pregão encerrado.

Existe porque em 08/09/2026 o executor morreu no meio do pregão e ninguém soube — o
Tiago só descobriu horas depois estranhando que a Alpaca não tinha movimento.

O aviso é o `msg.exe` do próprio Windows: não bloqueia, some sozinho e não traz
dependência nova. Este projeto é isolado, então nada de WhatsApp/e-mail de outros
projetos aqui.
"""
import csv
import os
import subprocess
import sys
import time
from datetime import datetime, time as dtime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
(ROOT / "journal").mkdir(exist_ok=True)
saida = open(ROOT / "journal" / "checker.log", "a", encoding="utf-8", buffering=1)
sys.stdout = sys.stderr = saida  # rodado por pythonw (sem console): sem isto nada fica registrado

from alpaca.trading.client import TradingClient  # noqa: E402
from alpaca.trading.requests import GetCalendarRequest  # noqa: E402

from config import API_KEY, JOURNAL_DIR, MAX_SESSIONS, PAPER, SECRET_KEY  # noqa: E402

ET = ZoneInfo("America/New_York")
SYMBOL = next((a for a in sys.argv[1:] if not a.startswith("--")), "SPY")


def log(msg):
    print(f"{datetime.now():%Y-%m-%d %H:%M:%S} {msg}")


def avisar(texto):
    log(f"AVISO: {texto}")
    destino = os.environ.get("USERNAME", "*")
    subprocess.run(["msg.exe", destino, "/TIME:900", f"[day trade {SYMBOL}] {texto}"], check=False)


def dia_a_conferir(trading):
    """Devolve (pregão a conferir, se a posição aberta diz algo sobre ele) ou None.

    No horário (a partir de 2 h antes das 15:57 ET) confere o pregão de hoje, esperando as
    15:57 se chegou cedo: em novembro, sem o horário de verão americano, 16:57 BRT vira
    14:57 ET. Atrasada (o PC estava desligado às 16:57), confere o último pregão encerrado
    sem esperar nada — senão o Agendador a mata no limite de 4 h, como até 30/09/2026."""
    agora = datetime.now(ET)
    hoje = agora.date()
    alvo = agora.replace(hour=15, minute=57, second=0, microsecond=0)
    pregao_hoje = bool(trading.get_calendar(GetCalendarRequest(start=hoje, end=hoje)))
    if "--agora" in sys.argv or agora >= alvo - timedelta(hours=2):  # `--agora` só para teste
        if not pregao_hoje:
            log(f"{hoje}: sem pregão nos EUA; nada a conferir")
            return None
        if agora < alvo and "--agora" not in sys.argv:
            log(f"ainda são {agora:%H:%M} ET; esperando {(alvo - agora).total_seconds() / 60:.0f} min")
            time.sleep((alvo - agora).total_seconds())
        return hoje, True
    anteriores = trading.get_calendar(
        GetCalendarRequest(start=hoje - timedelta(days=10), end=hoje - timedelta(days=1)))
    dia = anteriores[-1].date
    # Posição aberta só fala do pregão anterior enquanto o de hoje não abriu; depois disso
    # pode ser a operação de hoje, legítima.
    olhar_posicao = not pregao_hoje or agora.time() < dtime(9, 30)
    log(f"execução atrasada (o PC estava desligado às 16:57?): conferindo o pregão de {dia:%d/%m}")
    return dia, olhar_posicao


def problemas(trading, dia, olhar_posicao):
    """Textos de aviso para o pregão `dia`; lista vazia = dia fechado direito."""
    path = JOURNAL_DIR / "trades.csv"
    rows = []
    if path.exists():
        with open(path, encoding="utf-8") as f:
            rows = [r for r in csv.DictReader(f) if r["symbol"] == SYMBOL]
    avisos = []
    if olhar_posicao:
        pos = next((p for p in trading.get_all_positions() if p.symbol == SYMBOL), None)
        if pos is not None:
            avisos.append(f"POSICAO ABERTA de {pos.qty} {SYMBOL} depois do fechamento - o executor "
                          f"nao zerou. Conferir na Alpaca antes do proximo pregao.")
    if not any(r["date"] == str(dia) for r in rows):
        avisos.append(f"o pregao de {dia:%d/%m} NAO fechou no journal ({len(rows)}/{MAX_SESSIONS} "
                      f"registrados). Ver journal/live_{dia}.log.")
    return avisos, len(rows)


def main():
    trading = TradingClient(API_KEY, SECRET_KEY, paper=PAPER)
    alvo = dia_a_conferir(trading)
    if alvo is None:
        return
    dia, olhar_posicao = alvo
    avisos, n = problemas(trading, dia, olhar_posicao)
    if avisos and dia == datetime.now(ET).date():
        # 15:57 fica só 2 min depois da saída forçada; se o executor ainda está gravando o
        # journal, dar mais um tempo antes de alarmar à toa.
        time.sleep(60)
        avisos, n = problemas(trading, dia, olhar_posicao)
    for texto in avisos:
        avisar(texto)
    if avisos:
        return
    if n >= MAX_SESSIONS:
        avisar(f"PROVA CONCLUIDA: {n} pregoes registrados. Rodar report.py e decidir.")
    else:
        log(f"{dia}: ok — {n}/{MAX_SESSIONS} pregões registrados")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        import traceback
        traceback.print_exc(file=saida)
        avisar("o verificador de fim de dia falhou; ver journal/checker.log")
        raise
