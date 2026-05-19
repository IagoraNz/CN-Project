# Fase 1: Implementação Real e Inspeção (Sockets & Docker)

## Visão Geral

Este projeto implementa um sistema de transferência de arquivos que compara dois protocolos:
- **TCP**: Protocolo TCP nativo do Linux
- **R-UDP**: UDP confiável com janela deslizante (Go-Back-N)

O projeto utiliza Docker para criar um ambiente controlado de testes e `tc` (traffic control) para simular diferentes cenários de rede.

## Estrutura do Projeto

```
CN-Project/
├── docker/                          # Configuração Docker
│   ├── Dockerfile                   # Imagem base com dependências
│   └── docker-compose.yml           # Orquestração de containers
├── src/                             # Código-fonte Python
│   ├── client.py                    # Cliente de transferência
│   ├── server.py                    # Servidor de transferência
│   └── rudp.py                      # Implementação R-UDP
├── scripts/                         # Scripts de teste e configuração
│   ├── setup_network.sh             # Configurar tc (traffic control)
│   ├── capture_traffic.sh           # Capturar com tcpdump
│   └── run_tests.sh                 # Executar suite de testes
├── data/                            # Dados de teste e resultados
│   ├── pcap/                        # Arquivos de captura .pcap
│   ├── csv/                         # Dados em formato CSV
│   ├── logs/                        # Logs de execução
│   ├── send/                        # Arquivos para enviar
│   └── received/                    # Arquivos recebidos
├── analysis/                        # Scripts de análise
├── results/                         # Resultados e gráficos
│   └── graphs/                      # Gráficos Plotly/Seaborn
└── docs/                            # Documentação
```

## Quick Start

### 1. Configurar Informações do Aluno

Edite `.env.example` e renomeie para `.env`:

```bash
cp .env.example .env
```

Atualize com suas informações:
```env
STUDENT_ID=seu_matricula
STUDENT_NAME=Seu Nome
```

### 2. Construir Imagem Docker

```bash
make build
# ou: bash scripts/compose.sh build
```

### 3. Iniciar Containers

```bash
make up
# ou: bash scripts/compose.sh up -d
```

Verificar status:
```bash
bash scripts/compose.sh ps
```

### 4. Acessar Containers

```bash
# Terminal do servidor
docker exec -it cn-server bash

# Terminal do cliente
docker exec -it cn-client bash
```

## Usando o Sistema

### Teste Manual - TCP

**No container servidor:**
```bash
python3 src/server.py --protocol tcp
```

**No container cliente:**
```bash
python3 src/client.py /app/data/test_file.bin --protocol tcp
```

### Teste Manual - R-UDP

**No container servidor:**
```bash
python3 src/server.py --protocol rudp
```

**No container cliente:**
```bash
python3 src/client.py /app/data/test_file.bin --protocol rudp
```

### Teste com Captura de Tráfego

1. **Iniciar captura** (em um terminal do servidor):
```bash
bash scripts/capture_traffic.sh eth0 /app/data/pcap 30
```

2. **Aplicar condições de rede** (Cenário B: 10% perda, 50ms delay):
```bash
bash scripts/setup_network.sh eth0 B
```

3. **Executar transferência**:
```bash
python3 src/client.py /app/data/test_file.bin --protocol tcp
```

## Protocolos

### TCP (Nativo)

Utiliza sockets TCP padrão do Linux. Funcionalidades:
- Entrega confiável garantida
- Controle de congestionamento automático
- Ordenação de pacotes

### R-UDP (Reliable UDP)

Implementação customizada sobre UDP com:
- **Números de sequência**: Cada pacote tem um número único
- **ACKs (Acknowledgments)**: Confirmação de recebimento
- **Timeout e Retransmissão**: Se ACK não chegar em tempo, retransmite
- **Checksum MD5**: Validação de integridade por bloco
- **Janela Deslizante (Go-Back-N)**: Tamanho de janela configurável

#### Estrutura do Header R-UDP

```
| Sequence (2B) | ACK (2B) | Length (4B) | Timestamp (4B) | Flags (1B) | Checksum (2B) | Dados |
```

**Flags:**
- `0x01`: ACK
- `0x02`: FIN (Final)
- `0x04`: SYN (Sincronização)

