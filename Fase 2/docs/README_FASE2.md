# Fase 2: Modelagem Estocástica (SimPy)

## Visão Geral

Esta fase desenvolve um **simulador de eventos discretos** em SimPy que replica o comportamento do protocolo R-UDP (Go-Back-N) implementado na Fase 1. O objetivo é validar modelos estocásticos contra medições reais de rede (tc, tcpdump, logs da aplicação).

## Arquitetura do Simulador

```
┌─────────────┐     uplink      ┌──────────────┐     downlink    ┌─────────────┐
│   Sender    │ ──────────────► │   Channel    │ ◄────────────── │  Receiver   │
│  (Go-Back-N)│ ◄────────────── │ Bernoulli +  │ ──────────────► │   (ACKs)    │
└─────────────┘                 │ Normal delay │                 └─────────────┘
                                └──────────────┘
```

### Modelos Estocásticos

1. **Atraso (Normal)**: `delay ~ max(0, N(μ, σ))` calibrado com RTT do tcpdump
2. **Perda (Bernoulli)**: cada pacote perdido com probabilidade `p` (tc)
3. **Jitter**: variação adicional `N(0, σ_jitter)` sobre o atraso base

### Parâmetros (alinhados à Fase 1)

| Cenário | Perda | Delay μ | Uso |
|---------|-------|---------|-----|
| A | 0% | 10 ms | Baseline |
| B | 10% | 50 ms | Realista |
| C | 20% | 100 ms | Crítico |
| STRESS | 25% | 100 ms | Tarefa 8 |

## As 10 Tarefas de Validação

Detalhamento conforme edital §3.1:

### Tarefa 1 — Modelagem de Atraso
Ajusta `μ` e `σ` da distribuição normal a partir de amostras RTT extraídas dos PCAPs da Fase 1. Compara histograma simulado vs real.

### Tarefa 2 — Bernoulli vs tc
Executa N simulações por cenário e verifica se a taxa observada de pacotes perdidos converge para `p` configurado no `tc`.

### Tarefa 3 — Timeout e Retransmissões
Compara contagem média de retransmissões do SimPy com logs da aplicação e inferências do tcpdump.

### Tarefa 4 — Curva de Vazão
Varia tamanho do arquivo de 1 MB a 100 MB (Cenário B) e plota throughput vs tamanho.

### Tarefa 5 — Sensibilidade da Janela
Varia N ∈ {1, 2, 4, 8, 16, 32, 64} e identifica ponto de saturação (>95% do máximo).

### Tarefa 6 — RTT
Compara RTT médio simulado (ida+volta) com medição do tcpdump por cenário.

### Tarefa 7 — Jitter
Injeta σ_jitter crescente e mede coeficiente de variação da vazão.

### Tarefa 8 — Estresse (25%)
Prediz tempo de transferência com 25% de perda e valida com simulação direta.

### Tarefa 9 — Eficiência
Calcula `pacotes_dados / (pacotes_dados + pacotes_ACK)`.

### Tarefa 10 — Convergência
≥30 execuções por cenário; intervalo de confiança 95% (t de Student) para vazão e tempo.

## Saídas

- `data/taskXX_*.csv` — dados tabulares por tarefa
- `results/graphs/taskXX_*.png` — gráficos Seaborn
- `results/validation_report.json` — relatório consolidado
- `results/comparison_report.json` — Real vs Simulado

## Integração com Fase 1

```python
from analysis.load_phase1_data import load_app_metrics, get_delay_params_from_phase1

metrics = load_app_metrics()          # ../Fase 1/data/logs/
params = get_delay_params_from_phase1()  # calibração automática
```

Se a Fase 1 ainda não tiver dados capturados, o simulador usa os defaults do edital (cenários A/B/C).
