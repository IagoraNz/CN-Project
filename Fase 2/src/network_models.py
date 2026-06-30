"""Modelos estocásticos de rede: atraso normal, perda de Bernoulli e jitter."""
import random
from dataclasses import dataclass

import numpy as np


@dataclass
class DelayModel:
    """Latência modelada por distribuição normal (Tarefa 1)."""

    mean_ms: float
    std_ms: float
    jitter_std_ms: float = 0.0
    rng: random.Random | None = None

    def __post_init__(self):
        self._rng = self.rng or random.Random()

    def sample_delay_s(self) -> float:
        """Amostra atraso one-way em segundos (>= 0)."""
        base_ms = self._rng.gauss(self.mean_ms, self.std_ms)
        if self.jitter_std_ms > 0:
            base_ms += self._rng.gauss(0, self.jitter_std_ms)
        return max(0.0, base_ms / 1000.0)

    def sample_rtt_s(self) -> float:
        """RTT ≈ ida + volta (duas amostras independentes)."""
        return self.sample_delay_s() + self.sample_delay_s()

    def fit_from_samples_ms(self, samples_ms: list[float]) -> None:
        """Ajusta parâmetros a partir de medições reais (Fase 1 / tcpdump)."""
        if not samples_ms:
            return
        arr = np.asarray(samples_ms, dtype=float)
        self.mean_ms = float(np.mean(arr))
        self.std_ms = float(max(np.std(arr, ddof=1), 0.5))


@dataclass
class BernoulliLossModel:
    """Perda de pacotes independente (Tarefa 2)."""

    loss_prob: float
    rng: random.Random | None = None

    def __post_init__(self):
        self._rng = self.rng or random.Random()
        self.loss_prob = max(0.0, min(1.0, self.loss_prob))

    def is_lost(self) -> bool:
        return self._rng.random() < self.loss_prob


@dataclass
class NetworkChannel:
    """Canal que combina atraso normal + perda de Bernoulli."""

    delay: DelayModel
    loss: BernoulliLossModel

    @classmethod
    def from_params(
        cls,
        loss_prob: float,
        delay_mean_ms: float,
        delay_std_ms: float,
        jitter_std_ms: float = 0.0,
        seed: int | None = None,
    ) -> 'NetworkChannel':
        rng = random.Random(seed)
        return cls(
            delay=DelayModel(delay_mean_ms, delay_std_ms, jitter_std_ms, rng),
            loss=BernoulliLossModel(loss_prob, rng),
        )

    def forward(self) -> tuple[bool, float]:
        """Retorna (entregue, atraso_s). Se perdido, atraso=0."""
        if self.loss.is_lost():
            return False, 0.0
        return True, self.delay.sample_delay_s()
