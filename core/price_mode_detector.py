from __future__ import annotations

import re
from enum import Enum
from typing import Any, Dict, List, Optional


class PriceMode(str, Enum):
    OFFICIAL_SINGLE = "OFFICIAL_SINGLE"
    LEGACY_COMPOSITE = "LEGACY_COMPOSITE"


class PriceModeDetector:
    @staticmethod
    def detect_mode(layers: List[Any]) -> PriceMode:
        if not layers:
            return PriceMode.OFFICIAL_SINGLE

        for layer in layers:
            text = str(getattr(layer, "text", "") or layer.get("text", "") or "").strip()
            name = str(getattr(layer, "name", "") or layer.get("name", "") or "").upper()
            if re.search(r"^DE\b", text, flags=re.IGNORECASE):
                continue
            if "R$" in text.upper() and any(ch.isdigit() for ch in text):
                return PriceMode.OFFICIAL_SINGLE
            if "PRECO_POR" in name or "PRECOPOR" in name:
                return PriceMode.OFFICIAL_SINGLE

        integer_count = 0
        decimal_count = 0
        for layer in layers:
            text = str(getattr(layer, "text", "") or layer.get("text", "") or "").strip()
            name = str(getattr(layer, "name", "") or layer.get("name", "") or "").upper()
            if re.search(r"^DE\b", text, flags=re.IGNORECASE):
                continue
            if re.fullmatch(r"\d{1,4}", text):
                integer_count += 1
            if re.fullmatch(r"\d{2}", text) or re.fullmatch(r"[,\.]\d{2}", text):
                decimal_count += 1
            if "INTEIRO" in name or "DECIMAL" in name or "CENTAVOS" in name:
                integer_count += 1
                decimal_count += 1

        if integer_count >= 1 and decimal_count >= 1:
            return PriceMode.LEGACY_COMPOSITE

        return PriceMode.OFFICIAL_SINGLE
