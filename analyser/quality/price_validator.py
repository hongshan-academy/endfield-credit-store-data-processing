# analyser/quality/price_validator.py

import json
import math
from pathlib import Path
from collections import defaultdict
from typing import List, Tuple, Dict, Optional
from ..models import Item, ImageRecord
from ..stats.item_stats import EN_TO_CN

# ------------------------------------------------------------------
# Base prices and allowed discounts
# ------------------------------------------------------------------
BASE_PRICE = {
    "武器检查装置": 140,
    "武器检查单元": 90,
    "武库配额": 840,
    "强固模具": 140,
    "初级认知载体": 140,
    "初级作战记录": 90,
    "重型强固模具": 175,
    "中级作战记录": 140,
    "嵌晶玉": 400,
    "协议圆盘": 140,
    "协议圆盘组": 175,
    "协议棱柱": 120,
    "协议棱柱组": 140,
    "折金票": 140,
}

ALLOWED_DISCOUNTS = {0, 25, 50, 75, 95, 99}

def get_chinese_name(item: Item) -> str:
    return EN_TO_CN.get(item.name, item.name)

def floor_expected(original: int, discount: Optional[int]) -> int:
    """Floor discounted price for given original and discount (0-100)."""
    if discount is None:
        return original
    else:
        return max(1, math.floor(original * (100 - discount) / 100))

def split_price_candidate(price: int, expected_discounted: int, expected_original: int) -> bool:
    s = str(price)
    n = len(s)
    for split in range(1, n):
        a_str, b_str = s[:split], s[split:]
        if (len(a_str) > 1 and a_str[0] == '0') or (len(b_str) > 1 and b_str[0] == '0'):
            continue
        a, b = int(a_str), int(b_str)
        if (a == expected_discounted and b == expected_original) or \
           (a == expected_original and b == expected_discounted):
            return True
    return False

def levenshtein(s1: str, s2: str) -> int:
    if len(s1) < len(s2):
        return levenshtein(s2, s1)
    if len(s2) == 0:
        return len(s1)
    prev = list(range(len(s2) + 1))
    for i, c1 in enumerate(s1):
        curr = [i + 1]
        for j, c2 in enumerate(s2):
            ins = prev[j + 1] + 1
            dele = curr[j] + 1
            sub = prev[j] + (c1 != c2)
            curr.append(min(ins, dele, sub))
        prev = curr
    return prev[-1]

def prefix_suffix_match(actual_str: str, target: int) -> bool:
    target_str = str(target)
    return actual_str.startswith(target_str) or actual_str.endswith(target_str)

