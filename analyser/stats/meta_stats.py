from collections import Counter
from typing import List

from ..helpers import safe_median
from ..models import ImageRecord


def compute_meta_stats(records: List[ImageRecord]) -> dict:
    """Extract cards_detected, slots_built, tokens_found, rectification_used,
    original_shape, OCR settings."""
    cards = [r.meta.cards_detected for r in records]
    slots = [r.meta.slots_built for r in records]
    tokens = [r.meta.tokens_found for r in records]
    rect_used = [r.meta.rectification_used for r in records]
    shapes = [r.meta.original_shape for r in records]
    ocr_modes = [r.meta.ocr.mode for r in records]
    full_passes = [r.meta.ocr.full_passes for r in records]
    crop_passes = [r.meta.ocr.crop_passes for r in records]
    ocr_skipped = [r.meta.ocr.skipped for r in records]

    return {
        'cards': cards,
        'slots': slots,
        'tokens': tokens,
        'rect_used_count': sum(rect_used),
        'rect_total': len(rect_used),
        'shape_counter': Counter(shapes),
        'ocr_mode_counter': Counter(ocr_modes),
        'full_passes_counter': Counter(full_passes),
        'crop_passes_counter': Counter(crop_passes),
        'ocr_skipped_count': sum(ocr_skipped)
    }

def report_meta(stats: dict):
    print("\n" + "=" * 10 + " Meta Statistics " + "=" * 10)

    def print_numeric_field(name: str, values: List[int]):
        if not values:
            return
        print(f"\n{name}:")
        print(f"  Min: {min(values)}, Max: {max(values)}, Mean: {sum(values)/len(values):.2f}, "
              f"Median: {safe_median(values):.2f}")
        cnt = Counter(values)
        print("  Distribution (top 10):")
        for val, c in cnt.most_common(10):
            print(f"    {val}: {c}")

    print_numeric_field("cards_detected", stats['cards'])
    print_numeric_field("slots_built", stats['slots'])
    print_numeric_field("tokens_found", stats['tokens'])

    print(f"\nrectification_used:")
    print(f"  True: {stats['rect_used_count']} ({stats['rect_used_count']/stats['rect_total']*100:.1f}%)")
    print(f"  False: {stats['rect_total'] - stats['rect_used_count']}")

    print("\noriginal_shape (height, width):")
    for shape, cnt in stats['shape_counter'].most_common(10):
        print(f"  {shape}: {cnt}")

    print("\nOCR mode distribution:")
    for mode, cnt in stats['ocr_mode_counter'].items():
        print(f"  {mode}: {cnt}")

    print_numeric_field("OCR full_passes", list(stats['full_passes_counter'].elements()))
    print_numeric_field("OCR crop_passes", list(stats['crop_passes_counter'].elements()))
    total_ocr = sum(stats['ocr_mode_counter'].values())
    print(f"\nOCR skipped: {stats['ocr_skipped_count']} ({stats['ocr_skipped_count']/total_ocr*100:.1f}%)")