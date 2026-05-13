#!/usr/bin/env python3
"""
Endfield Credit Store Data Analysis CLI
"""

import argparse
import sys
from pathlib import Path

from analyser import *


def parse_args():
    parser = argparse.ArgumentParser(description="Endfield Credit Store Data Analysis Tool")
    parser.add_argument("results_json", type=Path, help="Path to results_final.json")
    parser.add_argument("--uid", action="store_true", help="Show UID statistics")
    parser.add_argument("--refresh", action="store_true", help="Show refresh statistics")
    parser.add_argument("--meta", action="store_true", help="Show meta statistics")
    parser.add_argument("--items", action="store_true", help="Show flattened item statistics")
    parser.add_argument("--price-validation", action="store_true", help="Run price validation and classification")
    parser.add_argument("--rounding", action="store_true", help="Compare rounding methods")
    parser.add_argument("--fix-price", action="store_true", help="Apply automatic price/discount fixes")
    parser.add_argument("--output", type=Path, help="Output JSON file for fixed data (default: <input_dir>/results_final_fixed.json)")
    parser.add_argument("--dump-errors", type=Path, metavar="FILEPATH", help="Export non-exact and non-close validation results to JSON file")
    
    # 新增 filter 与 dry-run 参数
    parser.add_argument("--filter", action="store_true", help="Enable quality filtering (based on price categories and item count)")
    parser.add_argument("--filter-threshold", type=float, default=DEFAULT_MIN_SCORE,
                        help=f"Penalty threshold for filtering (default {DEFAULT_MIN_SCORE})")
    parser.add_argument("--dry-run", action="store_true", help="Do not write output, only log what would be done")
    
    return parser.parse_args()


def run_price_validation_on_file(file_path: Path):
    """Load a JSON file and run price validation, returning the validation dict and printing report."""
    print(f"\nLoading file for validation: {file_path}")
    records = load_records(file_path)
    validation = validate_prices_detailed(records)
    report_price_validation_detailed(validation)
    report_file_level_stats(validation)
    return validation


def main():
    args = parse_args()
    json_path = args.results_json
    if not json_path.exists():
        print(f"Error: JSON file not found: {json_path}")
        sys.exit(1)

    # Load records
    records = load_records(json_path)
    total_items = sum(len(r.items) for r in records)
    print(f"Loaded {len(records)} images, {total_items} items.\n")

    # If no analysis flags, just exit
    if not (args.uid or args.refresh or args.meta or args.items or 
            args.price_validation or args.rounding or args.fix_price or args.dump_errors or args.filter):
        print("No analysis flags provided. Use --help for available options.")
        return

    # Flatten items if needed
    items_with_parent = None
    if args.items or args.price_validation or args.rounding or args.fix_price or args.dump_errors or args.filter:
        items_with_parent = flatten_items(records)

    # Run requested analyses
    if args.uid:
        uid_stats = compute_uid_stats(records)
        report_uid(uid_stats)

    if args.refresh:
        refresh_stats = compute_refresh_stats(records)
        report_refresh(refresh_stats)

    if args.meta:
        meta_stats = compute_meta_stats(records)
        report_meta(meta_stats)

    if args.items and items_with_parent:
        print("\n" + "=" * 10 + " Flattened Item Statistics " + "=" * 10)
        report_item_names(item_name_stats(items_with_parent))
        report_price(compute_price_stats(items_with_parent))
        report_discount(compute_discount_stats(items_with_parent))
        report_quantity(compute_quantity_stats(items_with_parent))
        report_confidence(compute_confidence_stats(items_with_parent))
        report_source(compute_source_stats(items_with_parent))
        report_occluded(compute_occluded_stats(items_with_parent))
        report_price_panel(compute_price_panel_stats(items_with_parent))
        report_items_per_image(items_per_image_stats(records))

    # Compute validation once if needed
    validation = None
    if args.price_validation or args.dump_errors or args.fix_price or args.filter:
        validation = validate_prices_detailed(records)
        if args.price_validation:
            report_price_validation_detailed(validation)
            report_file_level_stats(validation)
        if args.dump_errors:
            export_validation_errors_to_json(validation, args.dump_errors)

    if args.rounding and items_with_parent:
        compare_rounding_methods(items_with_parent)

    if args.filter:
        records, filter_stats = filter_records(
            records,
            min_score=args.filter_threshold,
            dry_run=args.dry_run,   # 仅控制日志详细程度，不影响过滤结果
        )
        print(f"\nFilter stats: kept {filter_stats['kept_records']} / {filter_stats['total_records']} records "
              f"(dropped {filter_stats['dropped_records']}, threshold={args.filter_threshold})")

    if args.fix_price:
        # Determine output path
        if args.output is None:
            output_path = json_path.parent / "results_final_fixed.json"
        else:
            output_path = args.output

        fixed_records, fix_stats = fix_all_items(records)
        print(f"\nFix statistics: {fix_stats}")

        if not args.dry_run:
            save_fixed_records(fixed_records, output_path)
            print(f"Fixed records saved to {output_path}")

            # Automatically validate the fixed file
            val_fixed = run_price_validation_on_file(output_path)
            # Optionally export errors from fixed file if dump_errors was provided
            if args.dump_errors:
                # Create a separate error file for fixed results
                fixed_errors_path = output_path.parent / f"{output_path.stem}_errors.json"
                export_validation_errors_to_json(val_fixed, fixed_errors_path)
        else:
            print("DRY RUN: Fixed records not saved, validation skipped.")


if __name__ == "__main__":
    main()