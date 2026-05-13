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
# Cost parameters (adjustable)
# ------------------------------------------------------------------

# Price matching costs
COST_PRICE_EXACT = 0.0
COST_PRICE_OFF_BY_1 = 1.0
COST_PRICE_EDIT_DISTANCE_LE1 = 1.0
COST_PRICE_PREFIX_SUFFIX_MATCH = 5.0          # was 0.5, increased to discourage unreasonable changes
COST_PRICE_SPLIT_CANDIDATE = 0.5
COST_PRICE_OTHER = lambda diff: min(10.0, diff * 0.5)  # diff = abs(actual - expected)
COST_PRICE_MISSING = 2.0                      # when actual price is None

# Discount matching costs
COST_DISCOUNT_EXACT = 0.0
COST_DISCOUNT_MISMATCH = 1.0
COST_DISCOUNT_CHANGE_PENALTY = 10.0           # extra penalty when changing discount
COST_DISCOUNT_MISSING = 0.5                   # when discount is None

# DP parameters
DP_MAX_99_COUNT = 3
DP_PENALTY_PER_99 = 1.0

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
            cost += COST_PRICE_EXACT
        elif abs(actual_price - expected_price) == 1:
            cost += COST_PRICE_OFF_BY_1
        else:
            actual_str = str(actual_price)
            exp_str = str(expected_price)
            if levenshtein(actual_str, exp_str) <= 1:
                cost += COST_PRICE_EDIT_DISTANCE_LE1
            elif prefix_suffix_match(actual_str, expected_price):
                cost += COST_PRICE_PREFIX_SUFFIX_MATCH
            elif actual_price > 999 and split_price_candidate(actual_price, expected_price, base_price):
                cost += COST_PRICE_SPLIT_CANDIDATE
            else:
                diff = abs(actual_price - expected_price)
                cost += COST_PRICE_OTHER(diff)
    else:
        cost += COST_PRICE_MISSING

    # Discount matching
    if actual_discount is not None:
        if actual_discount == discount:
            cost += COST_DISCOUNT_EXACT
        else:
            cost += COST_DISCOUNT_MISMATCH
            cost += COST_DISCOUNT_CHANGE_PENALTY
    else:
        cost += COST_DISCOUNT_MISSING

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
    first_fixed_discount: Optional[int] = None,
    max_99_count: int = DP_MAX_99_COUNT,
    penalty_per_99: float = DP_PENALTY_PER_99,
) -> List[int]:
    """
    Run monotonic DP on a sequence of fixable items.
    
    Args:
        items: List of items
        base_prices: Corresponding base prices (must be same length)
        first_fixed_discount: If provided and valid, force first item to this discount.
        max_99_count: Maximum allowed number of discount=99 in the sequence.
        penalty_per_99: Additional cost per occurrence of discount=99.
    
    Returns:
        List of chosen discounts (int, allowed discounts).
    """
    n = len(items)
    assert n == len(base_prices)
    if n == 0:
        return []

    # Helper to get candidates, optionally with max discount cap
    def get_candidates_with_cap(item: Item, base: int, max_disc: Optional[int] = None):
        cand = []
        for d in ALLOWED_DISCOUNTS:
            if max_disc is not None and d > max_disc:
                continue
            price = floor_expected(base, d)
            if price > 0:
                cost = compute_candidate_cost(item, base, d)
                cand.append((d, cost))
        return cand

    # Build candidate lists, respecting first_fixed_discount if given
    fixed_valid = (first_fixed_discount is not None and 
                   first_fixed_discount in ALLOWED_DISCOUNTS)
    if fixed_valid and n >= 1:
        # First item forced to fixed discount, with zero cost
        first_price = floor_expected(base_prices[0], first_fixed_discount)
        if first_price <= 0:
            # fallback: ignore fixed requirement
            candidates_per_item: List[List[Tuple[int, float]]] = [
                get_candidates_with_cap(items[i], base_prices[i], None)
                for i in range(n)
            ]
        else:
            first_disc = cast(int, first_fixed_discount)
            first_cand: List[Tuple[int, float]] = [(first_disc, 0.0)]
            rest_cands: List[List[Tuple[int, float]]] = [
                get_candidates_with_cap(items[i], base_prices[i], first_disc)
                for i in range(1, n)
            ]
            candidates_per_item = [first_cand] + rest_cands
    else:
        candidates_per_item: List[List[Tuple[int, float]]] = [
            get_candidates_with_cap(items[i], base_prices[i], None)
            for i in range(n)
        ]

    discount_matrix: List[List[int]] = [[int(c[0]) for c in cand] for cand in candidates_per_item]
    base_cost_matrix: List[List[float]] = [[float(c[1]) for c in cand] for cand in candidates_per_item]
    lens = [len(c) for c in candidates_per_item]

    INF = 1e9
    max_k = max_99_count + 1
    # dp[i][j][k] = min total cost for first i+1 items, item i choosing candidate j, with exactly k discounted 99
    dp = [[[INF] * max_k for _ in range(lens[i])] for i in range(n)]
    # prev stores (prev_j, prev_k)
    prev = [[[(-1, -1)] * max_k for _ in range(lens[i])] for i in range(n)]

    # Base
    for j in range(lens[0]):
        disc0 = discount_matrix[0][j]
        is99 = 1 if disc0 == 99 else 0
        if is99 <= max_99_count:
            cost0 = base_cost_matrix[0][j] + (penalty_per_99 if is99 else 0.0)
            dp[0][j][is99] = cost0
            # prev stays (-1,-1)

    # Transition
    for i in range(1, n):
        for j in range(lens[i]):
            cur_disc = discount_matrix[i][j]
            cur_is99 = 1 if cur_disc == 99 else 0
            for prev_k in range(max_k):
                new_k = prev_k + cur_is99
                if new_k >= max_k:
                    continue
                best_prev_cost = INF
                best_prev_j = -1
                for k in range(lens[i-1]):
                    prev_disc = discount_matrix[i-1][k]
                    if prev_disc >= cur_disc:
                        prev_cost = dp[i-1][k][prev_k]
                        if prev_cost < best_prev_cost:
                            best_prev_cost = prev_cost
                            best_prev_j = k
                if best_prev_j != -1:
                    total = best_prev_cost + base_cost_matrix[i][j] + (penalty_per_99 if cur_is99 else 0.0)
                    if total < dp[i][j][new_k]:
                        dp[i][j][new_k] = total
                        prev[i][j][new_k] = (best_prev_j, prev_k)

    # Backtrack: find best final state (any valid k)
    best_last_cost = INF
    best_last_j = -1
    best_last_k = -1
    for j in range(lens[-1]):
        for k in range(max_k):
            if dp[-1][j][k] < best_last_cost:
                best_last_cost = dp[-1][j][k]
                best_last_j = j
                best_last_k = k

    chosen = [0] * n
    if best_last_j != -1:
        j = best_last_j
        k = best_last_k
        for i in range(n-1, -1, -1):
            chosen[i] = discount_matrix[i][j]
            if i > 0:
                j, k = prev[i][j][k]
    else:
        # Fallback: per-item best ignoring 99 count (but still monotonic? simpler: per-item best)
        for i in range(n):
            if candidates_per_item[i]:
                best = cast(int, min(candidates_per_item[i], key=lambda x: x[1])[0])
                chosen[i] = best
    return chosen


