from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


@dataclass
class Bounds:
    left: float
    top: float
    right: float
    bottom: float

    @property
    def width(self) -> float:
        return max(0.0, self.right - self.left)

    @property
    def height(self) -> float:
        return max(0.0, self.bottom - self.top)


@dataclass
class LayerInfo:
    id: Optional[int]
    name: str
    typename: str
    visible: bool
    opacity: float
    bounds: Optional[Bounds] = None
    text: Optional[str] = None
    font_size: Optional[float] = None
    is_text: bool = False
    is_smart_object: bool = False
    is_shape: bool = False
    children: list["LayerInfo"] = field(default_factory=list)
    role: Optional[str] = None


@dataclass
class GroupAnalysis:
    group_name: str
    group_bounds: Optional[Bounds]
    description: Optional[LayerInfo] = None
    image: Optional[LayerInfo] = None
    shapes: list[LayerInfo] = field(default_factory=list)
    price_integer: Optional[LayerInfo] = None
    price_decimal: Optional[LayerInfo] = None
    price_de: Optional[LayerInfo] = None
    unit: Optional[LayerInfo] = None
    currency: Optional[LayerInfo] = None
    horizontal_distance_to_price: Optional[float] = None
    available_width: float = 0.0
    available_height: float = 0.0
    surrounding_collisions: list[str] = field(default_factory=list)
    needs_line_break: bool = False
    recommended_text: Optional[str] = None
    recommended_font_scale: float = 1.0
    recommended_font_size: Optional[float] = None
    recommended_line_spacing_scale: float = 0.9
    warnings: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)


@dataclass
class DocumentAnalysis:
    document_name: str
    width: float
    height: float
    groups: list[GroupAnalysis] = field(default_factory=list)
    raw_tree: list[LayerInfo] = field(default_factory=list)