# ------------------------------------------------------------------
# Core classification
# ------------------------------------------------------------------
def classify_price_detailed(item: Item, max_discount: int) -> Tuple[str, str, Optional[int], Optional[float]]:
    ch_name = get_chinese_name(item)
    if ch_name not in BASE_PRICE:
        return "other_error", f"Unknown item name: {ch_name}", None, None

    original = BASE_PRICE[ch_name]
    disc = item.discount_percent
    has_discount = disc is not None and disc != 100
    actual = item.price

    # Helper to compute expected float
    def exp_float(d: int) -> float:
        return original * (100 - d) / 100

    if actual is None:
        if has_discount:
            return "mismatch_with_discount", f"price None but discount {disc}%", None, None
        return "missing_discount", "price None", None, None

    actual_str = str(actual)

    # ---- Discount exists case ----
    if has_discount:
        if disc > max_discount: # type: ignore[operator]
            return "discount_non_motonic", f"non-motonic discount: {disc} > {max_discount}", None, None

        exp_int = floor_expected(original, disc) # type: ignore[arg-type]
        expected = exp_float(disc) # type: ignore[arg-type]

        if abs(actual - exp_int) < 1e-6:
            return "exact_match", f"exact match (floor)", disc, expected
        if abs(actual - exp_int) <= 1:
            return "close_match_pm1", f"numeric close ±1", disc, expected
        if levenshtein(actual_str, str(exp_int)) <= 1:
            return "close_match_edit", f"edit distance match", disc, expected
        if prefix_suffix_match(actual_str, exp_int):
            return "prefix_suffix_match_exact", f"prefix/suffix match for discount {disc}%", disc, expected
        if actual > 999:
            for cand in (exp_int, exp_int-1, exp_int+1):
                if cand > 0 and split_price_candidate(actual, cand, original):
                    return "prefix_suffix_match_pm1", f"concatenated split to {cand}/{original}", disc, expected
        return "mismatch_with_discount", f"unmatched price {actual} with discount {disc}%", disc, expected

    # ---- Discount is None ----
    # First, check if price is close to original (no discount)
    if actual == original:
        return "exact_match", "no discount, price equals base price", 0, float(original)
    if abs(actual - original) <= 1:
        return "close_match_pm1", f"no discount, price close to base (off by {actual - original})", 0, float(original)

    # Then try to match any allowed discount via prefix/suffix
    for d in ALLOWED_DISCOUNTS:
        if d > max_discount:
            continue
        
        exp_int = floor_expected(original, d)
        if prefix_suffix_match(actual_str, exp_int):
            return "prefix_suffix_match_exact", f"prefix/suffix matches discount {d}% (expected {exp_int})", d, exp_float(d)
        # Also try ±1 on expected
        for delta in (-1, 1):
            cand = exp_int + delta
            if cand > 0 and prefix_suffix_match(actual_str, cand):
                return "prefix_suffix_match_exact", f"prefix/suffix (±1) matches discount {d}% (expected {cand})", d, exp_float(d)

    # Implied discount: price itself matches an allowed discount when compared to original
    implied = round(100 - (actual / original) * 100)
    for i in (-1, 0, 1):
        if (implied + i) in ALLOWED_DISCOUNTS and implied + i <= max_discount:
            return "implied_match", f"price implies {implied + i}% off", implied + i, exp_float(implied + i)

    # Nothing works
    return "other_error", f"no discount, price {actual} does not match any allowed discount", None, float(original)

# ------------------------------------------------------------------
# Validation and reporting
# ------------------------------------------------------------------
def validate_prices_detailed(records: List[ImageRecord]) -> Dict[str, List]:
    result = defaultdict(list)
    for parent in records:
        items = sorted(parent.items, key=lambda x: (x.row, x.col))
        in_stock = [item for item in items if not item.sold_out]
        sold_out = [item for item in items if item.sold_out]
        
        max_discount = 100
        for item in in_stock:
            cat, reason, discount, exp_float = classify_price_detailed(item, max_discount)
            result[cat].append((item, parent, reason, discount, exp_float))
            max_discount = discount if discount is not None else max_discount
        
        max_discount = 100
        for item in sold_out:
            cat, reason, discount, exp_float = classify_price_detailed(item, max_discount)
            result[cat].append((item, parent, reason, discount, exp_float))
            max_discount = discount if discount is not None else max_discount
            
    return dict(result)

def report_price_validation_detailed(validation_result: Dict[str, List], max_examples: int = 5):
    print("\n" + "=" * 10 + " Detailed Price Validation " + "=" * 10)
    total = sum(len(lst) for lst in validation_result.values())
    if total == 0:
        print("No items to validate.")
        return

    category_order = [
        "exact_match", "close_match_pm1", "close_match_edit", 
        "prefix_suffix_match_exact", "concatenated_exact", "prefix_suffix_match_pm1", 
        "implied_match", "mismatch_with_discount", "missing_discount", 
        "other_error"
    ]
    for cat in category_order:
        lst = validation_result.get(cat, [])
        if not lst:
            continue
        print(f"\n{cat}: {len(lst)} ({len(lst)/total*100:.1f}%)")
        for item, parent, reason, discount, exp_float in lst[:max_examples]:
            exp_str = f"{exp_float:.2f}" if exp_float is not None else "N/A"
            print(f"    {parent.filename} (r{item.row}c{item.col}): {reason} (fixed_discount={discount}, expected_float={exp_str})")
        if len(lst) > max_examples:
            print(f"    ... and {len(lst)-max_examples} more.")

    # Any remaining categories not listed (shouldn't happen)
    for cat, lst in validation_result.items():
        if cat not in category_order:
            print(f"\n{cat}: {len(lst)} ({len(lst)/total*100:.1f}%)")
            for item, parent, reason, discount, exp_float in lst[:max_examples]:
                exp_str = f"{exp_float:.2f}" if exp_float is not None else "N/A"
                print(f"    {parent.filename} (r{item.row}c{item.col}): {reason} (fixed_discount={discount}, expected_float={exp_str})")
            if len(lst) > max_examples:
                print(f"    ... and {len(lst)-max_examples} more.")

