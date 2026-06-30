"""Testes unitários do simulador R-UDP SimPy."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from config import SimConfig
from network_models import BernoulliLossModel, DelayModel, NetworkChannel
from rudp_simulator import run_simulation


def test_ideal_scenario_completes():
    cfg = SimConfig.from_scenario('A', file_size_bytes=32 * 1024, seed=1)
    res = run_simulation(cfg)
    assert res.elapsed_s > 0
    assert res.throughput_mbps > 0
    assert res.bytes_sent == cfg.file_size_bytes


def test_loss_increases_retransmissions():
    cfg_a = SimConfig.from_scenario('A', file_size_bytes=64 * 1024, seed=2)
    cfg_c = SimConfig.from_scenario('C', file_size_bytes=64 * 1024, seed=2)
    res_a = run_simulation(cfg_a)
    res_c = run_simulation(cfg_c)
    assert res_c.retransmissions >= res_a.retransmissions


def test_bernoulli_loss_rate():
    model = BernoulliLossModel(0.5, __import__('random').Random(0))
    losses = sum(model.is_lost() for _ in range(10000))
    assert 4500 < losses < 5500


def test_delay_model_non_negative():
    dm = DelayModel(10.0, 2.0)
    for _ in range(100):
        assert dm.sample_delay_s() >= 0


def test_efficiency_ratio_bounds():
    cfg = SimConfig.from_scenario('B', file_size_bytes=16 * 1024, seed=3)
    res = run_simulation(cfg)
    assert 0 < res.efficiency_ratio <= 1.0


def test_window_size_affects_throughput():
    cfg_small = SimConfig.from_scenario('B', file_size_bytes=128 * 1024, window_size=1, seed=4)
    cfg_large = SimConfig.from_scenario('B', file_size_bytes=128 * 1024, window_size=32, seed=4)
    res_small = run_simulation(cfg_small)
    res_large = run_simulation(cfg_large)
    assert res_large.throughput_mbps >= res_small.throughput_mbps * 0.5
