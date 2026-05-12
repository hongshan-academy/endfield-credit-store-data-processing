from collections import Counter
from typing import List

from ..helpers import print_counter, safe_median


def compute_refresh_stats(records):
    # Filter out None values for each numeric field
    total_vals = [r.refresh_total for r in records if r.refresh_total is not None]
    remain_vals = [r.refresh_remaining for r in records if r.refresh_remaining is not None]
    time_vals = [r.refresh_remaining_time for r in records if r.refresh_remaining_time is not None]

    # consistency: refresh_remaining > refresh_total (only if both are not None)
    inconsistent = 0
    for r in records:
        if r.refresh_remaining is not None and r.refresh_total is not None:
            if r.refresh_remaining > r.refresh_total:
                inconsistent += 1

    # time bins (time_vals already filtered)
    time_bins = [(0, 60), (60, 300), (300, 600), (600, 1800), (1800, float('inf'))]
    bin_counts = []
    if time_vals:
        total_time = len(time_vals)
        for low, high in time_bins:
            if high == float('inf'):
                cnt = sum(1 for t in time_vals if t >= low)
                label = f">={low}"
            else:
                cnt = sum(1 for t in time_vals if low <= t < high)
                label = f"{low}-{high}"
            bin_counts.append((label, cnt, cnt/total_time*100))
    else:
        bin_counts = [(label, 0, 0) for label, _ in time_bins]

    return {
        'total_counter': Counter(total_vals),
        'remain_counter': Counter(remain_vals),
        'time_vals': time_vals,
        'inconsistent_count': inconsistent,
        'time_bins': bin_counts,
        'zero_time_count': sum(1 for t in time_vals if t == 0)
    }

def report_refresh(stats: dict):
    print("\n" + "=" * 10 + " Refresh Statistics " + "=" * 10)
    print_counter(stats['total_counter'], "refresh_total distribution")
    print_counter(stats['remain_counter'], "refresh_remaining distribution")
    print(f"\nEntries where refresh_remaining > refresh_total: {stats['inconsistent_count']}")

    times = stats['time_vals']
    if times:
        print(f"\nrefresh_remaining_time (seconds):")
        print(f"  Min: {min(times)}, Max: {max(times)}, Mean: {sum(times)/len(times):.2f}, "
              f"Median: {safe_median(times):.2f}")
        print("  Time bins:")
        for label, cnt, pct in stats['time_bins']:
            print(f"    {label}: {cnt} ({pct:.1f}%)")
        print(f"  refresh_remaining_time == 0: {stats['zero_time_count']}")
    else:
        print("\n  No refresh_remaining_time data available.")
