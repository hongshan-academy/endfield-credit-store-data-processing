from pathlib import Path
import json
from .models import *


def load_json_file(path: Path) -> dict:
    """Load and return JSON content."""
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)

def parse_OCR(ocr_dict: dict) -> OCRInfo:
    """Convert raw OCR dict to OCRInfo."""
    return OCRInfo(
        skipped=ocr_dict.get('skipped', False),
        mode=ocr_dict.get('mode', 'unknown'),
        full_passes=ocr_dict.get('full_passes', 0),
        crop_passes=ocr_dict.get('crop_passes', 0),
        tokens_found=ocr_dict.get('tokens_found')
    )

def parse_meta(meta_dict: dict) -> Meta:
    """Convert raw meta dict to Meta."""
    ocr = parse_OCR(meta_dict.get('ocr', {}))
    return Meta(
        original_shape=tuple(meta_dict['original_shape']),
        cards_detected=meta_dict['cards_detected'],
        slots_built=meta_dict['slots_built'],
        tokens_found=meta_dict['tokens_found'],
        rectification_used=meta_dict['rectification_used'],
        ocr=ocr
    )

def parse_item(item_dict: dict) -> Item:
    """Convert raw item dict to Item."""
    return Item(
        id=item_dict['id'],
        row=item_dict['row'],
        col=item_dict['col'],
        name=item_dict['name'],
        name_confidence=item_dict['name_confidence'],
        name_source=item_dict['name_source'],
        name_occluded=item_dict['name_occluded'],
        price=item_dict.get('price'),
        original_price=item_dict.get('original_price'),
        price_panel_present=item_dict['price_panel_present'],
        discount_percent=item_dict.get('discount_percent'),
        quantity=item_dict['quantity'],
        sold_out=item_dict['sold_out']
    )

def load_records(data_path: Path) -> List[ImageRecord]:
    """Load all records from results_final.json and mapping.json."""
    records_data = load_json_file(data_path)
    records = []
    for entry in records_data:
        items = [parse_item(it) for it in entry.get('items', [])]
        meta = parse_meta(entry['meta'])
        record = ImageRecord(
            image_path=entry['image_path'],
            uid=entry.get('uid'),
            refresh_remaining=entry['refresh_remaining'],
            refresh_remaining_time=entry['refresh_remaining_time'],
            refresh_total=entry['refresh_total'],
            items=items,
            meta=meta
        )
        records.append(record)
    return records