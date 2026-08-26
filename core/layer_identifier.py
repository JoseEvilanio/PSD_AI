from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class LayerFeature:
    name: str
    text: str = ""
    font_size: float = 0.0
    is_text: bool = False
    is_smart_object: bool = False
    area: float = 0.0
    kind: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class GroupClassification:
    group_name: str
    slot: int
    nome: Optional[str] = None
    preco_de: Optional[str] = None
    preco_por: Optional[str] = None
    unidade: Optional[str] = None
    imagem: Optional[str] = None
    cada: Optional[str] = None
    confidence: Dict[str, float] = field(default_factory=dict)


class LayerIdentifier:
    @staticmethod
    def extract_slot_number(group_name: str) -> int:
        match = re.search(r"(\d+)", str(group_name) or "")
        return int(match.group(1)) if match else 1

    @classmethod
    def classify_group(cls, group_name: str, layers: List[LayerFeature]) -> GroupClassification:
        slot = cls.extract_slot_number(group_name)
        result = GroupClassification(group_name=group_name, slot=slot)

        text_layers = [layer for layer in layers if layer.is_text]
        image_layers = [layer for layer in layers if not layer.is_text]

        if text_layers:
            best_name = max(text_layers, key=lambda layer: len((layer.text or layer.name).strip()), default=None)
            if best_name:
                result.nome = best_name.name
                result.confidence["nome"] = 0.9

        for layer in text_layers:
            text = (layer.text or "").strip()
            name = layer.name.upper()
            if re.search(r"^DE\b", text, flags=re.IGNORECASE) or "PRECO_DE" in name:
                if result.preco_de is None:
                    result.preco_de = layer.name
                    result.confidence["preco_de"] = 0.95
            if re.search(r"(?:R\$|\d{1,4}[,.]\d{2})", text) and not re.search(r"^DE\b", text, flags=re.IGNORECASE):
                if result.preco_por is None:
                    result.preco_por = layer.name
                    result.confidence["preco_por"] = 0.95
            if re.fullmatch(r"[A-Za-z.,/ ]*cada[ A-Za-z.,/]*", text, flags=re.IGNORECASE):
                if result.cada is None:
                    result.cada = layer.name
                    result.confidence["cada"] = 0.9
            if re.fullmatch(r"(?:UN|KG|LT|G|CX|PCT)", text, flags=re.IGNORECASE):
                if result.unidade is None:
                    result.unidade = layer.name
                    result.confidence["unidade"] = 0.9

        if image_layers:
            preferred = max(image_layers, key=lambda layer: layer.area, default=None)
            if preferred:
                result.imagem = preferred.name
                result.confidence["imagem"] = 0.92

        if result.preco_por and result.preco_de and result.unidade and result.imagem and result.cada:
            return result

        # Fallbacks for common naming conventions
        for layer in text_layers:
            name = layer.name.upper()
            if result.preco_de is None and ("PRECO_DE" in name or "VALOR_DE" in name or "DE_" in name):
                result.preco_de = layer.name
            if result.preco_por is None and ("PRECO_POR" in name or "PRECOPOR" in name or "PRECO" in name):
                result.preco_por = layer.name
            if result.unidade is None and ("UNIDADE" in name or "MEDIDA" in name or name in {"UN", "KG", "LT", "CX", "PCT"}):
                result.unidade = layer.name
            if result.cada is None and "CADA" in name:
                result.cada = layer.name

        if result.nome is None and text_layers:
            result.nome = text_layers[0].name
            result.confidence["nome"] = 0.7

        return result
