# CLAUDE.md — daytrade (projeto pessoal do Tiago)

Laboratório de operação sistemática via API da Alpaca. Isolado dos demais
projetos do workspace: nada aqui referencia Escolia, SIM ou outros.

## Travas inegociáveis
1. **Só conta PAPER.** `config.py` força `PAPER = True` e aborta se a chave
   não começar com `PK`. Chave live (`AK...`) nunca entra neste projeto.
2. **Nenhuma ordem fora de estratégia backtestada e aprovada pelo Tiago.**
   Ordem manual só para teste de encanamento, 1 ação, fechada em seguida.
3. **Limite diário de perda simulada** definido na estratégia; atingido,
   para de operar no dia. Sem exceção "só mais uma".
4. **Números antes de opinião.** Backtest com custo e slippage, depois paper
   por período fixo. Métricas: resultado líquido, drawdown máximo, taxa de
   acerto, profit factor, Sharpe. Sem "parece que funciona".
5. **Reinício nunca inventa operação.** Se já existe posição, o executor assume
   a que está lá — jamais abre uma segunda. Se o rompimento já passou enquanto
   ele estava fora do ar, o dia é descartado em vez de entrar atrasado: entrada
   fora de hora não é a operação que o backtest mediu.

## Prova de uso em andamento (aprovada pelo Tiago em 04/09/2026)
20 pregões de paper no SPY: ORB 15min, alvo 2R, risco 0,5%/trade, filtro
"range de abertura estreito" (OR/ATR14 < 0,195). Roda sozinha pela tarefa
agendada do Windows `daytrade-orb-spy` (seg–sex 10:20 BRT → `pythonw.exe
run_daily.pyw`, sem janela de console: em 08/09/2026 alguém fechou a janela do
`run_daily.cmd` e matou o executor 12 min depois da abertura, sem aviso).
O executor conta os pregões em `journal/trades.csv`, recusa rodar duas vezes
no mesmo dia e para no 20º. Acompanhar com `python report.py`.
Desde 09/09/2026 os dias BARRADOS pelo filtro também são medidos em sombra, para que
a pergunta "o filtro está pagando o próprio aluguel?" tenha resposta com dado novo,
e não remoendo o mesmo histórico que pariu o filtro. Sombra não é operação: não conta
pregão, não manda ordem.
Critério: fills e slippage coerentes com o backtest (PF > 1,2 é bônus, não
prova; edge real pede ~100 trades). Depois: Tiago decide estender ou encerrar.

## Estrutura
- `config.py` — carrega `.env`, trava paper, pastas. Guarda também os números que
  mais de um script precisa enxergar iguais: `MAX_SESSIONS` e `OR_ATR_MAX` (o limite
  do filtro). Se o limite divergisse entre executor e sombra, a sombra rotularia os
  dias errado sem reclamar.
- `check_account.py` — testa conexão, conta e relógio do mercado.
- `fetch_history.py` — baixa barras 5min (IEX) para `data/`.
- `backtest_orb.py` — Opening Range Breakout com custos e sizing por risco.
- `sweep.py` / `filters.py` — robustez: grade de parâmetros e filtros ano1×ano2.
- `live_orb.py` — executor paper (bracket order, filtro, 1 trade/dia, 15:55 ET,
  retomada segura: `decidir_entrada` e `retomar`). Ao abrir posição, mostra na tela
  "não desligue o PC antes das 16:57": o bracket é DAY, então stop e alvo expiram no
  fechamento e, com o executor morto, a posição dormiria sem proteção.
- `check_dia.py` — aviso de fim de dia (tarefa `daytrade-check-dia`, 16:57 BRT, antes
  do Tiago desligar o PC): alerta por `msg.exe` se o pregão não fechou no journal, se
  sobrou posição aberta ou se a prova chegou aos 20. Se rodar atrasada (PC estava
  desligado), confere na hora o último pregão encerrado. `--agora` = teste fora de hora.
- `run_daily.pyw` — entrada da tarefa agendada (pythonw, sem console; redireciona
  stdout/stderr para `journal/scheduler.log` antes de importar o executor).
- `run_daily.cmd` — o mesmo, para rodar na mão. `report.py` — acompanhamento.
- `sombra.py` — registro em sombra (tarefa `daytrade-sombra`, seg–sex 17:20 BRT,
  `--backfill`): simula, SEM operar, o trade que o filtro barrou, com as mesmas regras
  de `backtest_orb.run()`, e grava em `journal/sombra.csv`. Só tem cliente de dados —
  nenhum `TradingClient`. Recusa dia que ainda não fechou; o `--backfill` recupera
  depois o que ficou para trás, então rodar cedo demais não perde nada.
- `testa_retomada.py` — testes da trava 5 (sem rede, com fakes). Rodar depois de
  qualquer mexida em `decidir_entrada`, `retomar` ou `main`.
- `data/` e `journal/` — ignorados no git.

## Contexto
Mercado: ações/ETFs dos EUA (SPY, QQQ) em horário regular, 10:30–17:00
Brasília durante o horário de verão americano. Conta paper Alpaca com
capital fictício. O operador desliga o PC por volta das 17h, o que explica os horários das tarefas de aviso.