## Cenários de Rede

### Cenário A: Condições Ideais
- **Perda de pacotes**: 0%
- **Latência**: 10ms
- **Uso**: Baseline para comparação

### Cenário B: Condições Realistas
- **Perda de pacotes**: 10%
- **Latência**: 50ms
- **Uso**: Teste de confiabilidade em rede degradada

### Cenário C: Condições Críticas
- **Perda de pacotes**: 20%
- **Latência**: 100ms
- **Uso**: Teste de robustez em rede muito instável

## Captura e Análise de Tráfego

### TCPDump

Captura todos os pacotes em tempo real:

```bash
sudo tcpdump -i eth0 -w arquivo.pcap 'tcp port 9000 or udp port 9001'
```

**Saídas:**
- `.pcap`: Formato binário (Wireshark)
- `.csv`: Formato tabular (análise em Python)
- `.json`: Formato estruturado (integração com análise)

### Validação Cruzada

A validação cruzada compara:

1. **Aplicação**: Tempos e throughput registrados pelo código
2. **Rede**: Dados capturados pelo tcpdump

**Exemplo de comparação:**
- App registra: "1024 bytes enviados em 0.5s = 2048 bps"
- TCPDump mostra: 1024 bytes em 0.5s de tráfego
- ✓ Dados validados!

## Header Customizado X-Custom-Auth

Todos os pacotes incluem:

```
X-Custom-Auth: MATRICULA-NOME
```

Isso é verificado no tcpdump para garantir a autenticação de origem.

## Métricas Coletadas

### Nível de Aplicação

- **Tempo de Transferência**: Segundos decorridos
- **Throughput**: Megabits por segundo (Mbps)
- **Taxa de Sucesso**: Porcentagem de pacotes sem retransmissão

### Nível de Rede (TCPDump)

- **Número de Pacotes**: Total capturado
- **Volume de Dados**: Bytes trafegados
- **Latência**: RTT dos ACKs
- **Perdas**: Pacotes não confirmados
- **Retransmissões**: Pacotes reenviados

## Análise e Gráficos

Os dados são exportados em CSV/JSON para análise em Python:

```python
import pandas as pd
import seaborn as sns
import plotly.express as px

# Carregar dados
df = pd.read_csv('data/csv/traffic_20260519_120000.csv')

# Plotar comparação TCP vs R-UDP
fig = px.box(df, x='protocol', y='throughput_mbps')
fig.show()
```

## Executar Suite Completa de Testes

```bash
bash scripts/run_tests.sh
```

Isso executa:
- 3 cenários × 2 protocolos = 6 testes
- Captura de tráfego para cada teste
- Coleta de métricas automática

Resultados salvos em `/app/data/`

## Logging

Todos os eventos são registrados:

- **Servidor**: `/app/data/logs/server_*.log`
- **Cliente**: `/app/data/logs/client_*.log`
- **Métricas**: `/app/data/logs/metrics_*.json`

Para ver em tempo real:
```bash
tail -f /app/data/logs/*.log
```

## Troubleshooting

### Erro: "Connection refused"
- Verifique se o servidor está rodando: `docker ps`
- Verifique a porta correta: `docker port cn-server`

### Erro: "Permission denied" em tcpdump
- Use `sudo` ou configure permissões do usuário:
  ```bash
  docker exec -it cn-server bash
  sudo tcpdump -i eth0 -w /app/data/pcap/test.pcap
  ```

### Containers não se comunicam
- Verifique rede Docker:
  ```bash
  docker network inspect cn-project_cn-network
  ```
- Teste conectividade: `docker exec cn-client ping server`

## Próximos Passos (Fase 2)

- Comparação com simulação SimPy
- Validação de modelos estocásticos
- Análise estatística avançada
- Relatório final

## Referências

- [RFC 768 - UDP](https://tools.ietf.org/html/rfc768)
- [RFC 793 - TCP](https://tools.ietf.org/html/rfc793)
- [Linux tc (traffic control)](https://man7.org/linux/man-pages/man8/tc.8.html)
- [TCPDump Manual](https://www.tcpdump.org/papers/sniffing-faq.html)
