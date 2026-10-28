#!/usr/bin/env python3
"""Write a small, clearly-labelled SYNTHETIC POD5 file with the official pod5 Writer API.

The signal is Gaussian noise (no biological or physical meaning); sample_id, experiment_name and
every other free-text run field say SYNTHETIC. Signal and read IDs come from a fixed numpy seed, but
the bytes differ between runs because pod5 writes a random file identifier and section marker.

    pip install "pod5==0.3.49"
    python scripts/make_synthetic_pod5.py examples/synthetic
"""
import argparse
import datetime
import sys
import uuid
from pathlib import Path

import numpy as np
import pod5

NAME = "SYNTHETIC_nanopore_signal.pod5"
SAMPLE_RATE = 5000
READ_SAMPLES = (250_000, 20_000, 15_000, 10_000, 4_000)
# Timezone-aware: the Writer converts naive datetimes as local time.
START = datetime.datetime(2026, 1, 2, 3, 4, 5, tzinfo=datetime.UTC)


def run_info() -> pod5.RunInfo:
    return pod5.RunInfo(
        acquisition_id="SYNTHETIC-acquisition-0000",
        acquisition_start_time=START,
        adc_max=4095,
        adc_min=-4096,
        context_tags={"experiment_type": "SYNTHETIC", "sample_frequency": str(SAMPLE_RATE)},
        experiment_name="SYNTHETIC",
        flow_cell_id="SYNTHETIC-FC",
        flow_cell_product_code="SYNTHETIC-FLO",
        protocol_name="SYNTHETIC-protocol",
        protocol_run_id="SYNTHETIC-protocol-run-0000",
        protocol_start_time=START,
        sample_id="SYNTHETIC",
        sample_rate=SAMPLE_RATE,
        sequencing_kit="SYNTHETIC-KIT",
        sequencer_position="SYNTHETIC-position",
        sequencer_position_type="SYNTHETIC",
        software="ARVA make_synthetic_pod5.py",
        system_name="SYNTHETIC-system",
        system_type="SYNTHETIC",
        tracking_id={"run_id": "SYNTHETIC-protocol-run-0000"},
    )


def write(path: Path, seed: int = 20240501) -> None:
    rng = np.random.default_rng(seed)
    info = run_info()
    reads = []
    start = 0
    for i, n in enumerate(READ_SAMPLES):
        reads.append(
            pod5.Read(
                read_id=uuid.UUID(bytes=rng.bytes(16), version=4),
                pore=pod5.Pore(channel=i + 1, well=1, pore_type="SYNTHETIC"),
                calibration=pod5.Calibration(offset=-240.0, scale=0.1462),
                read_number=i,
                start_sample=start,
                median_before=200.0,
                end_reason=pod5.EndReason(pod5.EndReasonEnum.SIGNAL_POSITIVE, False),
                run_info=info,
                signal=rng.normal(500, 40, n).astype(np.int16),
            )
        )
        start += n + 1000
    with pod5.Writer(path) as writer:
        writer.add_reads(reads)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("out_dir", type=Path)
    out = ap.parse_args().out_dir / NAME
    if out.exists():
        sys.exit(f"{out} already exists; delete it first (nothing was changed)")
    out.parent.mkdir(parents=True, exist_ok=True)
    write(out)
    print(f"wrote {out} ({out.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