def compare_rounding_methods(items_with_parent: List[Tuple[Item, ImageRecord]]):
    methods = {
        "round": lambda x: max(1, round(x)),
        "floor": lambda x: max(1, math.floor(x)),
        "ceil":  lambda x: max(1, math.ceil(x)),
        "int":   lambda x: max(1, int(x))
    }
    stats = {name: 0 for name in methods}
    total = 0
    for item, _ in items_with_parent:
        ch_name = get_chinese_name(item)
        if ch_name not in BASE_PRICE:
            continue
        disc = item.discount_percent
        if disc is None or disc == 0 or disc == 100:
            continue
        original = BASE_PRICE[ch_name]
        exp_float = original * (100 - disc) / 100
        actual = item.price
        if actual is None or actual > 840:
            continue
        total += 1
        for name, func in methods.items():
            if abs(func(exp_float) - actual) < 1e-6:
                stats[name] += 1
    print("\n" + "=" * 10 + " Rounding Method Comparison " + "=" * 10)
    for name, count in sorted(stats.items(), key=lambda x: x[1], reverse=True):
        print(f"  {name}: {count} / {total} ({count/total*100:.1f}%)")

def export_validation_errors_to_json(validation_result: Dict[str, List], output_path: Path):
    # Categories considered perfectly valid (no need to export)
    valid_categories = {
        "exact_match", "close_match_pm1"
    }
    error_entries = []
    for cat, lst in validation_result.items():
        if cat in valid_categories:
            continue
        for item, parent, reason, _, exp_float in lst:
            entry = {
                "filename": parent.filename,
                "row": item.row,
                "col": item.col,
                "item_name": get_chinese_name(item),
                "discount_percent": item.discount_percent,
                "price": item.price,
                "expected_float": exp_float,
                "category": cat,
                "reason": reason,
            }
            error_entries.append(entry)
    error_entries.sort(key=lambda x: (x["filename"], x["row"], x["col"]))
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(error_entries, f, indent=2, ensure_ascii=False)
    print(f"Exported {len(error_entries)} mismatched items to {output_path}")

def report_file_level_stats(validation_result: Dict[str, List]):
    from collections import defaultdict

    file_count_by_cat = defaultdict(set)
    unfixable_files = set()
    unfixable_cats = {"missing_discount", "other_error"}
    acceptable_cats = {"exact_match", "close_match_pm1"}

    total_items_per_file: defaultdict = defaultdict(int)
    matched_items_per_file: defaultdict = defaultdict(int)

    for cat, entries in validation_result.items():
        for _, parent, _, _, _ in entries:
            filename = parent.filename
            file_count_by_cat[cat].add(filename)
            if cat in unfixable_cats:
                unfixable_files.add(filename)

            total_items_per_file[filename] += 1
            if cat in acceptable_cats:
                matched_items_per_file[filename] += 1

    matched_files = sum(1 for f in total_items_per_file
                        if total_items_per_file[f] == matched_items_per_file.get(f, 0))

    print("\n" + "=" * 10 + " File-Level Category Summary " + "=" * 10)
    for cat in sorted(file_count_by_cat.keys()):
        print(f"  {cat}: {len(file_count_by_cat[cat])} files")
    print(f"\n  Total unfixable files (any missing_discount or other_error): {len(unfixable_files)}")
    print(f"  Total matched files (all items exact_match or close_match_pm1): {matched_files}")