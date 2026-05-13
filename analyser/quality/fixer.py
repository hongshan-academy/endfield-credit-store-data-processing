# analyser/quality/fixer.py

import json
from copy import deepcopy
from pathlib import Path
from typing import List, Tuple, Dict, Any, Optional, DefaultDict, cast
from collections import defaultdict

from ..models import ImageRecord, Item
from .price_validator import (
    BASE_PRICE,
    ALLOWED_DISCOUNTS,
    get_chinese_name,
    floor_expected,
    split_price_candidate,
    levenshtein,
    prefix_suffix_match,
    classify_price_detailed,
)

# Categories that should NEVER be fixed (preserve original OCR)
UNFIXABLE_CATEGORIES = {"missing_discount", "other_error"}


# ------------------------------------------------------------------
# Candidate cost computation
# ------------------------------------------------------------------

def compute_candidate_cost(item: Item, base_price: int, discount: int) -> float:
    """Compute cost of assigning a specific discount (and its derived price) to an item."""
    expected_price = floor_expected(base_price, discount)
    actual_price = item.price
    actual_discount = item.discount_percent
    cost = 0.0

    # Price matching
    if actual_price is not None:
        if actual_price == expected_price:
            cost += 0.0
        elif abs(actual_price - expected_price) == 1:
            cost += 1.0
        else:
            actual_str = str(actual_price)
            exp_str = str(expected_price)
            if levenshtein(actual_str, exp_str) <= 1:
                cost += 1.0
            elif prefix_suffix_match(actual_str, expected_price):
                cost += 0.5
            elif actual_price > 999 and split_price_candidate(actual_price, expected_price, base_price):
                cost += 0.5
            else:
                cost += min(10.0, abs(actual_price - expected_price) * 0.5)
    else:
        cost += 2.0

    # Discount matching
    if actual_discount is not None:
        if actual_discount == discount:
            cost += 0.0
        else:
            cost += 1.0
    else:
        cost += 0.5

    return cost


def get_candidates_with_cost(item: Item, base_price: int) -> List[Tuple[int, float]]:
    """Return list of (discount, cost) for all allowed discounts."""
    candidates = []
    for d in ALLOWED_DISCOUNTS:
        price = floor_expected(base_price, d)
        if price > 0:
            cost = compute_candidate_cost(item, base_price, d)
            candidates.append((d, cost))
    # Fallback (shouldn't happen)
    if not candidates and item.discount_percent is not None:
        candidates.append((item.discount_percent, 0.0))
    return candidates


# ------------------------------------------------------------------
# DP for a list of fixable items (returns list of int discounts)
# ------------------------------------------------------------------

def dp_for_fixable_items(
    items: List[Item],
    base_prices: List[int],
) -> List[int]:
    """
    Run monotonic DP on a sequence of fixable items.
    Returns a list of chosen discounts (int, always one of ALLOWED_DISCOUNTS).
    """
    n = len(items)
    assert n == len(base_prices)
    if n == 0:
        return []

    candidates_per_item = [get_candidates_with_cost(items[i], base_prices[i]) for i in range(n)]
    discount_matrix = [[c[0] for c in cand] for cand in candidates_per_item]
    cost_matrix = [[c[1] for c in cand] for cand in candidates_per_item]
    lens = [len(c) for c in candidates_per_item]

    INF = 1e9
    dp = [[INF] * lens[i] for i in range(n)]
    prev = [[-1] * lens[i] for i in range(n)]

    # Base case
    for j in range(lens[0]):
        dp[0][j] = cost_matrix[0][j]

    # Transition
    for i in range(1, n):
        for j in range(lens[i]):
            best_prev = -1
            best_cost = INF
            cur_disc = discount_matrix[i][j]
            for k in range(lens[i-1]):
                if discount_matrix[i-1][k] >= cur_disc:
                    total = dp[i-1][k] + cost_matrix[i][j]
                    if total < best_cost:
                        best_cost = total
                        best_prev = k
            if best_prev != -1:
                dp[i][j] = best_cost
                prev[i][j] = best_prev

    # Backtrack
    chosen_discounts: List[int] = [0] * n   # default discount 0

    if n == 1:
        best_last = min(range(lens[0]), key=lambda j: dp[0][j])
        chosen_discounts[0] = discount_matrix[0][best_last]
    else:
        valid_last = [j for j in range(lens[-1]) if dp[-1][j] < INF]
        if valid_last:
            best_last = min(valid_last, key=lambda j: dp[-1][j])
            idx = best_last
            for i in range(n-1, -1, -1):
                chosen_discounts[i] = discount_matrix[i][idx]
                if i > 0:
                    idx = prev[i][idx]
        else:
            # No feasible monotonic path: independent best per item
            for i in range(n):
                if candidates_per_item[i]:
                    best_disc = min(candidates_per_item[i], key=lambda x: x[1])[0]
                    chosen_discounts[i] = best_disc
    return chosen_discounts


# ------------------------------------------------------------------
# Main fix function with monotonicity per sold_out group
# ------------------------------------------------------------------

