from collections import Counter, defaultdict
from typing import List, Tuple

from ..helpers import safe_median
from ..models import ImageRecord, Item


# English -> Chinese mapping (based on filenames order)
EN_TO_CN = {
    "arms-insp-kit": "武器检查装置",
    "arms-inspector": "武器检查单元",
    "arsenal-ticket": "武库配额",
    "cast-die": "强固模具",
    "elementary-cognitive-carrier": "初级认知载体",
    "elementary-combat-record": "初级作战记录",
    "heavy-cast-die": "重型强固模具",
    "intermediate-combat-record": "中级作战记录",
    "oroberyl": "嵌晶玉",
    "protoprism": "协议棱柱",
    "protohedron": "协议棱柱组",
    "protodisk": "协议圆盘",
    "protoset": "协议圆盘组",
    "t-creds": "折金票",
}

def flatten_items(records: List[ImageRecord]) -> List[Tuple[Item, ImageRecord]]:
    """Return list of (item, parent_record) pairs."""
    pairs = []
    for rec in records:
        for it in rec.items:
            pairs.append((it, rec))
    return pairs

def item_name_stats(items_with_parent: List[Tuple[Item, ImageRecord]]) -> dict:
    """Count item names (mapped to Chinese) and collect low-frequency filenames."""
    name_counter: Counter = Counter()
    name_to_filenames = defaultdict(set)
    for it, parent in items_with_parent:
        cn_name = EN_TO_CN.get(it.name, it.name)   # fallback to original if not mapped
        name_counter[cn_name] += 1
        name_to_filenames[cn_name].add(parent.filename)
    return {
        'name_counter': name_counter,
        'name_to_filenames': name_to_filenames,
        'total_items': len(items_with_parent)
    }

def report_item_names(stats: dict, low_freq_threshold: float = 0.0015):
    """Print item name frequencies and low-frequency items with filenames."""
    print("\n--- Item name frequency (after mapping to Chinese) ---")
    total = stats['total_items']
    for name, cnt in stats['name_counter'].most_common():
        print(f"  {name}: {cnt} ({cnt/total*100:.1f}%)")
    # low frequency report
    low_vals = [(name, cnt) for name, cnt in stats['name_counter'].items() if cnt/total <= low_freq_threshold]
    if low_vals:
        print(f"\n--- Item names with frequency <= {low_freq_threshold*100:.2f}% ---")
        for name, cnt in sorted(low_vals, key=lambda x: x[1]):
            print(f"  '{name}' appears {cnt} times ({cnt/total*100:.3f}%):")
            for fname in sorted(stats['name_to_filenames'][name]):
                print(f"    {fname}")


# ==================================================

def compute_price_stats(items_with_parent: List[Tuple[Item, ImageRecord]]) -> dict:
    """Global and per-item price statistics."""
    prices = [it.price for it, _ in items_with_parent if it.price is not None]
    # per name (mapped) price list
    per_name = defaultdict(list)
    for it, _ in items_with_parent:
        if it.price is not None:
            cn_name = EN_TO_CN.get(it.name, it.name)
            per_name[cn_name].append(it.price)
    return {
        'prices': prices,
        'per_name': per_name,
        'total_items': len(items_with_parent)
    }

def report_price(stats: dict):
    print("\n--- Price statistics (global) ---")
    prices = stats['prices']
    if prices:
        print(f"  Min: {min(prices)}, Max: {max(prices)}, Mean: {sum(prices)/len(prices):.2f}, "
              f"Median: {safe_median(prices):.2f}")
    else:
        print("  No price data.")

    print("\n--- Price statistics per item name (by count) ---")
    per_name = stats['per_name']
    for name, price_list in sorted(per_name.items(), key=lambda x: len(x[1]), reverse=True)[:10]:
        print(f"  {name} (n={len(price_list)}): min={min(price_list)}, max={max(price_list)}, "
              f"median={safe_median(price_list):.2f}, mean={sum(price_list)/len(price_list):.2f}")

def compute_discount_stats(items_with_parent: List[Tuple[Item, ImageRecord]]) -> dict:
    """Discount percent statistics (treat None as 100% meaning no discount)."""
    discounts = []
    for it, _ in items_with_parent:
        d = it.discount_percent
        if d is None:
            d = 100
        discounts.append(d)
        
    return {
        'discounts': discounts,
        'total_items': len(items_with_parent)
    }

def report_discount(stats: dict):
    print("\n--- Discount percent (None treated as 100%) ---")
    discounts = stats['discounts']
    if not discounts:
        return
    print(f"  Min: {min(discounts)}%, Max: {max(discounts)}%, Mean: {sum(discounts)/len(discounts):.2f}%, "
          f"Median: {safe_median(discounts):.2f}%")
    discounted = sum(1 for d in discounts if d < 100)
    print(f"  Items with discount < 100%: {discounted} ({discounted/len(discounts)*100:.1f}%)")
    no_discount = sum(1 for d in discounts if d == 100)
    print(f"  Items with no discount (100%): {no_discount} ({no_discount/len(discounts)*100:.1f}%)")

