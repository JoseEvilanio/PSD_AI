from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from psd_tools import PSDImage

logger = logging.getLogger(__name__)


class PsdTemplateInspector:
    """Inspects the final PSD template and extracts a slot map for each product card."""

    PRICE_TOKENS = {"KG", "UN", "LT", "CX", "PCT", "G", "ML"}
    NON_NAME_TOKENS = {"POR", "R$", "DE;", "DE", "CADA", "KG", "UN", "LT", "CX", "PCT", "G", "ML", ","}

    @staticmethod
    def _iter_descendants(node: Any) -> Iterable[Any]:
        for child in list(node):
            yield child
            try:
                yield from PsdTemplateInspector._iter_descendants(child)
            except TypeError:
                pass

    @staticmethod
    def _extract_text(layer: Any) -> str:
        if layer is None:
            return ""
        text = getattr(layer, "text", None)
        if text is not None:
            text = str(text).strip()
            return re.sub(r"\s+", " ", text)
        name = getattr(layer, "name", "")
        name = str(name).strip()
        return re.sub(r"\s+", " ", name)

    @staticmethod
    def _normalize_price(raw_value: Any) -> Optional[float]:
        if raw_value is None:
            return None
        text = str(raw_value).strip()
        if not text:
            return None
        cleaned = text.replace("R$", "").replace("DE;", "").replace("DE", "").replace(" ", "")
        cleaned = cleaned.replace("\u00a0", "")
        if not cleaned:
            return None
        if "," in cleaned and "." in cleaned:
            if cleaned.rfind(",") > cleaned.rfind("."):
                cleaned = cleaned.replace(".", "").replace(",", ".")
            else:
                cleaned = cleaned.replace(",", "")
        elif "," in cleaned:
            cleaned = cleaned.replace(",", ".")
        try:
            return float(cleaned)
        except ValueError:
            return None

    @classmethod
    def _parse_promo_price(cls, price_group: Any) -> Optional[float]:
        if price_group is None:
            return None
        tokens: List[str] = []
        for child in cls._iter_descendants(price_group):
            text = cls._extract_text(child)
            if text:
                tokens.append(text)

        if not tokens:
            return None

        for i, token in enumerate(tokens):
            upper = token.upper().strip()
            if upper in {"R$", "R$"}:
                numeric_tokens = []
                for later in tokens[i + 1:]:
                    later_clean = later.strip()
                    if later_clean.upper() in cls.PRICE_TOKENS:
                        break
                    if re.fullmatch(r"\d+([,.]\d+)?", later_clean):
                        numeric_tokens.append(later_clean)
                if numeric_tokens:
                    combined = ",".join(numeric_tokens) if len(numeric_tokens) > 1 else numeric_tokens[0]
                    return cls._normalize_price(combined)
                break
        return None

    @classmethod
    def _extract_slot_metadata(cls, group: Any) -> Dict[str, Any]:
        group_name = str(getattr(group, 'name', '') or '').strip()
        slot_match = re.search(r'(\d+)', group_name)
        slot = int(slot_match.group(1)) if slot_match else 0

        text_entries: List[Dict[str, str]] = []
        for child in cls._iter_descendants(group):
            text = cls._extract_text(child)
            if not text:
                continue
            text_entries.append({
                'layer_name': str(getattr(child, 'name', '') or '').strip(),
                'text': text,
                'type': type(child).__name__,
            })

        image_name = None
        for entry in text_entries:
            layer_name = entry['layer_name']
            upper_name = layer_name.upper()
            if 'IMAGEM' in upper_name:
                image_name = layer_name
                break
        if image_name is None:
            for child in cls._iter_descendants(group):
                name = str(getattr(child, 'name', '') or '').strip()
                upper_name = name.upper()
                if 'IMAGEM' in upper_name:
                    image_name = name
                    break

        nome = None
        for child in list(group):
            direct_text = cls._extract_text(child)
            if not direct_text:
                continue
            upper_text = direct_text.upper()
            if 'IMAGEM' in upper_text or 'PREÇO' in upper_text or 'PRECO' in upper_text:
                continue
            if upper_text in {'POR', 'R$', 'CADA', 'KG', 'UN', 'LT', 'CX', 'PCT', 'G', 'ML', ',', 'DE'}:
                continue
            if re.fullmatch(r'(?:DE;?\s*\d+[.,]\d+|R\$\s*\d+[.,]\d+|\d+[.,]\d+|\d+)', direct_text):
                continue
            nome = direct_text
            break

        if nome is None:
            for entry in text_entries:
                text = entry['text']
                upper = text.upper()
                if 'IMAGEM' in upper or 'PREÇO' in upper or 'PRECO' in upper:
                    continue
                if upper in {'POR', 'R$', 'CADA', 'KG', 'UN', 'LT', 'CX', 'PCT', 'G', 'ML', ',', 'DE'}:
                    continue
                if re.fullmatch(r'(?:DE;?\s*\d+[.,]\d+|R\$\s*\d+[.,]\d+|\d+[.,]\d+|\d+)', text):
                    continue
                nome = text
                break

        preco_de = None
        for entry in text_entries:
            text = entry['text']
            if re.match(r'^DE', text, flags=re.IGNORECASE):
                preco_de = cls._normalize_price(text)
                break

        preco_por = None
        price_group = None
        for child in list(group):
            name = str(getattr(child, 'name', '') or '').strip().upper()
            if 'PREÇO' in name or 'PRECO' in name:
                price_group = child
                break
        if price_group is None:
            for child in cls._iter_descendants(group):
                name = str(getattr(child, 'name', '') or '').strip().upper()
                if 'PREÇO' in name or 'PRECO' in name:
                    price_group = child
                    break
        if price_group is not None:
            preco_por = cls._parse_promo_price(price_group)

        unidade = None
        for entry in text_entries:
            value = entry['text'].upper()
            if value in cls.PRICE_TOKENS:
                unidade = value
                break

        cada = None
        for entry in text_entries:
            if entry['text'].lower() == 'cada':
                cada = entry['text']
                break

        return {
            'slot': slot,
            'group_name': group_name,
            'nome': nome,
            'preco_de': preco_de,
            'preco_por': preco_por,
            'unidade': unidade,
            'cada': cada,
            'imagem': image_name,
        }

    @classmethod
    def inspect_template(cls, template_path: str | Path) -> List[Dict[str, Any]]:
        template_file = Path(template_path).resolve()
        if not template_file.exists():
            raise FileNotFoundError(f"Template not found: {template_file}")

        psd = PSDImage.open(str(template_file))
        slots: List[Dict[str, Any]] = []

        for group in psd:
            name = getattr(group, 'name', '') or ''
            normalized = str(name).strip()
            if not normalized:
                continue
            if 'DESCRI' not in normalized.upper() and 'IMAGEM' not in normalized.upper() and 'PRE' not in normalized.upper():
                continue

            slot_map = cls._extract_slot_metadata(group)
            if slot_map['slot'] == 0:
                slot_map['slot'] = len(slots) + 1
            slots.append(slot_map)

        return slots
