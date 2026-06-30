# CN-Project — Redes de Computadores

Projeto de pós-graduação (PPGCC) dividido em duas fases que comparam, lado a lado, um sistema **real** de transferência de arquivos (TCP vs. R-UDP sobre Docker) com um **modelo de simulação estocástica** (SimPy) calibrado pelos dados coletados na primeira fase.

```
┌────────────────────────┐        dados reais        ┌────────────────────────┐
│        Fase 1          │ ─────────────────────────► │        Fase 2          │
│  Sockets + Docker + tc │   (logs, csv, RTT, perda)   │  Simulação SimPy       │
│  Implementação real    │                             │  Validação estatística │
└────────────────────────┘                             └────────────────────────┘
```

## Visão Geral

| Fase | Tema | Tecnologias |
|------|------|-------------|
| [**Fase 1**](Fase%201/) | Implementação real de TCP e R-UDP (Go-Back-N), simulação de rede com `tc` e captura com `tcpdump` | Python, Docker, sockets |
| [**Fase 2**](Fase%202/) | Modelagem estocástica em eventos discretos do R-UDP, com validação cruzada contra a Fase 1 | Python, SimPy |

A Fase 2 depende dos dados gerados pela Fase 1 (logs e CSVs) para calibrar seus modelos de atraso e perda — rode a Fase 1 antes para obter a comparação completa Real vs. Simulado.

## Estrutura do Repositório

```
CN-Project/
├── Fase 1/                  # Implementação real (Sockets & Docker)
│   ├── docker/               # Dockerfile + docker-compose.yml
│   ├── src/                  # Cliente, servidor, protocolo R-UDP
│   ├── scripts/               # Setup de rede (tc), captura (tcpdump), testes
│   ├── data/                  # PCAP, CSV, logs, arquivos de teste
│   ├── analysis/               # Scripts de análise (Plotly/Seaborn)
│   ├── results/                # Gráficos e relatórios
│   ├── ui/                     # Interface gráfica de apoio
│   └── docs/README_FASE1.md    # Documentação técnica detalhada
│
└── Fase 2/                  # Modelagem estocástica (SimPy)
    ├── src/                   # Modelos de rede + simulador Go-Back-N
    ├── analysis/                # Validação (10 tarefas) e comparação Real vs Simulado
    ├── data/                     # CSVs gerados por tarefa
    ├── results/                  # Gráficos e relatórios JSON
    └── docs/README_FASE2.md      # Documentação técnica detalhada
```

## Protocolos Implementados

- **TCP**: transferência via sockets TCP nativos do Linux.
- **R-UDP**: UDP confiável customizado com números de sequência, ACKs, timeout/retransmissão, checksum MD5 e janela deslizante (Go-Back-N).

## Cenários de Rede

| Cenário | Perda | Latência | Uso |
|---------|-------|----------|-----|
| A — Ideal | 0% | 10 ms | Baseline |
| B — Realista | 10% | 50 ms | Confiabilidade em rede degradada |
| C — Crítica | 20% | 100 ms | Robustez em rede instável |
| STRESS *(Fase 2)* | 25% | 100 ms | Cenário de estresse |

## Quick Start

### Fase 1 — Implementação real

```bash
cd "Fase 1"
cp .env.example .env       # preencher matrícula e nome
make setup                 # build + sobe os containers Docker
make test-all               # 3 cenários × 2 protocolos
make analyze                 # gera gráficos e relatórios
```

### Fase 2 — Simulação SimPy

```bash
cd "Fase 2"
make install                # instala dependências
make validate                # roda as 10 tarefas de validação
make compare                  # compara Real (Fase 1) vs Simulado
```

Veja o detalhamento completo de comandos, métricas e troubleshooting em cada subprojeto:
[`Fase 1/README.md`](Fase%201/README.md) · [`Fase 1/docs/README_FASE1.md`](Fase%201/docs/README_FASE1.md)
[`Fase 2/README.md`](Fase%202/README.md) · [`Fase 2/docs/README_FASE2.md`](Fase%202/docs/README_FASE2.md)

## Pipeline de Validação

1. **Fase 1** transfere arquivos via TCP e R-UDP sob diferentes condições de rede (`tc`), capturando tráfego com `tcpdump` e métricas de aplicação (tempo, throughput, retransmissões).
2. **Fase 2** consome esses dados (`../Fase 1/data/logs`, `../Fase 1/data/csv`) para calibrar distribuições de atraso (Normal) e perda (Bernoulli), executa 10 tarefas de validação estatística e compara os resultados simulados com os reais.

## Licença

Distribuído sob a licença MIT — veja [`Fase 1/LICENSE`](Fase%201/LICENSE).