# ------------------------------------------------------------------
# Main fix function with monotonicity per sold_out group
# ------------------------------------------------------------------
def _apply_fixes_to_block(
    block_indices: List[int],
    fixable_indices: List[int],
    chosen_discounts: List[int],
    items_sorted: List[Item],
    new_items: List[Item],
    base_prices: List[Optional[int]],
    categories: List[str],
) -> int:
    """
    Apply chosen discounts to a contiguous block (prefix or suffix).
    Returns number of items actually fixed.
    """
    discount_map = {fixable_indices[k]: chosen_discounts[k] for k in range(len(fixable_indices))}
    fixed_count = 0
    for idx in block_indices:
        if idx not in discount_map:
            continue
        chosen_disc = discount_map[idx]
        base_price = base_prices[idx]
        if base_price is None:
            continue
        cat = categories[idx]
        expected_price = floor_expected(base_price, chosen_disc)
        new_item = new_items[idx]
        fixed = False

        if cat in ("close_match_pm1", "prefix_suffix_match_pm1"):
            if new_item.discount_percent != chosen_disc:
                new_item.discount_percent = chosen_disc
                fixed = True
            if new_item.original_price != base_price:
                new_item.original_price = base_price
                fixed = True
        else:
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
            fixed_count += 1
    return fixed_count

def global_fix_with_monotonicity(records: List[ImageRecord]) -> Tuple[List[ImageRecord], Dict[str, Any]]:
    new_records = []
    by_category: DefaultDict[str, int] = defaultdict(int)
    fixed_items_total = 0

    for rec in records:
        items_sorted = sorted(rec.items, key=lambda x: (x.row, x.col))
        n = len(items_sorted)
        if n == 0:
            new_records.append(rec)
            continue

        # Precompute per-item data
        base_prices: List[Optional[int]] = []
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

        new_items = deepcopy(items_sorted)

        # Identify trailing contiguous sold_out block
        trailing_start = n
        for i in range(n - 1, -1, -1):
            if items_sorted[i].sold_out:
                trailing_start = i
            else:
                break

        # Prefix indices: [0, trailing_start)   (may be empty)
        # Suffix indices: [trailing_start, n)   (may be empty)
        prefix_indices = list(range(trailing_start))
        suffix_indices = list(range(trailing_start, n))

        # Process prefix block
        if prefix_indices:
            fixable_indices = [idx for idx in prefix_indices if fixable_flags[idx]]
            if fixable_indices:
                fixable_items = [items_sorted[idx] for idx in fixable_indices]
                fixable_bases = [base_prices[idx] for idx in fixable_indices]
                first_orig_disc = fixable_items[0].discount_percent if fixable_items else None
                chosen_discounts = dp_for_fixable_items(
                    fixable_items, fixable_bases, first_fixed_discount=first_orig_disc # type: ignore[arg-type]
                )
                fixed_items_total += _apply_fixes_to_block(
                    prefix_indices, fixable_indices, chosen_discounts,
                    items_sorted, new_items, base_prices, categories
                )

        # Process suffix block (trailing sold_out)
        if suffix_indices:
            fixable_indices = [idx for idx in suffix_indices if fixable_flags[idx]]
            if fixable_indices:
                fixable_items = [items_sorted[idx] for idx in fixable_indices]
                fixable_bases = [base_prices[idx] for idx in fixable_indices]
                first_orig_disc = fixable_items[0].discount_percent if fixable_items else None
                chosen_discounts = dp_for_fixable_items(
                    fixable_items, fixable_bases, first_fixed_discount=first_orig_disc # type: ignore[arg-type]
                )
                fixed_items_total += _apply_fixes_to_block(
                    suffix_indices, fixable_indices, chosen_discounts,
                    items_sorted, new_items, base_prices, categories
                )

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