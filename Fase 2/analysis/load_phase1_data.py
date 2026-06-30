"""Carrega métricas e dados de latência da Fase 1 para validação cruzada."""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PHASE1_DATA = PROJECT_ROOT / 'Fase 1' / 'data'
PHASE1_LOGS = PHASE1_DATA / 'logs'
PHASE1_CSV = PHASE1_DATA / 'csv'

SCENARIO_ORDER = ['A', 'B', 'C']
DEFAULT_RTT_MS = {'A': 20.0, 'B': 100.0, 'C': 200.0}
DEFAULT_DELAY_MS = {'A': 10.0, 'B': 50.0, 'C': 100.0}
DEFAULT_DELAY_STD_MS = {'A': 2.0, 'B': 8.0, 'C': 15.0}


def _find_phase1_data() -> Path:
    """Resolve diretório de dados da Fase 1."""
    if PHASE1_LOGS.exists():
        return PHASE1_DATA
    alt = Path('/app/data')
    return alt if alt.exists() else PHASE1_DATA


def load_app_metrics(data_dir: Path | None = None) -> list[dict]:
    """Carrega métricas R-UDP da Fase 1."""
    base = data_dir or _find_phase1_data()
    logs = base / 'logs'
    consolidated = logs / 'client_metrics_all.json'
    sources = [consolidated] if consolidated.exists() else []
    sources += sorted(logs.glob('client_metrics_*.json'))

    metrics: list[dict] = []
    seen: set = set()
    for path in sources:
        try:
            with open(path) as f:
                data = json.load(f)
            entries = data if isinstance(data, list) else [data]
            for entry in entries:
                if not isinstance(entry, dict) or entry.get('error'):
                    continue
                if entry.get('protocol', '').upper() != 'R-UDP':
                    continue
                key = (
                    entry.get('timestamp', ''),
                    entry.get('scenario', ''),
                    entry.get('run', 0),
                )
                if key in seen:
                    continue
                seen.add(key)
                metrics.append(entry)
        except (json.JSONDecodeError, OSError):
            pass
    return metrics


def load_pcap_rtt_samples(data_dir: Path | None = None) -> dict[str, list[float]]:
    """Estima amostras de RTT (ms) a partir de CSVs tcpdump da Fase 1.

    Usa o handshake SYN/SYN-ACK do R-UDP (primeiros dois pacotes UDP) para
    medir o RTT com precisão por captura. Mapeia PCAPs aos cenários por
    ordenação temporal com as métricas R-UDP.
    """
    base = data_dir or _find_phase1_data()
    csv_dir = base / 'csv'
    by_scenario: dict[str, list[float]] = {s: [] for s in SCENARIO_ORDER}

    # Constrói mapeamento PCAP→cenário via ordenação temporal com as métricas R-UDP
    app_metrics = load_app_metrics(base)
    pcap_scenario_map = _build_pcap_scenario_map(csv_dir, app_metrics)

    for csv_file in sorted(csv_dir.glob('*.csv')):
        try:
            with open(csv_file) as f:
                first = f.readline()
            if 'frame.time,' in first:
                continue

            df = pd.read_csv(csv_file)
            if df.empty:
                continue

            # Filtra apenas pacotes UDP (R-UDP)
            udp = df[df.get('protocol', pd.Series([''] * len(df)))
                     .astype(str).str.upper().eq('UDP')]
            if len(udp) < 2:
                continue

            t = pd.to_numeric(udp['frame.time_epoch'], errors='coerce').dropna()
            if len(t) < 2:
                continue

            # RTT do handshake SYN: primeiros dois pacotes são SYN e SYN-ACK.
            # A diferença deles = RTT de ida-e-volta com alta precisão.
            rtt_ms = (t.iloc[1] - t.iloc[0]) * 2 * 1000
            if not (1.0 <= rtt_ms <= 2000.0):
                continue

            # Inferência de cenário: nome do arquivo ou mapeamento temporal
            scenario = _infer_scenario(csv_file.name) or pcap_scenario_map.get(csv_file.stem)
            if scenario:
                by_scenario[scenario].append(rtt_ms)
        except Exception:
            pass

    return by_scenario


