# analyser/quality/fixer.py

import json
from copy import deepcopy
from pathlib import Path
from typing import List, Tuple, Dict, Any, Optional, DefaultDict
from collections import defaultdict

from ..models import ImageRecord, Item
from .price_validator import (
    BASE_PRICE,
    ALLOWED_DISCOUNTS,
    get_chinese_name,
    floor_expected,
    classify_price_detailed,
    split_price_candidate
)

def get_fix_from_classification(item: Item, base_price: int) -> Tuple[Optional[int], Optional[int], bool]:
    """
    Use the classifier's best judgment to determine the correct price and discount.
    Returns (correct_price, correct_discount, fixed_flag).
    """
    cat, _, exp_float = classify_price_detailed(item)
    actual_price = item.price
    current_discount = item.discount_percent

    # exact_match and close_match_pm1: keep original price, only fix discount if missing
    if cat in ("exact_match", "close_match_pm1"):
        if item.discount_percent is None:
            return item.price, 0, True
        else:
            return item.price, item.discount_percent, True

    # close_match_edit: edit distance 1, likely a typo -> fix price to expected
    if cat == "close_match_edit":
        if exp_float is not None:
            expected_price = int(exp_float)
            if expected_price > 0:
                best_discount = None
                for d in ALLOWED_DISCOUNTS:
                    if floor_expected(base_price, d) == expected_price:
                        best_discount = d
                        break
                if best_discount is None:
                    implied = round(100 - (expected_price / base_price) * 100)
                    best_discount = min(ALLOWED_DISCOUNTS, key=lambda x: abs(x - implied))
                return expected_price, best_discount, True
        return None, None, False

    # prefix_suffix_match and implied_match: extract price from string or infer discount
    if cat in ("prefix_suffix_match_exact", "implied_match"):
        if exp_float is not None:
            expected_price = int(exp_float)
            if expected_price > 0:
                best_discount = None
                for d in ALLOWED_DISCOUNTS:
                    if floor_expected(base_price, d) == expected_price:
                        best_discount = d
                        break
                if best_discount is None:
                    implied = round(100 - (expected_price / base_price) * 100)
                    best_discount = min(ALLOWED_DISCOUNTS, key=lambda x: abs(x - implied))
                return expected_price, best_discount, True
        return None, None, False

    # Add after handling of "prefix_suffix_match_exact" and "implied_match"
    if cat == "prefix_suffix_match_pm1":
        if actual_price is not None and actual_price > 999:
            for disc in ALLOWED_DISCOUNTS:
                exp_int = floor_expected(base_price, disc)
                for cand in (exp_int, exp_int - 1, exp_int + 1):
                    if cand > 0 and split_price_candidate(actual_price, cand, base_price):
                        # Found extracted discounted price
                        # Determine discount from cand
                        best_discount = None
                        for d in ALLOWED_DISCOUNTS:
                            if floor_expected(base_price, d) == cand:
                                best_discount = d
                                break
                        if best_discount is None:
                            implied = round(100 - (cand / base_price) * 100)
                            best_discount = min(ALLOWED_DISCOUNTS, key=lambda x: abs(x - implied))
                        return cand, best_discount, True

    # mismatch_with_discount: discount exists but price is wrong
    if cat == "mismatch_with_discount":
        if current_discount is not None:
            expected_price = floor_expected(base_price, current_discount)
            return expected_price, current_discount, True
        # Try to infer discount from price
        if actual_price is not None:
            for d in ALLOWED_DISCOUNTS:
                if floor_expected(base_price, d) == actual_price:
                    return actual_price, d, True
        return None, None, False

    # Unfixable categories
    if cat in ("missing_discount", "other_error"):
        return None, None, False

    raise ValueError(f'Unknown category: {cat}')


def apply_fix_to_item(item: Item, base_price: int) -> Tuple[Item, bool]:
    new_item = deepcopy(item)
    fixed = False

    new_price, new_discount, should_fix_price = get_fix_from_classification(new_item, base_price)

    if should_fix_price:
        if new_price is not None:
            new_item.price = new_price
            fixed = True
        if new_discount is not None:
            new_item.discount_percent = new_discount
            fixed = True

    # Always set original_price to base_price if missing or different
    if new_item.original_price != base_price:
        new_item.original_price = base_price
        fixed = True

    # For close_match, we may still have set original_price but not price/discount
    return (new_item, fixed) if fixed else (item, False)


def fix_all_items(records: List[ImageRecord]) -> Tuple[List[ImageRecord], Dict[str, Any]]:
    new_records: List[ImageRecord] = []
    fix_stats: Dict[str, Any] = {
        "total_items": 0,
        "fixed_items": 0,
        "by_category": defaultdict(int),   # type: ignore[var-annotated]
        "fix_applied": defaultdict(int),   # type: ignore[var-annotated]
    }

    for rec in records:
        new_items: List[Item] = []
        for item in rec.items:
            ch_name = get_chinese_name(item)
            if ch_name not in BASE_PRICE:
                new_items.append(item)
                fix_stats["by_category"]["unknown"] += 1
                continue

            base_price = BASE_PRICE[ch_name]
            cat, _, _ = classify_price_detailed(item)
            # Mypy needs explicit cast to int for defaultdict
            by_cat = fix_stats["by_category"]
            by_cat[cat] = by_cat.get(cat, 0) + 1   # safer than direct increment

            new_item, fixed = apply_fix_to_item(item, base_price)
            if fixed:
                fix_stats["fixed_items"] += 1
                by_app = fix_stats["fix_applied"]
                by_app[cat] = by_app.get(cat, 0) + 1
            new_items.append(new_item)

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

    fix_stats["total_items"] = sum(fix_stats["by_category"].values())
    return new_records, fix_stats


def save_fixed_records(records: List[ImageRecord], output_path: Path) -> None:
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