def global_fix_with_monotonicity(records: List[ImageRecord]) -> Tuple[List[ImageRecord], Dict[str, Any]]:
    new_records = []
    by_category: DefaultDict[str, int] = defaultdict(int)
    fixed_items_total = 0

    for rec in records:
        # Sort items by (row, col)
        items_sorted = sorted(rec.items, key=lambda x: (x.row, x.col))
        n = len(items_sorted)
        if n == 0:
            new_records.append(rec)
            continue

        # Precompute per-item data
        base_prices: List[Optional[int]] = []      # None for unknown items
        fixable_flags: List[bool] = []
        categories: List[str] = []
        for item in items_sorted:
            ch_name = get_chinese_name(item)
            if ch_name not in BASE_PRICE:
                base_prices.append(None)
                fixable_flags.append(False)
                categories.append("unknown_name")
                continue
            cat, _, _, _ = classify_price_detailed(item, max_discount=100)
            categories.append(cat)
            is_fixable = cat not in UNFIXABLE_CATEGORIES
            fixable_flags.append(is_fixable)
            base_prices.append(BASE_PRICE[ch_name])
            by_category[cat] += 1

        # Start with a copy of the original items (we will modify in place)
        new_items = deepcopy(items_sorted)

        # Process non-sold_out and sold_out groups separately
        for sold_out_flag in (False, True):
            # Indices of items with this sold_out status
            indices = [i for i, it in enumerate(items_sorted) if it.sold_out == sold_out_flag]
            if not indices:
                continue

            # Among these, collect fixable indices
            fixable_indices = [idx for idx in indices if fixable_flags[idx]]
            if not fixable_indices:
                # No fixable items → nothing to do for this group
                continue

            # Extract fixable items and their base prices (base_prices[idx] is not None here)
            fixable_items = [items_sorted[idx] for idx in fixable_indices]
            fixable_bases = [base_prices[idx] for idx in fixable_indices]
            # fixable_bases are List[int] because idx is fixable => base_prices[idx] is int

            # Run DP to get chosen discounts for these fixable items
            chosen_discounts = dp_for_fixable_items(fixable_items, fixable_bases) # type: ignore[arg-type]

            # Map original index to chosen discount
            discount_map = {fixable_indices[k]: chosen_discounts[k] for k in range(len(fixable_indices))}

            # Apply fixes to the new_items list
            for idx in indices:
                if idx in discount_map:
                    chosen_disc = discount_map[idx]
                    base_price = base_prices[idx]
                    # base_price is not None because idx is fixable
                    if base_price is None:
                        continue  # safety
                    cat = categories[idx]
                    expected_price = floor_expected(base_price, chosen_disc)

                    new_item = new_items[idx]   # already a deepcopy
                    fixed = False

                    # Apply changes
                    if cat in ("close_match_pm1", "prefix_suffix_match_pm1"):
                        # Keep original price, only update discount and original_price
                        if new_item.discount_percent != chosen_disc:
                            new_item.discount_percent = chosen_disc
                            fixed = True
                        if new_item.original_price != base_price:
                            new_item.original_price = base_price
                            fixed = True
                    else:
                        # Normal case: set price, discount, original_price
                        if new_item.price != expected_price:
                            new_item.price = expected_price
                            fixed = True
                        if new_item.discount_percent != chosen_disc:
                            new_item.discount_percent = chosen_disc
                            fixed = True
                        if new_item.original_price != base_price:
                            new_item.original_price = base_price
                            fixed = True
                    if fixed:
                        fixed_items_total += 1

        # Rebuild record
        new_rec = ImageRecord(
            image_path=rec.image_path,
            uid=rec.uid,
            refresh_remaining=rec.refresh_remaining,
            refresh_remaining_time=rec.refresh_remaining_time,
            refresh_total=rec.refresh_total,
            items=new_items,
            meta=rec.meta,
        )
        new_records.append(new_rec)

    fix_stats = {
        "total_items": sum(by_category.values()),
        "fixed_items": fixed_items_total,
        "by_category": dict(by_category),
        "fix_applied": {"global_monotonic": fixed_items_total},
    }
    return new_records, fix_stats


def fix_all_items(records: List[ImageRecord]) -> Tuple[List[ImageRecord], Dict[str, Any]]:
    """Public entry point for fixing price/discount information."""
    return global_fix_with_monotonicity(records)


def save_fixed_records(records: List[ImageRecord], output_path: Path) -> None:
    """Save fixed records to a JSON file."""
    data = []
    for rec in records:
        rec_dict = {
            "image_path": rec.image_path,
            "uid": rec.uid,
            "refresh_remaining": rec.refresh_remaining,
            "refresh_remaining_time": rec.refresh_remaining_time,
            "refresh_total": rec.refresh_total,
            "items": [
                {
                    "id": it.id,
                    "row": it.row,
                    "col": it.col,
                    "name": it.name,
                    "name_confidence": it.name_confidence,
                    "name_source": it.name_source,
                    "name_occluded": it.name_occluded,
                    "price": it.price,
                    "original_price": it.original_price,
                    "price_panel_present": it.price_panel_present,
                    "discount_percent": it.discount_percent,
                    "quantity": it.quantity,
                    "sold_out": it.sold_out,
                }
                for it in rec.items
            ],
            "meta": {
                "original_shape": list(rec.meta.original_shape),
                "cards_detected": rec.meta.cards_detected,
                "slots_built": rec.meta.slots_built,
                "tokens_found": rec.meta.tokens_found,
                "rectification_used": rec.meta.rectification_used,
                "ocr": {
                    "skipped": rec.meta.ocr.skipped,
                    "mode": rec.meta.ocr.mode,
                    "full_passes": rec.meta.ocr.full_passes,
                    "crop_passes": rec.meta.ocr.crop_passes,
                    "tokens_found": rec.meta.ocr.tokens_found,
                },
            },
        }
        data.append(rec_dict)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    print(f"Saved fixed records to {output_path}")