"""Simulador de eventos discretos R-UDP (Go-Back-N) com SimPy — espelha a Fase 1."""
from __future__ import annotations

from dataclasses import dataclass, field

import simpy

from config import SimConfig
from network_models import NetworkChannel


def _seq_le(a: int, b: int) -> bool:
    """True se a <= b no espaço de sequência 16-bit."""
    return ((b - a) & 0xFFFF) <= 32768


@dataclass
class SimulationResult:
    elapsed_s: float
    throughput_mbps: float
    packets_sent: int
    data_packets: int
    ack_packets: int
    retransmissions: int
    packets_lost: int
    bytes_sent: int
    rtt_samples_s: list[float] = field(default_factory=list)
    scenario: str = 'A'
    window_size: int = 16
    file_size_bytes: int = 0
    loss_prob: float = 0.0
    seed: int | None = None

    @property
    def mean_rtt_ms(self) -> float:
        if not self.rtt_samples_s:
            return 0.0
        return sum(self.rtt_samples_s) / len(self.rtt_samples_s) * 1000.0

    @property
    def efficiency_ratio(self) -> float:
        total = self.data_packets + self.ack_packets
        return self.data_packets / total if total else 0.0

    def to_dict(self) -> dict:
        return {
            'elapsed_s': self.elapsed_s,
            'throughput_mbps': self.throughput_mbps,
            'packets_sent': self.packets_sent,
            'data_packets': self.data_packets,
            'ack_packets': self.ack_packets,
            'retransmissions': self.retransmissions,
            'packets_lost': self.packets_lost,
            'bytes_sent': self.bytes_sent,
            'mean_rtt_ms': self.mean_rtt_ms,
            'efficiency_ratio': self.efficiency_ratio,
            'scenario': self.scenario,
            'window_size': self.window_size,
            'file_size_bytes': self.file_size_bytes,
            'loss_prob': self.loss_prob,
            'seed': self.seed,
        }


@dataclass
class _Stats:
    packets_sent: int = 0
    data_packets: int = 0
    ack_packets: int = 0
    retransmissions: int = 0
    packets_lost: int = 0
    rtt_samples_s: list = field(default_factory=list)
    elapsed_s: float = 0.0


