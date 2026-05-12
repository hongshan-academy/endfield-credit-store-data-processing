#!/usr/bin/env python3
"""
Endfield Credit Store Data Analysis CLI
"""

import argparse
import sys
import json
from pathlib import Path
from collections import defaultdict

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
    return parser.parse_args()


def run_price_validation_on_file(file_path: Path):
    """Load a JSON file and run price validation, returning the validation dict and printing report."""
    print(f"\nLoading file for validation: {file_path}")
    records = load_records(file_path)
    items_with_parent = flatten_items(records)
    validation = validate_prices_detailed(items_with_parent)
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
            args.price_validation or args.rounding or args.fix_price or args.dump_errors):
        print("No analysis flags provided. Use --help for available options.")
        return

    # Flatten items if needed
    items_with_parent = None
    if args.items or args.price_validation or args.rounding or args.fix_price or args.dump_errors:
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
    if args.price_validation or args.dump_errors or args.fix_price:
        validation = validate_prices_detailed(items_with_parent) # type: ignore
        if args.price_validation:
            report_price_validation_detailed(validation)
            report_file_level_stats(validation)
        if args.dump_errors:
            export_validation_errors_to_json(validation, args.dump_errors)

    if args.rounding and items_with_parent:
        compare_rounding_methods(items_with_parent)

    if args.fix_price:
        # Determine output path
        if args.output is None:
            output_path = json_path.parent / "results_final_fixed.json"
        else:
            output_path = args.output
        fixed_records, fix_stats = fix_all_items(records)
        save_fixed_records(fixed_records, output_path)
        print(f"\nFixed records saved to {output_path}")
        print(f"Fix statistics: {fix_stats}")

        # Automatically validate the fixed file
        val_fixed = run_price_validation_on_file(output_path)
        # Optionally export errors from fixed file if dump_errors was provided
        if args.dump_errors:
            # Create a separate error file for fixed results
            fixed_errors_path = output_path.parent / f"{output_path.stem}_errors.json"
            export_validation_errors_to_json(val_fixed, fixed_errors_path)


if __name__ == "__main__":
    main()