def compute_quantity_stats(items_with_parent: List[Tuple[Item, ImageRecord]]) -> dict:
    """Quantity and sold_out consistency."""
    valid_items = [(it, parent) for it, parent in items_with_parent if it.quantity is not None]
    quantities = [it.quantity for it, _ in valid_items]
    sold_out_true = sum(1 for it, _ in valid_items if it.sold_out)
    zero_qty = sum(1 for q in quantities if q == 0)
    # sold_out=True but quantity>0
    sold_out_wrong_qty = sum(1 for it, _ in valid_items if it.sold_out and it.quantity > 0)
    return {
        'quantities': quantities,
        'sold_out_true_count': sold_out_true,
        'zero_qty_count': zero_qty,
        'sold_out_wrong_qty_count': sold_out_wrong_qty
    }

def report_quantity(stats: dict):
    print("\n--- Quantity and sold_out ---")
    qty = stats['quantities']
    if qty:
        print(f"  Quantity: min={min(qty)}, max={max(qty)}, mean={sum(qty)/len(qty):.2f}, "
              f"median={safe_median(qty):.2f}")
        print(f"  Items with quantity == 0: {stats['zero_qty_count']} ({stats['zero_qty_count']/len(qty)*100:.1f}%)")
    print(f"  Sold out = True: {stats['sold_out_true_count']}")
    print(f"  Sold out = True but quantity > 0 (inconsistent): {stats['sold_out_wrong_qty_count']}")

def compute_confidence_stats(items_with_parent: List[Tuple[Item, ImageRecord]]) -> dict:
    """Name confidence distribution and negatives."""
    confs = [it.name_confidence for it, _ in items_with_parent]
    negative = [c for c in confs if c < 0]
    bins = [(0, 0.5), (0.5, 0.8), (0.8, 0.9), (0.9, 1.0), (1.0, 1.2), (1.2, float('inf'))]
    bin_counts = []
    for low, high in bins:
        if high == float('inf'):
            cnt = sum(1 for c in confs if c >= low)
            label = f">={low}"
        else:
            cnt = sum(1 for c in confs if low <= c < high)
            label = f"{low}-{high}"
        bin_counts.append((label, cnt))
    return {
        'confs': confs,
        'negative_count': len(negative),
        'bin_counts': bin_counts
    }

def report_confidence(stats: dict):
    print("\n--- Name confidence ---")
    confs = stats['confs']
    if not confs:
        return
    print(f"  Min: {min(confs):.4f}, Max: {max(confs):.4f}, Mean: {sum(confs)/len(confs):.4f}, "
          f"Median: {safe_median(confs):.4f}")
    print(f"  Negative confidence values: {stats['negative_count']} ({stats['negative_count']/len(confs)*100:.2f}%)")
    print("  Confidence bins:")
    for label, cnt in stats['bin_counts']:
        print(f"    {label}: {cnt} ({cnt/len(confs)*100:.1f}%)")

def compute_source_stats(items_with_parent: List[Tuple[Item, ImageRecord]]) -> dict:
    """Name source distribution."""
    source_counter = Counter(it.name_source for it, _ in items_with_parent)
    return {'source_counter': source_counter}

def report_source(stats: dict):
    print("\n--- Name source distribution ---")
    total = sum(stats['source_counter'].values())
    for src, cnt in stats['source_counter'].most_common():
        print(f"  {src}: {cnt} ({cnt/total*100:.1f}%)")

def compute_occluded_stats(items_with_parent: List[Tuple[Item, ImageRecord]]) -> dict:
    """Name occluded flag."""
    occluded_true = sum(1 for it, _ in items_with_parent if it.name_occluded)
    return {'occluded_true': occluded_true, 'total': len(items_with_parent)}

def report_occluded(stats: dict):
    print("\n--- Name occluded ---")
    print(f"  Occluded (True): {stats['occluded_true']} ({stats['occluded_true']/stats['total']*100:.1f}%)")

def compute_price_panel_stats(items_with_parent: List[Tuple[Item, ImageRecord]]) -> dict:
    """Price panel present flag."""
    present_true = sum(1 for it, _ in items_with_parent if it.price_panel_present)
    return {'present_true': present_true, 'total': len(items_with_parent)}

def report_price_panel(stats: dict):
    print("\n--- Price panel present ---")
    print(f"  Present: {stats['present_true']} ({stats['present_true']/stats['total']*100:.1f}%)")
    print(f"  Absent: {stats['total'] - stats['present_true']}")

def items_per_image_stats(records: List[ImageRecord]) -> dict:
    """Number of items per image."""
    counts = [len(rec.items) for rec in records]
    counter = Counter(counts)
    return {
        'counts': counts,
        'counter': counter,
        'total_images': len(records)
    }

def report_items_per_image(stats: dict):
    print("\n--- Items per image ---")
    counts = stats['counts']
    if counts:
        print(f"  Min: {min(counts)}, Max: {max(counts)}, Mean: {sum(counts)/len(counts):.2f}, "
              f"Median: {safe_median(counts):.2f}")
    print("  Distribution:")
    for val, cnt in sorted(stats['counter'].items()):
        print(f"    {val} items: {cnt} images ({cnt/stats['total_images']*100:.1f}%)")