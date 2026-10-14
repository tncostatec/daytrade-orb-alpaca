# Day trade sistemático em conta paper (Alpaca): laboratório ORB

[![CI](https://github.com/tncostatec/daytrade-orb-alpaca/actions/workflows/ci.yml/badge.svg)](https://github.com/tncostatec/daytrade-orb-alpaca/actions/workflows/ci.yml)
![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue)
[![Licença MIT](https://img.shields.io/badge/licen%C3%A7a-MIT-green)](LICENSE)

Uma estratégia intradiária simples (Opening Range Breakout no SPY) levada do backtest até 20 pregões de
operação automática em conta **paper** da Alpaca, com o rigor que se exigiria de software em produção:
custos no backtest, teste fora da amostra, filtro escolhido só com o ano 1, execução desatendida por tarefa
agendada, retomada segura após queda, registro em sombra dos dias barrados e benchmark contra buy-and-hold.

**Resultado honesto:** +0,86 % em 20 pregões com 8 operações (fator de lucro 2,37), mas `t = 1,08` com
`n = 8`: indistinguível de sorte. Buy-and-hold do SPY no mesmo período rendeu +1,71 %. A decisão foi **não
operar dinheiro real**. O que fica de valor é o método e a engenharia de execução, não o retorno.

*English: a 15-minute Opening Range Breakout strategy on SPY taken from a cost-aware backtest, through
parameter sweeps and out-of-sample regime filters, to 20 sessions of unattended paper trading on Alpaca
(bracket orders, safe resume after crashes, shadow logging of filtered days, buy-and-hold benchmark). The
measured result is statistically indistinguishable from luck, so no real money was ever traded. The code
and the incident log are the deliverable. Documentation is in Portuguese.*

> Não é recomendação de investimento. O projeto só opera conta paper (capital fictício) e o código aborta
> se a chave não for de conta paper.

---

## Travas que o código impõe

Estão em `CLAUDE.md` e no código, não só na intenção:

1. **Só conta paper.** `config.py` força `PAPER = True` e aborta se a chave não começar com `PK`.
2. **Nenhuma ordem fora da estratégia testada.** Ordem manual só para teste de encanamento, 1 ação, fechada em seguida.
3. **Limite diário de perda** definido na estratégia (1 operação por dia, stop no lado oposto do range).
4. **Números antes de opinião.** Backtest com custo e slippage, depois paper por período fixo; métricas: líquido,
   drawdown, taxa de acerto, fator de lucro, R médio, `t`.
5. **Reinício nunca inventa operação.** Se já existe posição, o executor a assume; nunca abre a segunda. Se o
   rompimento passou enquanto ele estava fora do ar, o dia é descartado: entrada atrasada não é o que o backtest mediu.

## A estratégia

- **ORB 15 min no SPY**: range = máxima e mínima dos primeiros 15 minutos (09:30 ET). Primeiro fechamento de barra
  de 5 min acima do range compra; abaixo, vende a descoberto. Uma operação por dia.
- **Ordem bracket**: stop no lado oposto do range, alvo em 2R. Saída forçada às 15:55 ET.
- **Risco** de 0,5 % do patrimônio por operação, sem alavancagem (na prática ~0,19 %, porque sem alavancagem o
  tamanho fica limitado a ~130 SPY, 100 % do patrimônio paper).
- **Filtro de regime**: só opera quando o range de abertura é estreito, `OR / ATR14 < 0,195`. Limiar fixado
  usando só o ano 1 da amostra (ver abaixo).

## Método e o que os números disseram

| Etapa | O que foi feito | Resultado medido |
|---|---|---|
| Backtest (set/2024 a set/2026, SPY, 5 min IEX, slippage 1 c por lado) | `backtest_orb.py` | +15,3 % em 2 anos, PF 1,18, Sharpe 1,12, drawdown −5 %. Buy-and-hold no período: +40 %. |
| Robustez: grade de parâmetros + dentro/fora da amostra | `sweep.py` | Grade quase toda positiva (platô), mas ano 1 +13,9 % (`t` 2,45) contra ano 2 +1,2 % (`t` 0,90): vantagem fraca e não persistente. |
| Filtros de regime (10 filtros × 2 símbolos, limiares só do ano 1) | `filters.py` | Único que segurou fora da amostra no SPY: "range de abertura estreito". Ano 1 +8,1 % (PF 1,55, `t` 2,05); ano 2 +5,8 % (PF 1,63, `t` 2,14); drawdown −1,2 %. No QQQ esse filtro falha. |
| Ressalva estatística | varredura do limiar de 0,14 a 0,32 | No SPY o ano 2 é **platô, não pico** (PF entre 1,20 e 1,69 em toda a faixa; sem filtro 1,03). Regra fabricada costuma dar pico estreito. Ainda assim: com 20 testes, um acerto por acaso é esperado. Só o teste à frente responde. |
| Prova de uso: 20 pregões de paper (09/09 a 07/10/2026) | `live_orb.py` por tarefa agendada | 12 dias filtrados, 8 operações (6 compras, 2 vendas). Líquido +US$ 859,22 (+0,86 %), PF 2,37, acerto 50 %, R médio +0,57, drawdown −0,43 %. **`t` = 1,08**: compatível com sorte; três operações fizeram o placar. |
| Benchmark | `report.py` | Buy-and-hold do SPY no mesmo período: +1,71 %. |
| Slippage real de entrada (contra a abertura da barra seguinte, que o backtest usa) | journal | 16, 6, 5, −2, 3, 15, −5, −4 c → média 4,4 c por ação, contra 1 c assumido. |
| Registro em sombra dos dias barrados (31/08 a 07/10, 27 dias) | `sombra.py` | Dias liberados: n = 10, R médio +0,44 (acerto 50 %). Dias barrados: n = 17, R médio −0,58 (acerto 24 %, soma −9,8R). O filtro separou forte com dado novo; é o achado mais sólido, ainda com n pequeno. |

**Conclusão.** Não há evidência de vantagem. Mesmo o melhor caso fora da amostra (+5,8 % ao ano) perde para a
renda fixa brasileira da época com risco incomparável. Uma vantagem real pediria ~100 operações; no ritmo de
~8 por mês, cerca de um ano de paper. A decisão registrada foi não colocar dinheiro real e manter a regra
intacta: otimizar depois de ver o resultado destruiria a única credibilidade do número, ter vindo do ano 1 sem
olhar o ano 2.

## O que deu errado na operação e o que mudou

Quatro incidentes em 20 pregões, todos em caminhos que o backtest não exercita. Cada um virou código e teste.

| Quando | O que aconteceu | Correção |
|---|---|---|
| 04/09 | Na saída forçada, `cancel_orders()` é assíncrono: as pernas do bracket ainda seguravam a quantidade e `close_position()` foi recusado. O `except` chamou a saída de novo, estourou e **matou o processo** com a posição aberta e descoberta no fim de semana. | `flatten()` espera as ordens abertas sumirem antes de zerar; a saída de recuperação vive em `try/except` próprio e grava o journal antes de qualquer outra coisa. |
| 08/09 | A tarefa agendada rodava um `.cmd` com janela de console. Alguém fechou a janela e o Windows matou o executor 12 minutos depois da abertura (código `0xC000013A`), sem nenhum aviso. | `run_daily.pyw` com `pythonw.exe` (sem console) redirecionando `stdout`/`stderr` para arquivo **antes** de importar o executor, para que até falha de import deixe rastro. |
| 22/09 | Um `cancel_orders()` que sobrou da versão anterior, chamado logo depois do fechamento a mercado, **cancelou a própria ordem de fechamento** 135 ms depois de roteada. Primeira vez que o caminho "saída por horário" rodava de ponta a ponta: o bug ficou latente 18 dias. | Removido. "Encerrado" só quando a posição sumir de fato (poll com teto), nunca pelo retorno da chamada. Teste com fakes verifica a **sequência** de chamadas, não só o resultado. |
| 30/09 | O PC era desligado antes da saída forçada em vários dias. O bracket é `DAY`: com o executor morto, uma posição dormiria sem stop. | Aviso na tela logo após a entrada; `check_dia.py` às 16:57 BRT confere journal e posição, inclusive quando roda atrasado na manhã seguinte, sem alarme falso. |

**Retomada segura** (`decidir_entrada` e `retomar` em `live_orb.py`): olha o primeiro rompimento do dia, não o
preço de agora; se já passou, registra "rompimento perdido" e sai sem operar; se há posição, leva-a até a saída
e nunca abre a segunda. São 20 testes sem rede em `testa_retomada.py`, que rodam no CI.

## Estrutura

| Arquivo | Papel |
|---|---|
| `config.py` | carrega `.env`, trava paper, pastas; guarda os números que mais de um script precisa enxergar iguais (`MAX_SESSIONS`, `OR_ATR_MAX`) |
| `check_account.py` | conexão, conta e relógio do mercado |
| `fetch_history.py` | barras de 5 min (feed IEX) para `data/` |
| `backtest_orb.py` | ORB com custos e sizing por risco |
| `sweep.py`, `filters.py` | robustez: grade de parâmetros; filtros de regime avaliados ano 1 × ano 2 |
| `live_orb.py` | executor paper: bracket, filtro, 1 operação por dia, saída 15:55 ET, retomada segura |
| `sombra.py` | simula, sem operar, o trade que o filtro barrou, com as regras do backtest; `--backfill` recupera dias |
| `check_dia.py` | aviso de fim de dia: pregão sem linha no journal, posição aberta, prova concluída |
| `report.py` | placar da prova, comparação com o backtest e benchmark buy-and-hold |
| `run_daily.pyw`, `run_daily.cmd` | entrada da tarefa agendada (sem console) e execução manual |
| `testa_retomada.py` | 20 testes offline da retomada segura e dos caminhos de saída |
| `data/`, `journal/` | ignorados no git (barras baixadas, logs e CSVs da prova) |

## Como rodar

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt     # Linux/macOS: .venv/bin/python
cp .env.example .env                                         # chaves de conta PAPER da Alpaca (prefixo PK)
.venv/Scripts/python check_account.py
.venv/Scripts/python fetch_history.py
.venv/Scripts/python backtest_orb.py
.venv/Scripts/python sweep.py
.venv/Scripts/python filters.py
.venv/Scripts/python live_orb.py SPY --test     # encanamento: dados de ontem + bracket de 1 ação cancelada
.venv/Scripts/python report.py
.venv/Scripts/python testa_retomada.py          # sem rede
```

Operação desatendida no Windows: tarefa agendada `daytrade-orb-spy` (seg a sex, 10:20 BRT) chamando
`pythonw.exe run_daily.pyw SPY`, com reinício automático; `daytrade-check-dia` (16:57 BRT) e
`daytrade-sombra` (17:20 BRT, `sombra.py SPY --backfill`).

## Avisos

- Conta paper apenas. Nada aqui foi desenhado para dinheiro real; a análise de 07/10/2026 concluiu que, com
  valores pequenos, a regra PDT (máximo de 3 day trades em 5 dias úteis abaixo de US$ 25 mil), a ausência de
  bracket e de venda a descoberto em fracionário e as taxas de remessa tornariam a operação inviável.
- Dados do feed IEX gratuito. Resultados dependem do período; não extrapole.

## Licença e autor

MIT (ver `LICENSE`). **Tiago Costa** · [TN Costa Tecnologia](https://www.tncostatecnologia.com.br/) ·
[LinkedIn](https://www.linkedin.com/in/tiago-costa-7470587a) · [GitHub](https://github.com/tncostatec)