class RUDPSimulator:
    """Simula transferência R-UDP Go-Back-N sobre canal estocástico."""

    def __init__(self, config: SimConfig):
        self.config = config
        self.channel = NetworkChannel.from_params(
            config.loss_prob,
            config.delay_mean_ms,
            config.delay_std_ms,
            config.jitter_std_ms,
            config.seed,
        )

    def run(self) -> SimulationResult:
        env = simpy.Environment()
        cfg = self.config
        stats = _Stats()
        num_chunks = cfg.num_chunks

        uplink_in = simpy.Store(env)
        uplink = simpy.Store(env)
        ack_in = simpy.Store(env)
        downlink = simpy.Store(env)

        # ACK buffer: collector process drains downlink → Python list + event signal.
        # This avoids the phantom-get accumulation that occurs when downlink.get()
        # events are abandoned on timeout without cancellation.
        ack_buffer: list = []
        ack_signal = env.event()
        fin_flag: list[bool] = [False]

        def ack_collector():
            while True:
                ack = yield downlink.get()
                if ack.get('fin'):
                    fin_flag[0] = True
                else:
                    ack_buffer.append(ack)
                if not ack_signal.triggered:
                    ack_signal.succeed()

        def _put_delayed(store_out: simpy.Store, msg: dict, wait: float):
            if wait > 0:
                yield env.timeout(wait)
            yield store_out.put(msg)

        def forward(store_in: simpy.Store, store_out: simpy.Store):
            # FIFO channel with per-packet random delay.
            # Packets travel concurrently but cannot overtake each other:
            #   arrival_i = max(now + delay_i, prev_arrival)
            # This matches a real single-path network where jitter adds delay
            # variation without reordering — which GBN requires to avoid spurious
            # retransmissions (receiver discards out-of-order packets).
            next_arrival = [0.0]
            while True:
                msg = yield store_in.get()
                delivered, delay = self.channel.forward()
                if not delivered:
                    stats.packets_lost += 1
                    continue
                arrival = max(env.now + delay, next_arrival[0])
                next_arrival[0] = arrival
                env.process(_put_delayed(store_out, msg, arrival - env.now))

        def receiver():
            recv_seq = 0
            while True:
                pkt = yield uplink.get()
                ptype = pkt['type']
                seq = pkt['seq']
                if ptype == 'syn':
                    stats.ack_packets += 1
                    yield ack_in.put({'type': 'ack', 'ack': seq})
                    recv_seq = 1
                elif ptype == 'data':
                    if seq == recv_seq:
                        recv_seq = (recv_seq + 1) & 0xFFFF
                    stats.ack_packets += 1
                    yield ack_in.put({'type': 'ack', 'ack': (recv_seq - 1) & 0xFFFF})
                elif ptype == 'fin':
                    stats.ack_packets += 1
                    yield ack_in.put({'type': 'ack', 'ack': seq, 'fin': True})
                    return

        def _reset_signal():
            nonlocal ack_signal
            ack_signal = env.event()
            # Re-arm immediately if buffer still has items or fin arrived.
            if ack_buffer or fin_flag[0]:
                ack_signal.succeed()

        def sender():
            nonlocal ack_signal
            send_base = 1
            send_seq = 1
            next_chunk = 0
            unacked: dict[int, tuple[float, int]] = {}
            start = env.now

            def drain_acks():
                nonlocal send_base
                while ack_buffer:
                    ack = ack_buffer.pop(0)
                    acked = ack['ack']
                    for s in list(unacked.keys()):
                        if _seq_le(s, acked):
                            sent_t, _ = unacked.pop(s)
                            stats.rtt_samples_s.append(env.now - sent_t)
                    new_base = (acked + 1) & 0xFFFF
                    # Only advance: out-of-order ACKs (parallel delivery with
                    # different delays) must never regress send_base.
                    if _seq_le(send_base, new_base):
                        send_base = new_base

            # SYN handshake
            syn_retries = 0
            while True:
                stats.packets_sent += 1
                yield uplink_in.put({'type': 'syn', 'seq': 0})
                yield ack_signal | env.timeout(cfg.timeout_s)
                _reset_signal()
                if ack_buffer:
                    drain_acks()
                    break
                syn_retries += 1
                stats.retransmissions += 1
                if syn_retries >= 10:
                    raise RuntimeError('SYN timeout')

            # Data transfer — Go-Back-N
            while next_chunk < num_chunks or unacked:
                drain_acks()

                while ((send_seq - send_base) & 0xFFFF) < cfg.window_size and next_chunk < num_chunks:
                    unacked[send_seq] = (env.now, 0)
                    stats.packets_sent += 1
                    stats.data_packets += 1
                    yield uplink_in.put({'type': 'data', 'seq': send_seq, 'chunk': next_chunk})
                    send_seq = (send_seq + 1) & 0xFFFF
                    next_chunk += 1

                if next_chunk >= num_chunks and not unacked:
                    break

                yield ack_signal | env.timeout(cfg.timeout_s)
                _reset_signal()
                drain_acks()

                # Retransmit timed-out unacked packets (Go-Back-N).
                # max_retries guards against infinite loops: the limit is global
                # (total retransmissions), not per-packet, because in GBN every
                # timeout retransmits the full window, inflating per-seq counters.
                if stats.retransmissions > cfg.max_retries * max(num_chunks, 1):
                    raise RuntimeError(
                        f'Global retransmission limit exceeded ({stats.retransmissions})'
                    )
                for seq in sorted(unacked.keys()):
                    t_sent, retries = unacked[seq]
                    if env.now - t_sent >= cfg.timeout_s:
                        stats.retransmissions += 1
                        stats.packets_sent += 1
                        unacked[seq] = (env.now, retries + 1)
                        yield uplink_in.put({
                            'type': 'data', 'seq': seq,
                            'chunk': (seq - 1) % max(num_chunks, 1),
                        })

            # FIN handshake with retries.
            # Reset ack_signal here to clear any pre-triggered state from the
            # last data-loop iteration (the signal may have been armed by a late
            # ACK that arrived after drain_acks already emptied the buffer).
            _reset_signal()
            fin_retries = 0
            while not fin_flag[0]:
                stats.packets_sent += 1
                yield uplink_in.put({'type': 'fin', 'seq': send_seq})
                yield ack_signal | env.timeout(cfg.timeout_s)
                _reset_signal()
                if fin_flag[0]:
                    break
                fin_retries += 1
                stats.retransmissions += 1
                if fin_retries >= 20:
                    break

            stats.elapsed_s = env.now - start

        env.process(ack_collector())
        env.process(forward(uplink_in, uplink))
        env.process(forward(ack_in, downlink))
        env.process(receiver())
        env.process(sender())
        env.run()

        elapsed = stats.elapsed_s
        return SimulationResult(
            elapsed_s=elapsed,
            throughput_mbps=(cfg.file_size_bytes * 8 / elapsed / 1e6) if elapsed > 0 else 0.0,
            packets_sent=stats.packets_sent,
            data_packets=stats.data_packets,
            ack_packets=stats.ack_packets,
            retransmissions=stats.retransmissions,
            packets_lost=stats.packets_lost,
            bytes_sent=cfg.file_size_bytes,
            rtt_samples_s=stats.rtt_samples_s,
            scenario=cfg.scenario,
            window_size=cfg.window_size,
            file_size_bytes=cfg.file_size_bytes,
            loss_prob=cfg.loss_prob,
            seed=cfg.seed,
        )


def run_simulation(config: SimConfig) -> SimulationResult:
    return RUDPSimulator(config).run()
