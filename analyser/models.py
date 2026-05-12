from pathlib import Path
from dataclasses import dataclass
from typing import Optional, Tuple, Dict, List


@dataclass
class OCRInfo:
    """OCR sub-dictionary from meta."""
    skipped: bool
    mode: str
    full_passes: int
    crop_passes: int
    tokens_found: Optional[int] = None

@dataclass
class Meta:
    """Meta information for an image."""
    original_shape: Tuple[int, int]
    cards_detected: int
    slots_built: int
    tokens_found: int
    rectification_used: bool
    ocr: OCRInfo

@dataclass
class Item:
    """A single shop item."""
    id: int
    row: int
    col: int
    name: str                 # English name as stored in JSON
    name_confidence: float
    name_source: str
    name_occluded: bool
    price: Optional[int]
    original_price: Optional[int]
    price_panel_present: bool
    discount_percent: Optional[int]
    quantity: int
    sold_out: bool

    def mapped_name(self, mapping: Dict[str, str]) -> str:
        """Return Chinese name if mapping provided, else original name."""
        return mapping.get(self.name, self.name)

@dataclass
class ImageRecord:
    """One image entry from results_final.json."""
    image_path: str
    uid: Optional[str]
    refresh_remaining: int
    refresh_remaining_time: int
    refresh_total: int
    items: List[Item]
    meta: Meta

    @property
    def filename(self) -> str:
        return Path(self.image_path).name