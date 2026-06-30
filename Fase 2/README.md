# Fase 2 — Modelagem Estocástica (SimPy)

Simulador de eventos discretos que espelha o R-UDP Go-Back-N da [Fase 1](../Fase%201/), com validação cruzada contra dados reais (tc, tcpdump e logs da aplicação).

## Checklist — 10 Tarefas de Validação (Edital §3.1)

| # | Tarefa | Implementação |
|---|--------|---------------|
| 1 | **Modelagem de Atraso** — latência por distribuição normal baseada em dados reais | `src/network_models.py` + `task01_delay_model` |
| 2 | **Modelo de Perda de Bernoulli** — validar taxa vs `tc` | `src/network_models.py` + `task02_bernoulli_loss` |
| 3 | **Simulação de Timeout** — retransmissões vs tcpdump | `src/rudp_simulator.py` + `task03_retransmissions` |
| 4 | **Curva de Vazão** — arquivos 1 MB a 100 MB | `task04_throughput_curve` |
| 5 | **Sensibilidade da Janela** — saturação teórica variando N | `task05_window_sensitivity` |
| 6 | **Validação de RTT** — RTT médio sim vs tcpdump | `task06_rtt_validation` |
| 7 | **Impacto do Jitter** — estabilidade do fluxo | `task07_jitter_impact` |
| 8 | **Cenário de Estresse** — 25% de perda | `task08_stress_scenario` |
| 9 | **Análise de Eficiência** — razão dados / ACKs | `task09_efficiency` |
| 10 | **Convergência Estatística** — IC 95% com ≥30 execuções | `task10_convergence` |

## Quick Start

```bash
cd "Fase 2"

# Instalar dependências
make install

# Validação rápida (~2 min)
make validate-quick

# Validação completa (30 runs por tarefa, ~10–15 min)
make validate

# Comparação Real (Fase 1) vs Simulado
make compare

# Ou tudo de uma vez
bash scripts/run_all.sh
```

## Estrutura

```
Fase 2/
├── src/
│   ├── config.py           # Cenários A/B/C + STRESS (espelham Fase 1)
│   ├── network_models.py   # Atraso normal, Bernoulli, jitter
│   └── rudp_simulator.py   # SimPy Go-Back-N
├── analysis/
│   ├── load_phase1_data.py # Carrega métricas e RTT da Fase 1
│   ├── run_validation.py   # 10 tarefas + gráficos
│   └── compare_real_sim.py # Real vs Simulado
├── data/                   # CSVs gerados por tarefa
├── results/
│   ├── graphs/             # PNG (Plotly/Seaborn compatível com Colab)
│   └── validation_report.json
├── tests/
└── docs/README_FASE2.md
```

## Dependência da Fase 1

O simulador usa por padrão os parâmetros dos cenários `tc` da Fase 1. Se existirem logs em `../Fase 1/data/logs/` e CSVs em `../Fase 1/data/csv/`, os parâmetros de atraso e comparações Real vs Simulado são calibrados automaticamente.

## Critérios de Avaliação (Fase 2)

- **Modelagem SimPy + 10 tarefas**: 3.0 pts
- **Análise comparativa Real vs Simulado**: parte dos 3.0 pts (I/II)
- Gráficos em `results/graphs/` — prontos para Colab e relatório SBC

## Referências

- [SimPy Documentation](https://simpy.readthedocs.io/)
- Fase 1: R-UDP Go-Back-N, cenários tc A/B/C
- Edital: Avaliação Redes PPGCC 2026-1, §3
