"""
Quality filter based on price validation categories and item count.
Computes a score per record (higher = better) and filters out low-quality ones.
"""

import logging
from typing import List, Tuple, Dict, Any, Optional
from collections import defaultdict

from ..models import ImageRecord, Item
from .price_validator import (
    classify_price_detailed,
    get_chinese_name,
    floor_expected,
    split_price_candidate,
    BASE_PRICE,
)

# Item scores (higher = better). Raw score is a float from 0 to 1, but we define
# integer base scores (0..100) and divide by 100 for normalization.
CATEGORY_BASE_SCORE = {
    "exact_match": 100,
    "close_match_pm1": 100,
    "concatenated_exact": 100,
    "discount_non_monotonic": 80,
    "close_match_edit": 70,
    "prefix_suffix_match_exact": 70,
    "prefix_suffix_match_pm1": 70,
    "implied_match": 50,
    "mismatch_with_discount": 30,
    "missing_discount": -50,
    "other_error": -50,
}
SCORE_NORMALIZER = 100.0         # divide by 100 to get per-item score in [ -0.5 , 1.0 ]

# Penalty for wrong item count (applied as a direct subtraction from total score)
ITEM_COUNT_PENALTY = 5.0

# Default minimum total score to keep a record (max possible = number_of_items, e.g. 10)
DEFAULT_MIN_SCORE = 7.0


def _is_perfect_concatenation(item: Item, ch_name: str, category: str) -> bool:
    """
    Upgrade a prefix/suffix match to "concatenated_exact" if the price string
    is exactly the concatenation of (discounted_price, original_price) or vice versa.
    """
    if item.price is None or category not in ("prefix_suffix_match_exact", "prefix_suffix_match_pm1"):
        return False
    if ch_name not in BASE_PRICE:
        return False
    original = BASE_PRICE[ch_name]
    actual = item.price
    for d in (0, 25, 50, 75, 95, 99):
        expected = floor_expected(original, d)
        if split_price_candidate(actual, expected, original):
            s = str(actual)
            exp_str = str(expected)
            orig_str = str(original)
            if s == exp_str + orig_str or s == orig_str + exp_str:
                return True
    return False


def compute_item_score(item: Item, max_discount: int) -> Tuple[float, str, Optional[int]]:
    """
    Compute score (0..1, may be negative) for a single item.
    Returns (score, category, used_discount).
    """
    ch_name = get_chinese_name(item)
    cat, _, discount, _ = classify_price_detailed(item, max_discount)

    # Upgrade to concatenated_exact if perfect
    if _is_perfect_concatenation(item, ch_name, cat):
        cat = "concatenated_exact"

    base = CATEGORY_BASE_SCORE.get(cat, 0)
    score = base / SCORE_NORMALIZER
    return score, cat, discount


def compute_record_score(record: ImageRecord) -> Tuple[float, Dict[str, Any]]:
    """
    Compute total score for a record. High is good.
    Returns (total_score, details).
    """
    items = sorted(record.items, key=lambda x: (x.row, x.col))
    n = len(items)
    total_score = 0.0
    max_discount = 100
    item_details = []

    for item in items:
        score, cat, used_discount = compute_item_score(item, max_discount)
        total_score += score
        item_details.append({
            "row": item.row,
            "col": item.col,
            "name": get_chinese_name(item),
            "price": item.price,
            "discount": item.discount_percent,
            "category": cat,
            "score": score,
        })
        if used_discount is not None:
            max_discount = used_discount

    # Apply item count penalty (if not 10 items)
    if n != 10:
        total_score -= ITEM_COUNT_PENALTY
        item_details.append({
            "row": -1,
            "col": -1,
            "name": "ITEM_COUNT",
            "price": None,
            "discount": None,
            "category": f"item_count_{n}_not_10",
            "score": -ITEM_COUNT_PENALTY,
        })

    return total_score, {
        "total_score": total_score,
        "item_count": n,
        "items": item_details,
    }


def filter_records(
    records: List[ImageRecord],
    min_score: float = DEFAULT_MIN_SCORE,
    dry_run: bool = False,
    logger: Optional[logging.Logger] = None,
) -> Tuple[List[ImageRecord], Dict[str, Any]]:
    """
    Filter out low-quality records based on total score.
    Always returns the filtered list (actual transformation). dry_run only controls logging verbosity.
    """
    if logger is None:
        logger = logging.getLogger(__name__)
        if not logger.handlers:
            handler = logging.StreamHandler()
            handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
            logger.addHandler(handler)
            logger.setLevel(logging.INFO)

    filtered = []
    stats: Dict[str, Any] = {
        "total_records": len(records),
        "kept_records": 0,
        "dropped_records": 0,
        "min_score": min_score,
        "total_score_distribution": [],
        "category_counts": defaultdict(int),
    }

    for rec in records:
        total_score, details = compute_record_score(rec)
        stats["total_score_distribution"].append(total_score)
        for it in details["items"]:
            stats["category_counts"][it["category"]] += 1

        keep = total_score >= min_score
        if keep:
            filtered.append(rec)
            stats["kept_records"] += 1
        else:
            stats["dropped_records"] += 1
            if not dry_run:
                logger.info(f"Dropped {rec.filename}: score={total_score:.2f} (min={min_score})")
            else:
                logger.debug(f"DRY RUN: Would drop {rec.filename}: score={total_score:.2f}")

    stats["category_counts"] = dict(stats["category_counts"])
    return filtered, stats