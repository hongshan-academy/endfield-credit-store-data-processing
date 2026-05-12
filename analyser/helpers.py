from pathlib import Path
import statistics

from collections import Counter

from typing import Iterable


def get_filename_from_path(path: str) -> str:
    return Path(path).name

def safe_median(data: Iterable[float]) -> float:
    return statistics.median(data) if data else 0.0

def print_counter(counter: Counter, title: str, top_n: int = 10):
    print(f"\n{title}:")
    for val, cnt in counter.most_common(top_n):
        print(f"  {val}: {cnt}")