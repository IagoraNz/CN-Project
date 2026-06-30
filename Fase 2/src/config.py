"""Parâmetros alinhados com a Fase 1 (R-UDP Go-Back-N + cenários tc)."""
from dataclasses import dataclass, field
from typing import Dict


SCENARIOS: Dict[str, Dict] = {
    'A': {'loss_prob': 0.0, 'delay_mean_ms': 10.0, 'delay_std_ms': 2.0, 'label': 'Ideal (0% perda, 10ms)'},
    'B': {'loss_prob': 0.10, 'delay_mean_ms': 50.0, 'delay_std_ms': 8.0, 'label': 'Realista (10% perda, 50ms)'},
    'C': {'loss_prob': 0.20, 'delay_mean_ms': 100.0, 'delay_std_ms': 15.0, 'label': 'Crítico (20% perda, 100ms)'},
    'STRESS': {'loss_prob': 0.25, 'delay_mean_ms': 100.0, 'delay_std_ms': 20.0, 'label': 'Estresse (25% perda, 100ms)'},
}

# Tamanhos de arquivo para Tarefa 4 (1 MB → 10 MB, granularidade fina para estatísticas)
THROUGHPUT_FILE_SIZES_MB = [1, 2, 3, 5, 7, 10]

# Tamanhos de janela para Tarefa 5
WINDOW_SIZES = [1, 2, 4, 8, 16, 32, 64]

# Repetições para convergência estatística (Tarefa 10)
CONVERGENCE_RUNS = 30


@dataclass
class SimConfig:
    """Configuração de uma execução do simulador."""
    file_size_bytes: int = 1_048_576  # 1 MB
    chunk_size: int = 1024
    window_size: int = 16
    timeout_s: float = 2.0
    loss_prob: float = 0.0
    delay_mean_ms: float = 10.0
    delay_std_ms: float = 2.0
    jitter_std_ms: float = 0.0
    scenario: str = 'A'
    seed: int | None = None
    max_retries: int = 500

    @classmethod
    def from_scenario(cls, scenario: str, **kwargs) -> 'SimConfig':
        params = SCENARIOS.get(scenario.upper(), SCENARIOS['A'])
        base = {
            'loss_prob': params['loss_prob'],
            'delay_mean_ms': params['delay_mean_ms'],
            'delay_std_ms': params['delay_std_ms'],
            'scenario': scenario.upper(),
        }
        base.update(kwargs)
        return cls(**base)

    @property
    def num_chunks(self) -> int:
        return (self.file_size_bytes + self.chunk_size - 1) // self.chunk_size