class IntelligentInspector:
    """Classify one complete native Photoshop tree into actionable recommendations."""

    UNIT_TEXT = {"UN", "KG", "LT", "CX", "PCT", "G", "ML"}
    PRICE_WORDS = ("R$", "DE:", "DE ", "POR:", "POR ", "PREÇO", "PRECO")

    def __init__(self, engine: Any):
        self.engine = engine

    @staticmethod
    def _bounds(value: Any) -> Optional[Bounds]:
        if isinstance(value, list) and len(value) == 4:
            return Bounds(*(float(item) for item in value))
        if isinstance(value, dict):
            try:
                return Bounds(float(value["left"]), float(value["top"]), float(value["right"]), float(value["bottom"]))
            except (KeyError, TypeError, ValueError):
                return None
        return None

    @classmethod
    def _from_node(cls, node: dict[str, Any]) -> LayerInfo:
        return LayerInfo(
            id=node.get("id"),
            name=str(node.get("name", "")),
            typename=str(node.get("typename", "")),
            visible=bool(node.get("visible", True)),
            opacity=float(node.get("opacity") or 0.0),
            bounds=cls._bounds(node.get("bounds")),
            text=node.get("text"),
            font_size=float(node["font_size"]) if node.get("font_size") is not None else None,
            is_text=bool(node.get("is_text", node.get("text") is not None)),
            is_smart_object=bool(node.get("is_smart_object", node.get("kind") == 17)),
            is_shape=bool(node.get("is_shape", False)),
            children=[cls._from_node(child) for child in node.get("children", []) if isinstance(child, dict)],
        )

    def get_full_layer_tree(self, layer: Any = None) -> list[LayerInfo]:
        if layer is None:
            tree = self.engine.native_layer_tree or self.engine.snapshot_native_layer_tree()
            return [self._from_node(node) for node in (tree or {}).get("layers", [])]
        return [self._from_node(node) for node in layer.get("children", [])]

    @staticmethod
    def _break_after_second_space(text: str) -> str:
        parts = str(text or "").strip().split()
        if len(parts) <= 2:
            return str(text or "").strip()
        return " ".join(parts[:2]) + "\r" + " ".join(parts[2:])

    def _classify_layers(self, children: list[LayerInfo]) -> dict[str, Any]:
        classified: dict[str, Any] = {
            "description": None, "image": None, "shapes": [],
            "price_integer": None, "price_decimal": None, "price_de": None,
            "unit": None, "currency": None, "others": [],
        }
        text_layers: list[LayerInfo] = []

        def visit(layer: LayerInfo) -> None:
            if not layer.visible:
                return
            if layer.is_smart_object:
                if classified["image"] is None:
                    classified["image"] = layer
                    layer.role = "image"
                return
            name = layer.name.lower().strip()
            text = (layer.text or "").strip().upper()
            if layer.is_shape or any(token in name for token in ("shape", "retangulo", "rectangle", "ellipse", "elipse")):
                classified["shapes"].append(layer)
                layer.role = "shape"
                return
            if layer.is_text:
                text_layers.append(layer)
                if text in self.UNIT_TEXT or name in {"un", "kg"}:
                    classified["unit"] = layer
                    layer.role = "unit"
                elif text == "R$" or "r$" in name:
                    classified["currency"] = layer
                    layer.role = "currency"
                elif text.startswith(("DE:", "DE ")):
                    classified["price_de"] = layer
                    layer.role = "price_de"
                elif text.startswith(",") and text[1:].replace(".", "").isdigit():
                    classified["price_decimal"] = layer
                    layer.role = "price_decimal"
                elif text.isdigit() and len(text) <= 4:
                    classified["price_integer"] = layer
                    layer.role = "price_integer"
                elif not any(token in text for token in self.PRICE_WORDS):
                    current = classified["description"]
                    if current is None or len(text) > len(current.text or ""):
                        if current:
                            current.role = None
                        classified["description"] = layer
                        layer.role = "description"
                return
            classified["others"].append(layer)
            for child in layer.children:
                visit(child)

        for child in children:
            visit(child)
        return classified

    def analyze_group(self, group_layer: LayerInfo, original_product_name: Optional[str] = None) -> GroupAnalysis:
        classified = self._classify_layers(group_layer.children)
        analysis = GroupAnalysis(group_layer.name, group_layer.bounds)
        for key in ("description", "image", "shapes", "price_integer", "price_decimal", "price_de", "unit", "currency"):
            setattr(analysis, key, classified[key])

        name = original_product_name or (analysis.description.text if analysis.description else "")
        if analysis.description and analysis.description.bounds:
            description = analysis.description.bounds
            font_size = float(analysis.description.font_size or 36.0)

            # Identifica camadas de preço que realmente estão no caminho horizontal do texto
            price_layers = [analysis.price_integer, analysis.price_decimal, analysis.currency, analysis.unit]
            price_bounds = [layer.bounds for layer in price_layers if layer and layer.bounds]

            # Preço à direita da descrição e que realmente tenha sobreposição vertical com ela
            closest_price_left = None
            for b in price_bounds:
                if b.left > description.left:
                    # Exige sobreposição vertical real com a descrição
                    v_overlap = min(description.bottom, b.bottom) - max(description.top, b.top)
                    if v_overlap > 0:
                        if closest_price_left is None or b.left < closest_price_left:
                            closest_price_left = b.left

            # Se não encontrou preço sobreposto verticalmente, tenta price_integer ou borda direita do slot
            if closest_price_left is None and analysis.price_integer and analysis.price_integer.bounds:
                if analysis.price_integer.bounds.left > description.left:
                    closest_price_left = analysis.price_integer.bounds.left

            group_b = analysis.group_bounds
            max_right = (closest_price_left - 8.0) if closest_price_left is not None else (group_b.right - 10.0 if group_b else description.right + 180.0)
            analysis.available_width = max(80.0, max_right - description.left)
            analysis.available_height = max(50.0, (group_b.bottom - description.top - 8.0) if group_b else 90.0)

            if closest_price_left is not None:
                analysis.horizontal_distance_to_price = closest_price_left - description.right
                if analysis.horizontal_distance_to_price < 10.0:
                    analysis.needs_line_break = True
                    analysis.suggestions.append(
                        f"Distância horizontal até o preço = {analysis.horizontal_distance_to_price:.1f}px (< 10px)."
                    )

            # Estima largura do texto real a ser inserido
            if name:
                estimated_char_width = font_size * 0.52
                est_text_width = len(name) * estimated_char_width
                if est_text_width > analysis.available_width:
                    analysis.needs_line_break = True
                    analysis.suggestions.append(
                        f"Texto longo ({len(name)} caracteres, ~{est_text_width:.0f}px) excede largura disponível ({analysis.available_width:.0f}px)."
                    )

            # Colisões com outros elementos (ignora imagem do produto e shapes)
            for child in group_layer.children:
                if (
                    child is analysis.description
                    or not child.visible
                    or not child.bounds
                    or child.is_shape
                    or child.is_smart_object
                ):
                    continue
                c_name = child.name.lower()
                if any(t in c_name for t in ("imagem", "image", "smart", "foto", "shape", "fundo", "retangulo")):
                    continue
                horizontal_gap = max(0.0, child.bounds.left - description.right, description.left - child.bounds.right)
                vertical_overlap = max(0.0, min(description.bottom, child.bounds.bottom) - max(description.top, child.bounds.top))
                if vertical_overlap > 0 and horizontal_gap < 5.0:
                    analysis.surrounding_collisions.append(child.name)
            if analysis.surrounding_collisions:
                analysis.needs_line_break = True
                analysis.suggestions.append(
                    "Colisão próxima detectada com: " + ", ".join(analysis.surrounding_collisions)
                )

        if not name:
            analysis.warnings.append("Nenhuma descrição encontrada neste grupo")
            return analysis
        analysis.recommended_text = self._break_after_second_space(name) if analysis.needs_line_break else name
        if analysis.description and analysis.description.font_size:
            analysis.recommended_font_size = analysis.description.font_size
        return analysis

    def analyze_document(self, product_names_by_slot: Optional[dict[int, str]] = None) -> DocumentAnalysis:
        tree = self.get_full_layer_tree()
        document = self.engine.native_layer_tree or {}
        result = DocumentAnalysis(
            document_name=str(document.get("name", "")),
            width=float(document.get("width") or 0.0),
            height=float(document.get("height") or 0.0),
            raw_tree=tree,
        )
        for group in tree:
            match = re.search(r"(?:GRUPO|GROUP)\s*[_-]?(\d+)", group.name, re.IGNORECASE)
            if match:
                slot = int(match.group(1))
                name = (product_names_by_slot or {}).get(slot)
                result.groups.append(self.analyze_group(group, name))
        return result

    @staticmethod
    def export_analysis_json(analysis: DocumentAnalysis, path: str | Path) -> Path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(asdict(analysis), ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info("Intelligent layer analysis exported to %s", target)
        return target
