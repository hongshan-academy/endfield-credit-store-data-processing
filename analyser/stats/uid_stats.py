from collections import Counter
from typing import List

from ..helpers import print_counter
from ..models import ImageRecord

def compute_uid_stats(records: List[ImageRecord]) -> dict:
    """Return statistics about UIDs."""
    uid_counter: Counter = Counter()
    uid_len_counter: Counter = Counter()
    for rec in records:
        if rec.uid is not None:
            uid_counter[rec.uid] += 1
            uid_len_counter[len(rec.uid)] += 1
        else:
            uid_counter[None] += 1
    return {
        'uid_counter': uid_counter,
        'uid_len_counter': uid_len_counter,
        'total_records': len(records),
        'null_uid_count': uid_counter.get(None, 0)
    }

def report_uid(stats: dict):
    print("\n" + "=" * 10 + " UID Statistics " + "=" * 10)
    print_counter(stats['uid_counter'], "UID frequency (top 10)")
    print_counter(stats['uid_len_counter'], "UID length distribution")
    print(f"\nRecords with UID = None: {stats['null_uid_count']}")