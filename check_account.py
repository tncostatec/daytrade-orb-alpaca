from zoneinfo import ZoneInfo

from alpaca.trading.client import TradingClient

from config import API_KEY, PAPER, SECRET_KEY

BRT = ZoneInfo("America/Sao_Paulo")

tc = TradingClient(API_KEY, SECRET_KEY, paper=PAPER)
acct = tc.get_account()
clock = tc.get_clock()

estado = "ABERTO" if clock.is_open else "fechado"
print(f"conta        : {acct.account_number}  status={acct.status}")
print(f"paper        : {PAPER}")
print(f"equity       : {acct.equity}  cash={acct.cash}  buying_power={acct.buying_power}")
print(f"pattern DT   : {acct.pattern_day_trader}  daytrade_count={acct.daytrade_count}")
print(f"mercado      : {estado}")
print(f"agora (BRT)  : {clock.timestamp.astimezone(BRT):%Y-%m-%d %H:%M}")
print(f"próx abertura: {clock.next_open.astimezone(BRT):%Y-%m-%d %H:%M} BRT")
print(f"próx fecham. : {clock.next_close.astimezone(BRT):%Y-%m-%d %H:%M} BRT")
