import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")

API_KEY = os.environ["ALPACA_API_KEY"]
SECRET_KEY = os.environ["ALPACA_SECRET_KEY"]

# Trava: este projeto nunca opera conta real.
PAPER = True
if not API_KEY.startswith("PK"):
    raise SystemExit("ABORTADO: a chave não é de conta paper (esperado prefixo PK).")

# Prova de uso aprovada em 04/09/2026: 20 pregões e o executor para sozinho.
# Fica aqui porque `live_orb.py` e `check_dia.py` precisam do mesmo número.
MAX_SESSIONS = 20

# Filtro "range de abertura estreito": OR/ATR14 abaixo da mediana do ano 1 (filters.py).
# Único filtro que segurou fora da amostra no SPY; no QQQ não segurou (ver memória 04/09).
# Mora aqui, e não em live_orb.py, porque `sombra.py` precisa do MESMO número: se os dois
# divergirem, a sombra rotula os dias como filtrados/operados errado — e em silêncio.
OR_ATR_MAX = {"SPY": 0.195, "QQQ": 0.2517}

DATA_DIR = ROOT / "data"
JOURNAL_DIR = ROOT / "journal"
DATA_DIR.mkdir(exist_ok=True)
JOURNAL_DIR.mkdir(exist_ok=True)

SYMBOLS = ["SPY", "QQQ"]
