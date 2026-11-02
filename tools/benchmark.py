"""Reproducible CPU benchmark, excluding IO/LLM time and fixture construction."""
import argparse
from datetime import date, timedelta
import gc
import json
import platform
from pathlib import Path
import statistics
import sys
from time import perf_counter

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from borrowcheck.engine import Invoice, Rules, calculate


def run(count, repeats):
    as_of = date(2026, 10, 31)
    rows = [Invoice(str(i), str(i % 2000), f'Synthetic debtor {i % 2000}',
                    as_of - timedelta(days=(i * 17) % 121), 100000 + i % 50000,
                    i % 50, i % 137 == 0) for i in range(count)]
    rules = Rules(90, 5000, 2000, 8000, 5000000, 100000000000, 'benchmark')
    calculate(rows[:min(1000,count)], rules, as_of)
    times = []
    for _ in range(repeats):
        gc.collect()
        start = perf_counter(); result = calculate(rows, rules, as_of)
        times.append(perf_counter() - start)
        assert result['invariants']['net_equals_exclusions_plus_eligible']
        del result
    median = statistics.median(times)
    return {'invoices':count, 'debtors':min(count,2000), 'repeats':repeats,
            'seconds':times, 'median_seconds':median, 'invoices_per_second':round(count/median)}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--invoices', type=int, default=100000)
    parser.add_argument('--repeats', type=int, default=3)
    parser.add_argument('--out', type=Path)
    args = parser.parse_args()
    if not 1 <= args.invoices <= 1000000 or not 1 <= args.repeats <= 20:
        parser.error('Use 1–1,000,000 invoices and 1–20 repeats')
    report = {'python':platform.python_version(), 'platform':platform.platform(),
              'processor':platform.machine(), 'scope':'Pure engine; excludes IO, source validation, PDF/OCR, network and UI',
              'results':run(args.invoices,args.repeats)}
    text = json.dumps(report, indent=2)+'\n'
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True); args.out.write_text(text)
    print(text)
