from __future__ import annotations

import logging
from pathlib import Path
from typing import List, Optional, Tuple

from .data_loader import OfferItem

logger = logging.getLogger(__name__)


class ValidationResult:
    def __init__(self):
        self.errors: List[str] = []
        self.warnings: List[str] = []

    @property
    def is_valid(self) -> bool:
        return len(self.errors) == 0

    def add_error(self, message: str) -> None:
        self.errors.append(message)
        logger.error(message)

    def add_warning(self, message: str) -> None:
        self.warnings.append(message)
        logger.warning(message)


class Validator:
    @staticmethod
    def validate_template(template_path: str | Path) -> Tuple[bool, List[str]]:
        path = Path(template_path).resolve()
        errors: List[str] = []
        if not path.exists():
            errors.append(f"Template file not found: {path}")
            return False, errors

        if path.is_dir():
            matches = [p for p in sorted(path.rglob("*")) if p.is_file() and p.suffix.lower() in {".psd", ".psb"}]
            if not matches:
                errors.append(f"No PSD template file was found inside: {path}")
                return False, errors
            return True, []

        if path.suffix.lower() not in {".psd", ".psb"}:
            errors.append(f"Unsupported template format: {path.suffix}")
            return False, errors
        return True, []

    @staticmethod
    def validate_offers(items: List[OfferItem], products_dir: Optional[str | Path] = None, max_slots: int = 50) -> ValidationResult:
        result = ValidationResult()
        if not items:
            result.add_error("No valid offers were loaded from the spreadsheet.")
            return result

        seen_slots = set()
        for item in items:
            prefix = f"Slot #{item.slot:02d}"

            if item.slot <= 0 or item.slot > max_slots:
                result.add_error(f"{prefix}: invalid slot number {item.slot}. Expected 1..{max_slots}.")

            if item.slot in seen_slots:
                result.add_warning(f"{prefix}: duplicate slot detected; later entries may overwrite earlier ones.")
            seen_slots.add(item.slot)

            if not item.nome:
                result.add_error(f"{prefix}: product name is empty.")

            if item.preco_por is None:
                result.add_warning(f"{prefix}: promotional price is missing.")
            elif item.preco_por <= 0:
                result.add_warning(f"{prefix}: promotional price must be greater than zero.")

            if item.preco_de is not None and item.preco_por is not None and item.preco_de <= item.preco_por:
                result.add_warning(f"{prefix}: 'de' price should be greater than the promotional price.")

            if item.imagem:
                image_path = Path(item.imagem)
                if not image_path.is_absolute() and products_dir is not None:
                    image_path = Path(products_dir) / item.imagem
                if not image_path.exists():
                    result.add_warning(f"{prefix}: image file not found: {item.imagem}")
            else:
                result.add_warning(f"{prefix}: no image mapped for this offer.")

        return result