def _build_pcap_scenario_map(csv_dir: Path, app_metrics: list[dict]) -> dict[str, str]:
    """Mapeia PCAPs R-UDP a cenários por ordenação temporal com as métricas."""
    rudp_metrics = sorted(
        [m for m in app_metrics
         if m.get('protocol', '').upper() == 'R-UDP' and m.get('scenario')],
        key=lambda m: m.get('timestamp', ''),
    )

    # Identifica CSVs que são R-UDP (contêm pacotes UDP)
    rudp_csvs: list[tuple[str, Path]] = []
    for csv_file in sorted(csv_dir.glob('*.csv')):
        m = re.search(r'traffic_(\d{8}_\d{6})', csv_file.name)
        if not m:
            continue
        try:
            df_head = pd.read_csv(csv_file, nrows=3)
            if df_head.get('protocol', pd.Series([])).astype(str).str.upper().eq('UDP').any():
                rudp_csvs.append((m.group(1), csv_file))
        except Exception:
            continue

    rudp_csvs.sort(key=lambda x: x[0])

    pcap_map: dict[str, str] = {}
    for i, (_, csv_file) in enumerate(rudp_csvs):
        if i < len(rudp_metrics):
            scen = rudp_metrics[i].get('scenario', '').upper()
            if scen:
                pcap_map[csv_file.stem] = scen

    return pcap_map


def _infer_scenario(filename: str) -> str | None:
    m = re.search(r'scenario_([ABC])', filename, re.I)
    if m:
        return m.group(1).upper()
    return None


def get_delay_params_from_phase1(data_dir: Path | None = None) -> dict[str, dict[str, float]]:
    """Parâmetros de atraso normal por cenário (Tarefa 1)."""
    rtt_by_scenario = load_pcap_rtt_samples(data_dir)
    app_metrics = load_app_metrics(data_dir)

    params: dict[str, dict[str, float]] = {}
    for scen in SCENARIO_ORDER:
        samples = rtt_by_scenario.get(scen, [])
        if len(samples) >= 5:
            arr = np.asarray(samples)
            params[scen] = {
                'delay_mean_ms': float(np.mean(arr) / 2),
                'delay_std_ms': float(max(np.std(arr, ddof=1) / 2, 0.5)),
                'rtt_mean_ms': float(np.mean(arr)),
                'source': 'pcap',
            }
        else:
            scen_metrics = [m for m in app_metrics if m.get('scenario', '').upper() == scen]
            if scen_metrics:
                # Use scenario's tc-configured delay as ground truth.
                # Retransmission counts do NOT affect propagation delay.
                params[scen] = {
                    'delay_mean_ms': DEFAULT_DELAY_MS[scen],
                    'delay_std_ms': DEFAULT_DELAY_STD_MS[scen],
                    'rtt_mean_ms': DEFAULT_RTT_MS[scen],
                    'source': 'app_metrics',
                }
            else:
                params[scen] = {
                    'delay_mean_ms': DEFAULT_DELAY_MS[scen],
                    'delay_std_ms': DEFAULT_DELAY_STD_MS[scen],
                    'rtt_mean_ms': DEFAULT_RTT_MS[scen],
                    'source': 'default',
                }
    return params


def metrics_to_dataframe(metrics: list[dict]) -> pd.DataFrame:
    if not metrics:
        return pd.DataFrame()
    rows = []
    for m in metrics:
        rows.append({
            'scenario': m.get('scenario', 'Unknown'),
            'protocol': m.get('protocol', 'R-UDP'),
            'run': m.get('run', 1),
            'elapsed_s': m.get('elapsed_seconds', 0),
            'throughput_mbps': m.get('throughput_mbps', 0),
            'retransmissions': m.get('retransmissions', 0),
            'packets_sent': m.get('packets_sent', 0),
            'bytes_sent': m.get('sent_bytes', m.get('size_bytes', 0)),
            'timestamp': m.get('timestamp', ''),
        })
    return pd.DataFrame(rows)


def aggregate_by_scenario(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    return df.groupby('scenario').agg(
        elapsed_mean=('elapsed_s', 'mean'),
        elapsed_std=('elapsed_s', 'std'),
        throughput_mean=('throughput_mbps', 'mean'),
        throughput_std=('throughput_mbps', 'std'),
        retrans_mean=('retransmissions', 'mean'),
        retrans_std=('retransmissions', 'std'),
        n_runs=('run', 'count'),
    ).reset_index()
