# CN-Project - Redes de Computadores

Projeto de pós-graduação em fases para análise comparativa entre sistemas reais (Sockets & Docker) e modelos formais de simulação (SimPy).

## 📋 Fase 1: Implementação Real e Inspeção

- **TCP**: Transferência via sockets TCP nativo
- **R-UDP**: UDP confiável com janela deslizante (Go-Back-N)
- **Simulação de Rede**: Uso de `tc` para injetar perda e latência
- **Captura**: `tcpdump` para análise de tráfego
- **Validação Cruzada**: Comparação app ↔ rede

### 🚀 Quick Start

```bash
# Setup inicial (construir Docker e iniciar containers)
make setup

# Editar informações do aluno
cp .env.example .env  # Adicione sua matrícula e nome

# Teste TCP
make test-tcp

# Teste R-UDP
make test-rudp

# Teste completo (3 cenários × 2 protocolos)
make test-all

# Gerar gráficos e análise
make analyze

# Interface gráfica (botões Setup, Test, Analyze, Down + logs; só Python 3)
make ui
```

### 📁 Estrutura do Projeto

```
CN-Project/
├── docker/              # Dockerfile + docker-compose.yml
├── src/                 # Cliente, servidor, implementação R-UDP
├── scripts/             # setup_network.sh, capture_traffic.sh, run_tests.sh
├── data/                # PCAP, CSV, logs, arquivos de teste
├── analysis/            # Scripts de análise (Plotly/Seaborn)
├── results/             # Gráficos HTML e relatórios
├── docs/                # README_FASE1.md com documentação detalhada
├── Makefile            # Comandos de automação
└── .env.example        # Variáveis de ambiente
```

### 📊 Cenários de Teste

| Cenário | Perda | Latência |
|---------|-------|----------|
| A (Ideal) | 0% | 10ms |
| B (Realista) | 10% | 50ms |
| C (Crítica) | 20% | 100ms |

### 🎯 Critérios de Avaliação (10 pontos)

- Docker & TC Setup: 1.0 pt
- Protocolo R-UDP: 2.5 pts
- Validação TCPDump: 1.5 pts
- Análise Estatística: 2.0 pts
- Integração de Dados: 1.0 pt
- Relatório (SBC): 1.0 pt
- Vídeo Demonstrativo: 1.0 pt

### 📖 Documentação

Leia a documentação completa em [`docs/README_FASE1.md`](docs/README_FASE1.md) para:
- Detalhes técnicos da implementação R-UDP
- Como executar testes com simulação de rede
- Como capturar e analisar tráfego com tcpdump
- Troubleshooting e próximos passos

### 🔗 Úteis

- `make help` - Lista todos os comandos disponíveis
- `make logs` - Visualizar logs em tempo real
- `make shell-server` - Acessar terminal do servidor
- `make shell-client` - Acessar terminal do cliente
- `make clean` - Limpar dados de teste
