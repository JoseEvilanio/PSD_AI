from __future__ import annotations

import json
import logging
import os
import re
import shutil
import time
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, Optional

from .product_abbreviator import abreviar_produto, quebrar_linhas_inteligente

logger = logging.getLogger(__name__)


@dataclass
class Bounds:
    left: float
    top: float
    right: float
    bottom: float

    @property
    def width(self) -> float:
        return self.right - self.left

    @property
    def height(self) -> float:
        return self.bottom - self.top

    @property
    def center_x(self) -> float:
        return (self.left + self.right) / 2.0

    @property
    def center_y(self) -> float:
        return (self.top + self.bottom) / 2.0

    def expand(self, margin: float) -> "Bounds":
        return Bounds(self.left - margin, self.top - margin, self.right + margin, self.bottom + margin)

    def intersects(self, other: "Bounds") -> bool:
        return not (
            self.right < other.left or
            self.left > other.right or
            self.bottom < other.top or
            self.top > other.bottom
        )

    def horizontal_overlap(self, other: "Bounds") -> float:
        return max(0.0, min(self.right, other.right) - max(self.left, other.left))

    def vertical_overlap(self, other: "Bounds") -> float:
        return max(0.0, min(self.bottom, other.bottom) - max(self.top, other.top))


def _could_collide_horizontally(a: Bounds, b: Bounds) -> bool:
    return a.vertical_overlap(b) > min(a.height, b.height) * 0.25


def _could_collide_vertically(a: Bounds, b: Bounds) -> bool:
    return a.horizontal_overlap(b) > min(a.width, b.width) * 0.25


def calculate_safe_text_box(
    description_bounds: Bounds,
    neighbors: list[tuple[str, Bounds]],
    min_margin: float = 4.0,
    extra_margin_for_images: float = 6.0,
    extra_margin_for_prices: float = 3.0,
    allow_sides: Optional[dict[str, bool]] = None,
) -> Bounds:
    if allow_sides is None:
        allow_sides = {"left": True, "right": True, "top": True, "bottom": True}

    safe = Bounds(description_bounds.left, description_bounds.top, description_bounds.right, description_bounds.bottom)

    for name, neighbor in neighbors:
        name_lower = (name or "").lower()
        margin = min_margin
        if any(token in name_lower for token in ("smart", "image", "foto", "img", "product", "produto")):
            margin = extra_margin_for_images
        elif any(token in name_lower for token in ("preço", "preco", "price", "r$", "de", "por", "unidade", "un", "kg", "ml", "unit")):
            margin = extra_margin_for_prices

        expanded = neighbor.expand(margin)
        if expanded.intersects(safe) or _could_collide_horizontally(safe, expanded):
            if expanded.right <= safe.center_x and allow_sides.get("left", True):
                new_left = max(safe.left, expanded.right)
                if new_left < safe.right - 20:
                    safe.left = new_left
            elif expanded.left >= safe.center_x and allow_sides.get("right", True):
                new_right = min(safe.right, expanded.left)
                if new_right > safe.left + 20:
                    safe.right = new_right

        if expanded.intersects(safe) or _could_collide_vertically(safe, expanded):
            if expanded.bottom <= safe.center_y and allow_sides.get("top", True):
                new_top = max(safe.top, expanded.bottom)
                if new_top < safe.bottom - 15:
                    safe.top = new_top
            elif expanded.top >= safe.center_y and allow_sides.get("bottom", True):
                new_bottom = min(safe.bottom, expanded.top)
                if new_bottom > safe.top + 15:
                    safe.bottom = new_bottom

    min_w, min_h = 40.0, 20.0
    if safe.width < min_w:
        mid = safe.center_x
        safe.left = mid - min_w / 2.0
        safe.right = mid + min_w / 2.0
    if safe.height < min_h:
        mid = safe.center_y
        safe.top = mid - min_h / 2.0
        safe.bottom = mid + min_h / 2.0

def quebrar_texto_por_comprimento(texto: str, max_caracteres: int) -> list:
    """
    Divide um texto em várias linhas sem quebrar palavras ao meio,
    respeitando o limite máximo de caracteres por linha.
    """
    palavras = texto.split()
    if not palavras:
        return []

    linhas = []
    linha_atual = []
    comprimento_atual = 0

    for palavra in palavras:
        tamanho_palavra = len(palavra)
        if not linha_atual:
            linha_atual.append(palavra)
            comprimento_atual = tamanho_palavra
        elif comprimento_atual + 1 + tamanho_palavra <= max_caracteres:
            linha_atual.append(palavra)
            comprimento_atual += 1 + tamanho_palavra
        else:
            linhas.append(" ".join(linha_atual))
            linha_atual = [palavra]
            comprimento_atual = tamanho_palavra

    if linha_atual:
        linhas.append(" ".join(linha_atual))

    return linhas


class PhotoshopEngine:
    """Wrapper for Adobe Photoshop automation.

    On Windows with Adobe Photoshop installed, it will attempt to connect to the
    COM interface. If Photoshop is unavailable, it falls back to a safe stub so
    the app remains usable in development and test environments.
    """

    def __init__(self, visible: bool = True, display_dialogs: bool = False):
        self.logger = logger
        self.visible = visible
        self.display_dialogs = display_dialogs
        self.app: Optional[Any] = None
        self.template_path: Optional[Path] = None
        self.photoshop_installed = self._is_photoshop_installed()
        self.com_error: Optional[str] = None
        self.native_layer_tree: Optional[dict[str, Any]] = None
        self._native_layer_index: dict[Any, dict[str, Any]] = {}
        self.description_recommendations: dict[int, str] = {}
        self.description_font_scales: dict[int, float] = {}
        self.description_line_spacing_scales: dict[int, float] = {}
        self.ai_provider: Optional[Any] = None
        self._connect()

    @staticmethod
    def _is_photoshop_installed() -> bool:
        candidate_roots = [
            r"C:\Program Files\Adobe",
            r"C:\Program Files (x86)\Adobe",
            os.environ.get("ProgramFiles", ""),
            os.environ.get("ProgramFiles(x86)", ""),
        ]
        seen = set()
        for root in candidate_roots:
            if not root or root in seen:
                continue
            seen.add(root)
            if os.path.exists(root):
                for current, _, files in os.walk(root):
                    if "Photoshop.exe" in files:
                        return True
        return bool(shutil.which("Photoshop.exe"))

    def _connect(self) -> None:
        try:
            import win32com.client  # type: ignore
            import struct

            self.app = win32com.client.Dispatch("Photoshop.Application")
            self.app.Visible = self.visible
            self.app.DisplayDialogs = 3 if self.display_dialogs else 2
            self.com_error = None
            logger.info("Connected to Photoshop via COM.")
        except Exception as exc:  # pragma: no cover - depends on Windows/Photoshop
            self.app = None
            self.com_error = str(exc)
            bitness = struct.calcsize("P") * 8
            if self.photoshop_installed:
                logger.warning(
                    "Photoshop appears installed on this machine, but COM could not connect. "
                    "This usually means a Python/Photoshop architecture mismatch (for example, 32-bit Python with 64-bit Photoshop), "
                    "or pywin32 is not installed. Python is %s-bit. Details: %s",
                    bitness,
                    exc,
                )
            else:
                logger.warning("Photoshop is not available in this runtime; using stub mode. Details: %s", exc)

    @staticmethod
    def _iter_layers(node: Any) -> Iterator[Any]:
        if node is None:
            return

        if hasattr(node, 'LayerSets'):
            try:
                for i in range(node.LayerSets.Count):
                    layer_set = node.LayerSets[i]
                    if layer_set is not None:
                        yield layer_set
                        yield from PhotoshopEngine._iter_layers(layer_set)
            except Exception:
                pass

        if hasattr(node, 'ArtLayers'):
            try:
                for i in range(node.ArtLayers.Count):
                    art_layer = node.ArtLayers[i]
                    if art_layer is not None:
                        yield art_layer
            except Exception:
                pass

        if hasattr(node, 'Layers'):
            try:
                for i in range(node.Layers.Count):
                    child = node.Layers[i]
                    if child is not None:
                        yield child
                        yield from PhotoshopEngine._iter_layers(child)
            except Exception:
                pass

    def _render_template_fallback(self, target_path: str | Path) -> Path:
        template_file = self.template_path or Path(target_path).resolve()
        target = Path(target_path).resolve()
        target.parent.mkdir(parents=True, exist_ok=True)

        try:
            from psd_tools import PSDImage
            from PIL import Image

            psd = PSDImage.open(str(template_file))
            image = psd.composite()
            image = image.convert("RGB")
            image.save(target, format="JPEG" if target.suffix.lower() in {".jpg", ".jpeg"} else "PNG")
            logger.info("Rendered PSD fallback to %s with psd-tools composite()", target)
            return target
        except Exception as exc:  # pragma: no cover - fallback if PSD parsing fails
            logger.warning("Could not render PSD fallback preview with psd-tools: %s", exc)
            from PIL import Image, ImageDraw

            image = Image.new("RGB", (1600, 900), color=(250, 250, 250))
            draw = ImageDraw.Draw(image)
            draw.rectangle((40, 40, 1560, 860), fill=(245, 245, 245), outline=(200, 200, 200), width=2)
            draw.text((90, 90), "Autoflyer — PSD fallback preview", fill=(30, 30, 30))
            draw.text((90, 150), str(template_file.name), fill=(70, 70, 70))
            draw.text((90, 220), "Photoshop não está disponível neste ambiente.", fill=(120, 120, 120))
            image.save(target, format="JPEG" if target.suffix.lower() in {".jpg", ".jpeg"} else "PNG")
            logger.info("Saved placeholder preview image to %s", target)
            return target

    def open_template(self, template_path: str | Path) -> bool:
        path = Path(template_path).resolve()
        if not path.exists():
            raise FileNotFoundError(f"Template not found: {path}")

        self.template_path = path
        if self.app is not None:
            try:
                self.app.Open(str(path))
                logger.info("Opened PSD template in Photoshop: %s", path)
                return True
            except Exception as exc:  # pragma: no cover - COM fallback
                logger.warning("Could not open template in Photoshop via COM: %s", exc)

        logger.info("Using PSD fallback preview mode to process template: %s", path)
        return True

    @staticmethod
    def _com_value(value: Any, default: Any = None) -> Any:
        try:
            return value.Value if hasattr(value, "Value") else value
        except Exception:
            return default

    @classmethod
    def _native_layer_tree(cls, layer: Any) -> dict[str, Any]:
        """Convert one Photoshop DOM layer and its descendants to JSON data."""
        bounds = cls._bounds_signature(layer)
        node: dict[str, Any] = {
            "name": str(getattr(layer, "Name", "") or ""),
            "id": cls._com_value(getattr(layer, "ID", None)),
            "kind": cls._com_value(getattr(layer, "Kind", None)),
            "typename": str(getattr(layer, "typename", type(layer).__name__) or ""),
            "visible": bool(getattr(layer, "Visible", True)),
            "opacity": cls._com_value(getattr(layer, "Opacity", None)),
            "bounds": list(bounds) if bounds is not None else None,
            "text": None,
            "font_size": None,
            "is_text": cls._is_text_layer(layer),
            "is_smart_object": cls._com_value(getattr(layer, "Kind", None)) == 17,
            "is_shape": cls._is_shape_name(getattr(layer, "Name", "")),
            "children": [],
        }
        if cls._is_text_layer(layer):
            node["text"] = cls._text_content(layer)
            node["font_size"] = cls._com_value(getattr(getattr(layer, "TextItem", None), "Size", None))

        collection_names = ("Layers",) if str(getattr(layer, "typename", "")) == "Document" else ("LayerSets", "ArtLayers")
        for collection_name in collection_names:
            collection = getattr(layer, collection_name, None)
            if collection is None:
                continue
            try:
                for index in range(collection.Count):
                    child = collection[index]
                    if child is not None:
                        node["children"].append(cls._native_layer_tree(child))
            except Exception:
                continue
        return node

    def get_native_layer_tree(self) -> Optional[dict[str, Any]]:
        """Return the open Photoshop document as a serializable layer tree."""
        if self.app is None:
            return None
        try:
            document = self.app.ActiveDocument
            if document is None:
                return None
            tree = {
                "name": str(getattr(document, "Name", "") or ""),
                "path": str(getattr(document, "FullName", "") or ""),
                "width": self._com_value(getattr(document, "Width", None)),
                "height": self._com_value(getattr(document, "Height", None)),
                "resolution": self._com_value(getattr(document, "Resolution", None)),
                "layers": [],
            }
            for index in range(document.Layers.Count):
                tree["layers"].append(self._native_layer_tree(document.Layers[index]))
            return tree
        except Exception as exc:  # pragma: no cover - depends on Photoshop COM
            logger.warning("Could not inspect the native Photoshop document: %s", exc)
            return None

    def snapshot_native_layer_tree(self) -> Optional[dict[str, Any]]:
        """Read the complete document tree once and index its structured nodes."""
        self.native_layer_tree = self.get_native_layer_tree()
        self._native_layer_index = {}

        def visit(node: dict[str, Any]) -> None:
            if node.get("id") is not None:
                self._native_layer_index[node["id"]] = node
            for child in node.get("children", []):
                if isinstance(child, dict):
                    visit(child)

        if self.native_layer_tree:
            for node in self.native_layer_tree.get("layers", []):
                visit(node)
        return self.native_layer_tree

    def _native_slot_node(self, slot_number: int) -> Optional[dict[str, Any]]:
        target = str(slot_number)
        padded = target.zfill(2)
        for node in self._native_layer_index.values():
            name = str(node.get("name", "")).strip()
            if not re.search(r"(?:^|[_ -])(?:%s|%s)$" % (re.escape(target), re.escape(padded)), name, re.IGNORECASE):
                continue
            upper = name.upper()
            if (
                re.search(r"^(?:GRUPO|GROUP|PRODUCT|PRODUTO)\s*[_-]?\s*\d+$", upper)
                or ("DESCRI" in upper and "PRE" in upper)
            ):
                return node
        return None

    def _layer_from_native_node(self, node: Optional[dict[str, Any]]) -> Any:
        if not node or node.get("id") is None or self.app is None:
            return None
        target_id = node["id"]
        for layer in self._iter_layers(self.app.ActiveDocument):
            if self._com_value(getattr(layer, "ID", None)) == target_id:
                return layer
        return None

    @staticmethod
    def _native_description_node(group_node: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
        if not group_node:
            return None
        candidates: list[dict[str, Any]] = []

        def visit(node: dict[str, Any]) -> None:
            if node.get("is_text"):
                text = str(node.get("text") or "").strip()
                upper = text.upper()
                if (
                    len(text) > 6
                    and not re.fullmatch(r"[\d,.]+", text)
                    and not any(token in upper for token in ("R$", "DE:", "POR:", "UN", "KG", "LT", "CX", ",99", ",49"))
                ):
                    candidates.append(node)
            for child in node.get("children", []):
                if isinstance(child, dict):
                    visit(child)

        visit(group_node)
        return max(candidates, key=lambda node: len(str(node.get("text") or "")), default=None)

    def export_native_layer_tree_json(self, output_path: str | Path) -> Optional[Path]:
        """Save the open Photoshop DOM tree as UTF-8 JSON, when COM is available."""
        tree = self.native_layer_tree or self.snapshot_native_layer_tree()
        if tree is None:
            return None
        target = Path(output_path).resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(tree, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        logger.info("Exported native Photoshop layer tree: %s", target)
        return target

    def update_text_layer(self, layer_name: str, text: str) -> None:
        logger.info("Updating layer '%s' with text '%s'", layer_name, text)
        if self.app is None:
            return
        try:
            doc = self.app.ActiveDocument
            if doc is None:
                return
            layers = doc.Layers
            for i in range(layers.Count):
                layer = layers[i]
                if getattr(layer, "Name", "") == layer_name:
                    layer.TextItem.Contents = text
                    break
        except Exception as exc:  # pragma: no cover - COM fallback
            logger.warning("Failed to update text layer '%s': %s", layer_name, exc)

    def _find_slot_group(self, doc: Any, slot_number: int) -> Any:
        if doc is None:
            return None
        target_token = str(slot_number).zfill(2)
        fallback = None
        for layer in self._iter_layers(doc):
            name = getattr(layer, "Name", "") or ""
            if not name:
                continue
            upper = name.upper()
            if "DESCRI" in upper and "PRE" in upper and (f"{slot_number}" in name or target_token in name):
                return layer
            if (
                fallback is None
                and (
                    "PRODUCT" in upper
                    or "PRODUTO" in upper
                    or re.search(r"^(?:GRUPO|GROUP)\s*[_-]?\s*\d+$", upper)
                )
                and (f"{slot_number}" in name or target_token in name)
            ):
                fallback = layer
        return fallback

    @classmethod
    def _text_content(cls, layer: Any) -> str:
        try:
            contents = getattr(getattr(layer, "TextItem", None), "Contents", None)
            if contents is not None:
                return str(contents).strip()
        except Exception:
            pass
        return str(getattr(layer, "Name", "") or "").strip()

    @classmethod
    def _text_layers(cls, node: Any) -> list[Any]:
        return [layer for layer in cls._iter_layers(node) if cls._is_text_layer(layer)]

    @classmethod
    def _smart_object_layers(cls, node: Any) -> list[Any]:
        return [
            layer for layer in cls._iter_layers(node)
            if int(getattr(layer, "Kind", 0)) == 17
        ]

    @classmethod
    def _largest_smart_object(cls, node: Any) -> Any:
        layers = cls._smart_object_layers(node)
        measured = []
        for layer in layers:
            bounds = cls._bounds_signature(layer)
            if bounds is None:
                continue
            width = max(bounds[2] - bounds[0], 0.0)
            height = max(bounds[3] - bounds[1], 0.0)
            measured.append((width * height, layer, bounds))
        if not measured:
            return None
        return max(measured, key=lambda item: item[0])

    @classmethod
    def _smart_objects_with_bounds(cls, node: Any) -> list[tuple[Any, tuple[float, float, float, float]]]:
        result = []
        for layer in cls._smart_object_layers(node):
            bounds = cls._bounds_signature(layer)
            if bounds is not None:
                result.append((layer, bounds))
        return result

    @staticmethod
    def _is_shape_name(name: Any) -> bool:
        normalized = unicodedata.normalize("NFKD", str(name or "")).upper()
        normalized = "".join(char for char in normalized if not unicodedata.combining(char))
        return any(token in normalized for token in ("SHAPE", "RECTANGLE", "RETANGULO", "ELLIPSE", "ELIPSE"))

    @classmethod
    def _shape_references(cls, node: Any) -> list[tuple[float, float, float, float]]:
        references = []
        for layer in cls._iter_layers(node):
            if cls._is_text_layer(layer) or int(getattr(layer, "Kind", 0)) == 17:
                continue
            if not cls._is_shape_name(getattr(layer, "Name", "")):
                continue
            bounds = cls._bounds_signature(layer)
            if bounds is None:
                continue
            if bounds[2] - bounds[0] >= 10 and bounds[3] - bounds[1] >= 10:
                references.append(bounds)
        return references

    @classmethod
    def _match_shape_to_image(
        cls,
        image_bounds: tuple[float, float, float, float],
        shapes: list[tuple[float, float, float, float]],
        used: set[int],
    ) -> Optional[tuple[float, float, float, float]]:
        center_x = (image_bounds[0] + image_bounds[2]) / 2.0
        center_y = (image_bounds[1] + image_bounds[3]) / 2.0
        candidates = []
        for index, shape in enumerate(shapes):
            if index in used:
                continue
            shape_center_x = (shape[0] + shape[2]) / 2.0
            shape_center_y = (shape[1] + shape[3]) / 2.0
            contains_center = shape[0] <= center_x <= shape[2] and shape[1] <= center_y <= shape[3]
            if not contains_center:
                continue
            distance = (shape_center_x - center_x) ** 2 + (shape_center_y - center_y) ** 2
            candidates.append((distance, index, shape))
        if not candidates:
            return None
        _, index, shape = min(candidates, key=lambda item: item[0])
        used.add(index)
        return shape

    @classmethod
    def _shape_reference_bounds(
        cls,
        node: Any,
        image_bounds: Optional[tuple[float, float, float, float]] = None,
    ) -> Optional[tuple[float, float, float, float]]:
        candidates = []
        image_center = None
        if image_bounds is not None:
            image_center = (
                (image_bounds[0] + image_bounds[2]) / 2.0,
                (image_bounds[1] + image_bounds[3]) / 2.0,
            )
        for layer in cls._iter_layers(node):
            if cls._is_text_layer(layer) or int(getattr(layer, "Kind", 0)) == 17:
                continue
            if not cls._is_shape_name(getattr(layer, "Name", "")):
                continue
            bounds = cls._bounds_signature(layer)
            if bounds is None:
                continue
            width = max(bounds[2] - bounds[0], 0.0)
            height = max(bounds[3] - bounds[1], 0.0)
            if width < 10 or height < 10:
                continue
            center = ((bounds[0] + bounds[2]) / 2.0, (bounds[1] + bounds[3]) / 2.0)
            distance = 0.0 if image_center is None else (
                (center[0] - image_center[0]) ** 2 + (center[1] - image_center[1]) ** 2
            )
            candidates.append((distance, width * height, bounds))
        if not candidates:
            return None
        return min(candidates, key=lambda item: (item[0], -item[1]))[2]

    @classmethod
    def _find_description_layer(cls, group: Any) -> Any:
        excluded = {"DE", "POR", "R$", "UN", "KG", "LT", "CX", "PCT", "G", "ML", "CADA", ","}
        candidates = []
        for layer in cls._text_layers(group):
            text = cls._text_content(layer)
            upper = text.upper().replace(";", "").strip()
            if not text or upper in excluded:
                continue
            if re.fullmatch(r"[\d,.]+", text) or re.match(r"^(?:DE|BD)\b", upper):
                continue
            if (
                ("PRE" in upper and len(text) < 12)
                or upper.startswith("SHAPE")
                or upper.startswith("ELLIPSE")
                or upper.startswith("RECTANGLE")
                or upper.startswith("RETANGULO")
                or upper.startswith("ELIPSE")
            ):
                continue
            candidates.append((len(text), layer))
        return max(candidates, key=lambda item: item[0])[1] if candidates else None

    @staticmethod
    def _is_unit_text(text: str) -> bool:
        return text.upper().strip() in {"UN", "KG", "LT", "CX", "PCT", "G", "ML"}

    @staticmethod
    def _is_unit_layer(name: str, text: str = "") -> bool:
        normalized_name = str(name or "").upper().strip()
        normalized_text = str(text or "").upper().strip()
        return (
            PhotoshopEngine._is_unit_text(normalized_text)
            or normalized_name in {"UN", "KG", "LT", "CX", "PCT", "G", "ML"}
            or any(token in normalized_name for token in ("UNIDADE", "UNID", "MEDIDA", "UNIT"))
        )

    @staticmethod
    def _is_text_layer(layer: Any) -> bool:
        try:
            kind = getattr(layer, "Kind", None)
            return kind is not None and int(kind) == 2
        except Exception:
            return False

    @staticmethod
    def _normalize_text_breaks(text: str) -> str:
        s = str(text or "")
        s = s.replace("\\r\\n", "\r").replace("\\r", "\r").replace("\\n", "\r")
        s = s.replace("\r\n", "\r").replace("\n", "\r")
        s = re.sub(r"\r+", "\r", s).strip("\r")
        return s

    def _apply_text_value(self, layer: Any, value: str) -> bool:
        if layer is None or not self._is_text_layer(layer):
            return False
        try:
            expected = self._normalize_text_breaks(value)
            layer.TextItem.Contents = expected
            actual = self._normalize_text_breaks(getattr(layer.TextItem, "Contents", ""))
            if actual != expected:
                logger.warning(
                    "Photoshop did not confirm text change on layer '%s' (expected '%s', got '%s')",
                    getattr(layer, "Name", ""), expected, actual,
                )
                return False
            logger.info("Updated Photoshop text layer '%s' to '%s'", getattr(layer, "Name", ""), expected)
            return True
        except Exception as exc:  # pragma: no cover - COM fallback
            logger.warning("Failed to set text on layer '%s': %s", getattr(layer, "Name", ""), exc)
            return False

    def _enable_auto_leading_and_wrap(self, layer: Any) -> None:
        if layer is None or not self._is_text_layer(layer):
            return
        try:
            text_item = getattr(layer, "TextItem", None)
            if text_item is not None:
                text_item.UseAutoLeading = True
                text_item.ParagraphJustification = 1
        except Exception:
            pass

    def _set_font_size(self, layer: Any, font_size: float) -> float:
        if layer is None or not self._is_text_layer(layer):
            return 0.0
        try:
            text_item = getattr(layer, "TextItem", None)
            if text_item is None:
                return 0.0
            size_value = max(1.0, float(font_size))
            text_item.Size = size_value
            current = float(getattr(text_item, "Size", size_value) or size_value)
            return current
        except Exception as exc:  # pragma: no cover - COM fallback
            logger.warning("Failed to set font size on layer '%s': %s", getattr(layer, "Name", ""), exc)
            return 0.0

    def _get_font_size(self, layer: Any) -> Optional[float]:
        if layer is None or not self._is_text_layer(layer):
            return None
        try:
            size = getattr(getattr(layer, "TextItem", None), "Size", None)
            return float(getattr(size, "Value", size)) if size is not None else None
        except Exception:
            return None

    def _set_tracking(self, layer: Any, value: int) -> None:
        if layer is None or not self._is_text_layer(layer):
            return
        try:
            text_item = getattr(layer, "TextItem", None)
            if text_item is not None:
                text_item.Tracking = int(value)
        except Exception:
            pass

    def _set_leading(self, layer: Any, value: float) -> None:
        if layer is None or not self._is_text_layer(layer):
            return
        try:
            text_item = getattr(layer, "TextItem", None)
            if text_item is not None:
                text_item.AutoLeading = False
                text_item.Leading = max(1.0, float(value))
        except Exception:
            pass

    def _try_convert_to_paragraph_text(self, layer: Any, width: float) -> bool:
        if layer is None or not self._is_text_layer(layer):
            return False
        width_set = False
        try:
            text_item = getattr(layer, "TextItem", None)
            if text_item is None:
                return False
            try:
                text_item.Width = max(1.0, float(width))
                width_set = True
            except Exception:
                pass
        except Exception:
            pass
        return width_set

    def _restore_full_description(self, layer: Any, text: str, width: float, font_size: float) -> None:
        wrapped = self._normalize_text_breaks(text)
        self._clear_and_set_text(layer, wrapped)
        try:
            layer.Visible = True
        except Exception:
            pass
        self._force_photoshop_update()

    @staticmethod
    def _wrap_text_for_width(text: str, width: float, font_size: float, tracking: int = 0) -> str:
        average_char_width = max(font_size * 0.55 + tracking / 100.0, 1.0)
        max_chars = max(8, int(width / average_char_width))

        wrapped_paragraphs: list[str] = []
        for paragraph in str(text).replace("\r\n", "\n").replace("\r", "\n").split("\n"):
            words = paragraph.split()
            lines: list[str] = []
            current: list[str] = []
            current_length = 0
            for word in words:
                added_length = len(word) if not current else len(word) + 1
                if current and current_length + added_length > max_chars:
                    lines.append(" ".join(current))
                    current = []
                    current_length = 0
                current.append(word)
                current_length += len(word) if current_length == 0 else len(word) + 1
            if current:
                lines.append(" ".join(current))
            wrapped_paragraphs.append("\r".join(lines))

        wrapped = "\r".join(wrapped_paragraphs)
        return wrapped or str(text)

    @staticmethod
    def _break_description_after_second_space(text: str) -> str:
        """Keep the first two words together, then start the remaining text below."""
        value = str(text or "").strip()
        first_space = value.find(" ")
        if first_space < 0:
            return value
        second_space = value.find(" ", first_space + 1)
        if second_space < 0:
            return value
        return value[:second_space] + "\r" + value[second_space + 1:]

    @staticmethod
    def _horizontal_gap(left: tuple[float, float, float, float], right: tuple[float, float, float, float]) -> float:
        """Return the horizontal distance between two boxes, or zero when they overlap."""
        return max(0.0, right[0] - left[2], left[0] - right[2])

    def _get_rendered_text_bounds(self, layer: Any) -> Optional[tuple[float, float, float, float]]:
        if layer is None or not self._is_text_layer(layer):
            return None
        try:
            self._enable_auto_leading_and_wrap(layer)
            bounds = getattr(layer, "Bounds", None)
            if bounds is None:
                return None
            values = []
            for value in bounds:
                values.append(float(getattr(value, "Value", value)))
            if len(values) == 4:
                return tuple(values)
        except Exception:
            return None
        return None

    def _calculate_safe_text_box(
        self,
        group: Any,
        description_layer: Any,
        min_margin: float = 4.0,
    ) -> Optional[tuple[float, float, float, float]]:
        if description_layer is None:
            return None
        description_bounds = self._bounds_signature(description_layer)
        if description_bounds is None:
            return None

        neighbors: list[tuple[str, Bounds]] = []
        for layer in self._iter_layers(group):
            if layer is description_layer or not bool(getattr(layer, "Visible", True)):
                continue
            if not (self._is_text_layer(layer) or int(getattr(layer, "Kind", 0)) == 17):
                continue
            blocker_bounds = self._bounds_signature(layer)
            if blocker_bounds is not None and self._valid_bounds(blocker_bounds):
                neighbors.append((str(getattr(layer, "Name", "") or "layer"), Bounds(*blocker_bounds)))

        if not neighbors:
            return tuple(description_bounds)

        safe_box = calculate_safe_text_box(
            description_bounds=Bounds(*description_bounds),
            neighbors=neighbors,
            min_margin=min_margin,
            extra_margin_for_images=8.0,
            extra_margin_for_prices=3.5,
        )
        return (
            safe_box.left,
            safe_box.top,
            safe_box.right,
            safe_box.bottom,
        )

    def _adjust_text_layer_to_fit(
        self,
        layer: Any,
        max_width: float,
        max_height: float,
        original_font_size: float,
        min_scale: float = 0.55,
        max_scale: float = 1.15,
        tolerance: float = 0.5,
        max_iterations: int = 12,
    ) -> float:
        if layer is None or not self._is_text_layer(layer):
            return float(original_font_size or 0.0)

        current_size = float(getattr(getattr(layer, "TextItem", None), "Size", original_font_size) or original_font_size or 0.0)
        if current_size <= 0:
            return 0.0
        self._enable_auto_leading_and_wrap(layer)

        min_size = max(1.0, current_size * min_scale)
        max_size = max(current_size, current_size * max_scale)
        best_size = current_size
        low = min_size
        high = max_size

        for _ in range(max_iterations):
            mid = (low + high) / 2.0
            self._set_font_size(layer, mid)
            bounds = self._get_rendered_text_bounds(layer)
            if bounds is None:
                break
            width = max(bounds[2] - bounds[0], 1.0)
            height = max(bounds[3] - bounds[1], 1.0)
            width_ok = width <= max_width + tolerance
            height_ok = height <= max_height + tolerance
            if width_ok and height_ok:
                best_size = mid
                low = mid
            else:
                high = mid
            if high - low < 0.3:
                break

        final_size = max(1.0, float(best_size))
        self._set_font_size(layer, final_size)
        return final_size

    def _fit_description_layer_with_collision(
        self,
        group: Any,
        description_layer: Any,
        description_bounds: tuple[float, float, float, float],
        shape_references: list[tuple[float, float, float, float]],
        blocking_bounds: list[tuple[float, float, float, float]],
        target_slot: int,
    ) -> None:
        target_fit_box = None
        if shape_references:
            description_shape = min(
                shape_references,
                key=lambda shape: (
                    ((shape[0] + shape[2]) / 2.0 - (description_bounds[0] + description_bounds[2]) / 2.0) ** 2
                    + ((shape[1] + shape[3]) / 2.0 - (description_bounds[1] + description_bounds[3]) / 2.0) ** 2
                ),
            )
            target_fit_box = self._description_safe_bounds(
                description_bounds,
                description_shape,
                blocking_bounds,
            )

        safe_slot_box = self._calculate_safe_text_box(group, description_layer, min_margin=4.0)
        if safe_slot_box is not None:
            target_fit_box = safe_slot_box
        elif target_fit_box is None:
            target_fit_box = self._description_safe_bounds(
                description_bounds,
                description_bounds,
                blocking_bounds,
            )

        self._fit_text_to_bounds(
            description_layer,
            target_fit_box,
            description_bounds,
            horizontal_center=(target_fit_box[0] + target_fit_box[2]) / 2.0,
            blocking_bounds=blocking_bounds,
        )

        max_width = max(target_fit_box[2] - target_fit_box[0], 1.0)
        max_height = max(target_fit_box[3] - target_fit_box[1], 1.0)
        original_font_size = float(getattr(description_layer.TextItem, "Size", 0) or 0)
        if original_font_size <= 0:
            return

        bounds_after_wrap = self._get_rendered_text_bounds(description_layer)
        if bounds_after_wrap is None:
            return

        measured_width = max(bounds_after_wrap[2] - bounds_after_wrap[0], 1.0)
        measured_height = max(bounds_after_wrap[3] - bounds_after_wrap[1], 1.0)
        if measured_width <= max_width + 0.5 and measured_height <= max_height + 0.5:
            return

        final_size = self._adjust_text_layer_to_fit(
            description_layer,
            max_width=max_width,
            max_height=max_height,
            original_font_size=original_font_size,
            min_scale=0.55,
            max_scale=1.15,
            tolerance=0.5,
            max_iterations=12,
        )
        if final_size < original_font_size * 0.85:
            logger.warning(
                "Description '%s' was shrunk to %.1f px to fit the safe box in slot %s.",
                getattr(description_layer, "Name", ""),
                final_size,
                target_slot,
            )

    def _force_photoshop_update(self) -> None:
        if self.app is None:
            return
        try:
            self.app.Refresh()
        except Exception:
            pass

    def _compress_and_position_text(self, layer: Any, target: Bounds) -> bool:
        if self.app is None or layer is None:
            return False
        try:
            layer_id = int(getattr(layer, "ID"))
        except Exception:
            return False

        script = (
            "function findLayer(container, targetId) {"
            "  for (var i = 0; i < container.layers.length; i++) {"
            "    var candidate = container.layers[i];"
            "    if (candidate.id == targetId) return candidate;"
            "    if (candidate.typename == 'LayerSet') {"
            "      var nested = findLayer(candidate, targetId);"
            "      if (nested) return nested;"
            "    }"
            "  }"
            "  return null;"
            "}"
            "function px(value) { return value.as('px'); }"
            "var fittedLayer = findLayer(app.activeDocument, " + str(layer_id) + ");"
            "if (!fittedLayer) throw new Error('Text layer not found for compression');"
            "var bounds = fittedLayer.bounds;"
            "var left = px(bounds[0]);"
            "var top = px(bounds[1]);"
            "var right = px(bounds[2]);"
            "var bottom = px(bounds[3]);"
            "var width = Math.max(right - left, 1);"
            "var height = Math.max(bottom - top, 1);"
            "var targetWidth = Math.max(" + str(target.width) + " * 0.96, 1);"
            "var targetHeight = Math.max(" + str(target.height) + " * 0.96, 1);"
            "var scaleX = Math.min(100, targetWidth / width * 100);"
            "var scaleY = Math.min(100, targetHeight / height * 100);"
            "if (scaleX < 99.9 || scaleY < 99.9) fittedLayer.resize(scaleX, scaleY, AnchorPosition.MIDDLECENTER);"
            "bounds = fittedLayer.bounds;"
            "left = px(bounds[0]); top = px(bounds[1]); right = px(bounds[2]); bottom = px(bounds[3]);"
            "var centerX = (left + right) / 2;"
            "var centerY = (top + bottom) / 2;"
            "var targetCenterX = " + str(target.center_x) + ";"
            "var targetCenterY = " + str(target.center_y) + ";"
            "var dx = targetCenterX - centerX;"
            "var dy = targetCenterY - centerY;"
            "if (left + dx < " + str(target.left) + ") dx += " + str(target.left) + " - (left + dx);"
            "if (right + dx > " + str(target.right) + ") dx -= (right + dx) - " + str(target.right) + ";"
            "if (top + dy < " + str(target.top) + ") dy += " + str(target.top) + " - (top + dy);"
            "if (bottom + dy > " + str(target.bottom) + ") dy -= (bottom + dy) - " + str(target.bottom) + ";"
            "fittedLayer.translate(new UnitValue(dx, 'px'), new UnitValue(dy, 'px'));"
        )
        try:
            self.app.DoJavaScript(script)
            self._force_photoshop_update()
            return True
        except Exception as exc:
            logger.warning("Could not compress and position text layer '%s': %s", getattr(layer, "Name", ""), exc)
            return False

    def _get_accurate_text_bounds(self, layer: Any) -> Optional[tuple[float, float, float, float]]:
        if layer is None or not self._is_text_layer(layer):
            return None
        try:
            self._force_photoshop_update()
            bounds = getattr(layer, "Bounds", None)
            if bounds is None:
                return None
            values = [float(getattr(value, "Value", value)) for value in bounds]
            if len(values) == 4:
                return tuple(values)
        except Exception:
            return None
        return None

    def _find_best_text_area(self, group: Any, description_layer: Any) -> Optional[Bounds]:
        candidates: list[Bounds] = []
        for layer in self._get_visible_layers_in_group(group):
            if layer is description_layer:
                continue
            name = str(getattr(layer, "Name", "") or "").lower()
            if not any(token in name for token in ("shape", "rectangle", "retangulo", "ellipse", "elipse", "area", "texto")):
                continue
            bounds = self._bounds_signature(layer)
            if bounds is not None and self._valid_bounds(bounds):
                candidates.append(Bounds(*bounds))

        if candidates:
            return max(candidates, key=lambda b: b.width * b.height)

        try:
            group_bounds = self._bounds_signature(group)
            if group_bounds is not None:
                return Bounds(*group_bounds)
        except Exception:
            pass
        return None

    def _get_visible_layers_in_group(self, group: Any) -> list[Any]:
        result: list[Any] = []

        def walk(node: Any) -> None:
            if node is None:
                return
            try:
                layers = getattr(node, "Layers", None)
                if layers is not None:
                    for i in range(layers.Count):
                        layer = layers[i]
                        if layer is None:
                            continue
                        if not bool(getattr(layer, "Visible", True)):
                            continue
                        if str(getattr(layer, "typename", "")) == "ArtLayer":
                            result.append(layer)
                        elif str(getattr(layer, "typename", "")) == "LayerSet":
                            walk(layer)
            except Exception:
                pass

        walk(group)
        return result

    def _set_text_content(self, layer: Any, text: str) -> None:
        if layer is None or not self._is_text_layer(layer):
            return
        try:
            layer.TextItem.Contents = str(text)
        except Exception as exc:
            logger.warning("Failed to set description content on layer '%s': %s", getattr(layer, "Name", ""), exc)

    def _clear_and_set_text(self, layer: Any, new_text: str) -> None:
        self._clear_text_layer_completely(layer)
        self._set_text_content(layer, new_text)
        self._force_photoshop_update()

    def _clear_text_layer_completely(self, layer: Any) -> None:
        """Clear stale Photoshop text content before writing the replacement."""
        if layer is None or not self._is_text_layer(layer):
            return
        try:
            text_item = layer.TextItem
            text_item.Contents = ""
            self._force_photoshop_update()
            text_item.Contents = " "
            text_item.Contents = ""
            self._force_photoshop_update()
        except Exception as exc:
            logger.warning("Failed to completely clear text layer '%s': %s", getattr(layer, "Name", ""), exc)

    def _enable_paragraph_wrapping(self, layer: Any) -> None:
        if layer is None or not self._is_text_layer(layer):
            return
        try:
            text_item = getattr(layer, "TextItem", None)
            if text_item is not None:
                text_item.UseAutoLeading = True
                text_item.ParagraphJustification = 1
        except Exception:
            pass

    def _get_layer_bounds(self, layer: Any) -> Optional[tuple[float, float, float, float]]:
        if layer is None:
            return None
        try:
            bounds = getattr(layer, "Bounds", None)
            if bounds is None:
                return None
            values = [float(getattr(value, "Value", value)) for value in bounds]
            if len(values) == 4:
                return tuple(values)
        except Exception:
            return None
        return None

    def _should_force_line_break(
        self,
        description_layer: Any,
        group: Any,
        original_bounds: Optional[tuple[float, float, float, float]] = None,
    ) -> bool:
        desc_bounds = original_bounds or self._get_layer_bounds(description_layer)
        if not desc_bounds:
            return False

        desc_left, _, desc_right, _ = desc_bounds
        closest_price_left: Optional[float] = None
        price_tokens = ("preço", "preco", "por", "r$", "valor", "price", "badge", "de:")
        numeric_names = {"1", "2", "3", "4", "5", "6", "9", "18", "26"}
        for layer in self._get_visible_layers_in_group(group):
            if layer is description_layer:
                continue
            name = str(getattr(layer, "Name", "") or "").strip().lower()
            if not (any(token in name for token in price_tokens) or name in numeric_names):
                continue
            bounds = self._get_layer_bounds(layer)
            if not bounds or bounds[0] <= desc_left:
                continue
            if closest_price_left is None or bounds[0] < closest_price_left:
                closest_price_left = bounds[0]

        return closest_price_left is not None and closest_price_left - desc_right < 4.0

    def _find_closest_price_left(
        self,
        group: Any,
        desc_left: float,
        group_node: Optional[dict[str, Any]] = None,
        desc_bounds: Optional[Bounds] = None,
    ) -> Optional[float]:
        if group_node is not None:
            closest: Optional[float] = None

            def visit(node: dict[str, Any]) -> None:
                nonlocal closest
                if node.get("is_text"):
                    text = str(node.get("text") or "").strip().lower()
                    name = str(node.get("name") or "").strip().lower()
                    if not (
                        name.startswith("de") or name.startswith("r$") or name in {"un", "kg", "ml"}
                        or text.startswith("de") or text.startswith("r$") or text in {"un", "kg", "ml"}
                    ):
                        normalized = text.replace(",", "").replace(".", "")
                        is_price = (
                            any(token in name or token in text for token in ("preço", "preco", "por", "valor", "price"))
                            or name.isdigit()
                            or normalized.isdigit()
                            or any(token in text for token in (",99", ",49", ",90"))
                        )
                        bounds = node.get("bounds")
                        if is_price and isinstance(bounds, list) and len(bounds) == 4 and bounds[0] > desc_left + 40.0:
                            v_overlap = 1.0
                            if desc_bounds is not None:
                                v_overlap = min(desc_bounds.bottom, float(bounds[3])) - max(desc_bounds.top, float(bounds[1]))
                            if v_overlap > 0:
                                if closest is None or bounds[0] < closest:
                                    closest = float(bounds[0])
                for child in node.get("children", []):
                    if isinstance(child, dict):
                        visit(child)

            visit(group_node)
            return closest

        closest: Optional[float] = None
        price_tokens = ("preço", "preco", "por", "valor", "price")
        numeric_names = {"0", "1", "2", "3", "4", "5", "6", "7", "8", "9", "18", "26"}
        for layer in self._get_visible_layers_in_group(group):
            name = str(getattr(layer, "Name", "") or "").strip().lower()
            if name.startswith("de") or name.startswith("r$") or name in {"un", "kg", "ml"}:
                continue
            normalized_name = name.replace(",", "").replace(".", "")
            is_price = (
                any(token in name for token in price_tokens)
                or name in numeric_names
                or normalized_name.isdigit()
                or any(token in name for token in (",99", ",49", ",90"))
            )
            if not is_price:
                continue
            bounds = self._get_layer_bounds(layer)
            if bounds is None or bounds[0] <= desc_left + 40.0:
                continue
            if desc_bounds is not None:
                v_overlap = min(desc_bounds.bottom, bounds[3]) - max(desc_bounds.top, bounds[1])
                if v_overlap <= 0:
                    continue
            if closest is None or bounds[0] < closest:
                closest = bounds[0]
        return closest

    def _force_break_after_second_space(self, text: str) -> str:
        parts = str(text or "").strip().split()
        if len(parts) <= 2:
            return str(text or "").strip()
        return " ".join(parts[:2]) + "\r" + " ".join(parts[2:])

    @staticmethod
    def _force_break_after_next_space(text: str) -> str:
        value = str(text or "")
        start = value.rfind("\r")
        search_from = start + 1 if start >= 0 else 0
        position = value.find(" ", search_from)
        if position < 0:
            return value
        return value[:position] + "\r" + value[position + 1:]

    def _has_surrounding_collision(
        self,
        description_layer: Any,
        group: Any,
        description_bounds: Optional[tuple[float, float, float, float]] = None,
    ) -> bool:
        bounds = description_bounds or self._get_layer_bounds(description_layer)
        if bounds is None:
            return False
        description = Bounds(*bounds)
        for layer in self._get_visible_layers_in_group(group):
            if layer is description_layer:
                continue
            name = str(getattr(layer, "Name", "") or "").lower()
            if any(token in name for token in ("shape", "rectangle", "retangulo", "ellipse", "elipse", "smart", "image", "imagem", "foto", "img", "fundo")):
                continue
            other_bounds = self._get_layer_bounds(layer)
            if other_bounds is None:
                continue
            other = Bounds(*other_bounds)
            contains_description = (
                other.left <= description.left
                and other.top <= description.top
                and other.right >= description.right
                and other.bottom >= description.bottom
            )
            if contains_description:
                continue
            horizontal_gap = max(0.0, other.left - description.right, description.left - other.right)
            vertical_overlap = description.vertical_overlap(other)
            if vertical_overlap > 0 and horizontal_gap < 5.0:
                return True
        return False

    def aplicar_texto_com_quebra_sob_demanda(self, layer, texto: str, largura_colisao: float, largura_original: float, altura_original: float = 0.0):
        """
        Atualiza a camada de texto aplicando quebra de linha física (\n/\r) sob demanda.
        Aplica as quebras estritamente após o 2º espaço ou após o 1º espaço se colidir.
        """
        text_item = layer.TextItem
        try:
            tamanho_fonte = float(text_item.Size)
            tipo_texto = int(text_item.Kind)
        except Exception as e:
            text_item.Contents = texto
            self.logger.warning(f"Falha ao ler propriedades tipográficas da camada: {e}")
            return

        proporcao_caractere = 0.52  # Estimativa média de largura de caractere da fonte do encarte
        
        # 1. TENTATIVA 1: Testar o texto inteiro em uma única linha
        largura_estimada_total = len(texto) * (tamanho_fonte * proporcao_caractere)
        
        if largura_estimada_total <= largura_colisao:
            # Cabe perfeitamente sem colisão! Não quebra nada.
            text_item.Contents = texto
            self.logger.info(f"Slot '{texto[:15]}...' aplicado em linha única (sem colisão).")
            return

        # Se colidir, precisamos aplicar as regras de quebra física sob demanda
        palavras = texto.split()

        # 2. TENTATIVA 2: Quebra após o segundo espaço (se houver pelo menos 3 palavras)
        if len(palavras) >= 3:
            linha1 = " ".join(palavras[:2])
            linha2 = " ".join(palavras[2:])
            
            # Medimos se a linha mais longa desse novo bloco cabe na largura útil
            comprimento_maximo_linha = max(len(linha1), len(linha2))
            largura_estimada_quebra2 = comprimento_maximo_linha * (tamanho_fonte * proporcao_caractere)
            
            if largura_estimada_quebra2 <= largura_colisao:
                texto_final = f"{linha1}\r{linha2}"
                text_item.Contents = texto_final
                text_item.UseAutoLeading = False
                text_item.Leading = tamanho_fonte * 1.10
                if tipo_texto == 2 and altura_original > 0:
                    try:
                        text_item.Width = largura_colisao
                        text_item.Height = altura_original
                    except Exception:
                        pass
                self.logger.info(f"Slot '{texto[:15]}...' quebrado após o SEGUNDO espaço devido a colisão.")
                return

        # 3. TENTATIVA 3: Quebra após o primeiro espaço (se houver pelo menos 2 palavras)
        if len(palavras) >= 2:
            linha1 = palavras[0]
            linha2 = " ".join(palavras[1:])
            
            texto_final = f"{linha1}\r{linha2}"
            comprimento_maximo_linha = max(len(linha1), len(linha2))
            largura_estimada_quebra3 = comprimento_maximo_linha * (tamanho_fonte * proporcao_caractere)
            
            # Ajuste de fonte proporcional se ainda assim a linha 2 for muito longa
            if largura_estimada_quebra3 > largura_colisao:
                fator = max(0.65, min(1.0, largura_colisao / largura_estimada_quebra3))
                tamanho_fonte = tamanho_fonte * fator

            text_item.Contents = texto_final
            text_item.UseAutoLeading = False
            text_item.Size = tamanho_fonte
            text_item.Leading = tamanho_fonte * 1.10
            if tipo_texto == 2 and altura_original > 0:
                try:
                    text_item.Width = largura_colisao
                    text_item.Height = altura_original
                except Exception:
                    pass
            self.logger.info(f"Slot '{texto[:15]}...' quebrado após o PRIMEIRO espaço (necessidade secundária).")
            return

        # Se o produto for uma palavra só gigante (ex: 'Amaciante'), apenas insere o texto bruto
        text_item.Contents = texto

    def aplicar_texto_com_ajuste_veloz(self, layer, texto: str, largura_colisao: float, largura_original: float, altura_original: float = 0.0):
        """Alias para manter compatibilidade."""
        return self.aplicar_texto_com_quebra_sob_demanda(layer, texto, largura_colisao, largura_original, altura_original)

    def fit_description_with_collision_v2(
        self,
        description_layer: Any,
        group: Any,
        offer_name: str,
        *,
        group_node: Optional[dict[str, Any]] = None,
        preferred_font_scale: Optional[float] = None,
        preferred_line_spacing_scale: float = 0.9,
        min_scale: float = 0.45,
        max_scale: float = 1.05,
        min_margin: float = 5.0,
        max_iterations: int = 14,
        tolerance: float = 1.0,
    ) -> dict[str, Any]:
        report: dict[str, Any] = {
            "success": False,
            "original_font_size": None,
            "final_font_size": None,
            "final_text": offer_name,
            "message": "",
        }
        try:
            raw = self._get_layer_bounds(description_layer)
            if not raw:
                report["message"] = "Sem bounds da descrição"
                return report

            desc = Bounds(*raw)
            largura_original = desc.width
            altura_original = desc.height

            # Determina o limite à direita baseado no slot ou nos elementos na mesma faixa vertical
            price_left = self._find_closest_price_left(group, desc.left, group_node, desc_bounds=desc)
            if price_left is not None and price_left > desc.left + 40.0:
                right_limit = price_left - 7.0
            else:
                right_limit = desc.right + 220.0

            for layer in self._get_visible_layers_in_group(group):
                if layer is description_layer:
                    continue
                name = str(getattr(layer, "Name", "") or "").lower()
                bounds = self._get_layer_bounds(layer)
                if bounds is None:
                    continue
                is_price = any(
                    token in name
                    for token in ("preço", "preco", "r$", "por", "un", "kg", "ml", "pc", "badge", "price")
                ) or (name.startswith("de") and (name == "de" or name.startswith("de:") or name.startswith("de;")))
                if is_price:
                    price_bounds = Bounds(*bounds)
                    # CRÍTICO: Só restringe largura se houver SOBREPOSIÇÃO VERTICAL real (> 2px) e estiver à direita
                    v_overlap = desc.vertical_overlap(price_bounds)
                    if v_overlap > 2.0 and price_bounds.left > desc.left + 40.0:
                        right_limit = min(right_limit, price_bounds.left - 7.0)

            for layer in self._get_visible_layers_in_group(group):
                if layer is description_layer:
                    continue
                name = str(getattr(layer, "Name", "") or "").lower()
                if any(token in name for token in ("badge", "selo", "tag")):
                    bounds = self._get_layer_bounds(layer)
                    if bounds is not None:
                        b_bounds = Bounds(*bounds)
                        v_overlap = desc.vertical_overlap(b_bounds)
                        if v_overlap > 2.0 and b_bounds.left > desc.left + 40.0:
                            right_limit = min(right_limit, b_bounds.left - 7.0)

            left_limit = desc.left
            top_limit = desc.top - 8.0
            bottom_limit = desc.bottom + 65.0
            has_lower_blocker = False
            for layer in self._get_visible_layers_in_group(group):
                if layer is description_layer:
                    continue
                name = str(getattr(layer, "Name", "") or "").lower()
                if not any(token in name for token in ("preço", "preco", "r$", "badge", "price", "valor")):
                    continue
                bounds = self._get_layer_bounds(layer)
                if bounds is not None:
                    price_bounds = Bounds(*bounds)
                    h_overlap = desc.horizontal_overlap(price_bounds)
                    if price_bounds.top > desc.top and (h_overlap > 0 or abs(price_bounds.left - desc.left) < 60.0):
                        bottom_limit = min(bottom_limit, price_bounds.top - 7.0)
                        has_lower_blocker = True

            # Garante que right_limit nunca seja menor que desc.left + 85.0
            right_limit = max(right_limit, left_limit + 85.0)
            available_width = right_limit - left_limit
            safe_width = max(85.0, available_width)
            safe_height = max(35.0, bottom_limit - top_limit)
            if not has_lower_blocker:
                safe_height = max(78.0, safe_height)

            # Registra as métricas de colisão estritamente nos logs (NUNCA na camada do Photoshop)
            self.logger.info(f"[COLLISION] Largura calculada: {safe_width:.1f}px, Altura: {safe_height:.1f}px")

            # Executa o ajuste ultra-veloz em memória (sem loops de COM)
            self.aplicar_texto_com_ajuste_veloz(
                layer=description_layer,
                texto=offer_name,
                largura_colisao=safe_width,
                largura_original=largura_original,
                altura_original=safe_height,
            )

            report["success"] = True
            report["message"] = "OK"
            try:
                report["final_text"] = str(getattr(description_layer.TextItem, "Contents", offer_name))
            except Exception:
                report["final_text"] = offer_name
            try:
                report["final_font_size"] = float(description_layer.TextItem.Size)
            except Exception:
                pass
            return report
        except Exception as exc:
            report["message"] = str(exc)
            logger.exception("Erro em fit_description_with_collision_v2: %s", exc)
            return report

    @staticmethod
    def _make_save_options(format_name: str) -> Any:
        import win32com.client  # type: ignore

        cls_name = "Photoshop.JPEGSaveOptions" if format_name.upper() == "JPG" else "Photoshop.PNGSaveOptions"
        return win32com.client.Dispatch(cls_name)

    @staticmethod
    def _normalize_jpeg_quality(quality: int) -> int:
        value = max(0, min(100, int(quality)))
        return max(1, min(12, int(round(value / 100 * 12))))

    @staticmethod
    def _bounds_signature(layer: Any) -> Optional[tuple[float, float, float, float]]:
        try:
            values = []
            for value in layer.Bounds:
                values.append(float(getattr(value, "Value", value)))
            if len(values) == 4:
                return tuple(values)  # type: ignore[return-value]
        except Exception:
            return None
        return None

    def _wait_for_update(self, delay: float = 1.0) -> None:
        """Allow Photoshop to finish asynchronous layer updates before continuing."""
        time.sleep(delay)

    def _fit_layer_to_bounds(self, layer: Any, target: tuple[float, float, float, float]) -> None:
        target_left, target_top, target_right, target_bottom = target
        target_width = max(target_right - target_left, 1.0) * 0.90
        target_height = max(target_bottom - target_top, 1.0) * 0.90
        target_center_x = (target_left + target_right) / 2.0
        target_center_y = (target_top + target_bottom) / 2.0

        layer_id = int(getattr(layer, "ID"))
        script = (
            "function findLayer(container, targetId) {"
            "  for (var i = 0; i < container.layers.length; i++) {"
            "    var candidate = container.layers[i];"
            "    if (candidate.id == targetId) return candidate;"
            "    if (candidate.typename == 'LayerSet') {"
            "      var nested = findLayer(candidate, targetId);"
            "      if (nested) return nested;"
            "    }"
            "  }"
            "  return null;"
            "}"
            "function px(value) { return value.as('px'); }"
            "var fittedLayer = findLayer(app.activeDocument, " + str(layer_id) + ");"
            "if (!fittedLayer) throw new Error('Layer not found for fitting');"
            "var bounds = fittedLayer.bounds;"
            "var width = Math.max(px(bounds[2]) - px(bounds[0]), 1);"
            "var height = Math.max(px(bounds[3]) - px(bounds[1]), 1);"
            "var scale = Math.min(" + str(target_width) + " / width, " + str(target_height) + " / height) * 100;"
            "if (Math.abs(scale - 100) > 0.1) fittedLayer.resize(scale, scale, AnchorPosition.MIDDLECENTER);"
            "bounds = fittedLayer.bounds;"
            "var centerX = (px(bounds[0]) + px(bounds[2])) / 2;"
            "var centerY = (px(bounds[1]) + px(bounds[3])) / 2;"
            "fittedLayer.translate(new UnitValue(" + str(target_center_x) + " - centerX, 'px'), "
            "new UnitValue(" + str(target_center_y) + " - centerY, 'px'));"
        )
        self.app.DoJavaScript(script)

    def _fit_text_to_bounds(
        self,
        layer: Any,
        target: tuple[float, float, float, float],
        anchor: Optional[tuple[float, float, float, float]] = None,
        horizontal_center: Optional[float] = None,
        blocking_bounds: Optional[list[tuple[float, float, float, float]]] = None,
    ) -> None:
        """Wrap replacement text while preserving its original font size and slot."""
        target_left, target_top, target_right, target_bottom = target
        target_width = max(target_right - target_left, 1.0) * 0.96
        target_height = max(target_bottom - target_top, 1.0) * 0.96
        anchor_bounds = anchor or target
        target_center_x = horizontal_center if horizontal_center is not None else (anchor_bounds[0] + anchor_bounds[2]) / 2.0
        target_center_y = (target_top + target_bottom) / 2.0
        layer_id = int(getattr(layer, "ID"))
        blockers_literal = json.dumps(blocking_bounds or [])
        script = (
            "function findLayer(container, targetId) {"
            "  for (var i = 0; i < container.layers.length; i++) {"
            "    var candidate = container.layers[i];"
            "    if (candidate.id == targetId) return candidate;"
            "    if (candidate.typename == 'LayerSet') {"
            "      var nested = findLayer(candidate, targetId);"
            "      if (nested) return nested;"
            "    }"
            "  }"
            "  return null;"
            "}"
            "function px(value) { return value.as('px'); }"
            "var fittedLayer = findLayer(app.activeDocument, " + str(layer_id) + ");"
            "if (!fittedLayer) throw new Error('Text layer not found for fitting');"
            "var textItem = fittedLayer.textItem;"
            "textItem.useAutoLeading = true;"
            "var words = textItem.contents.replace(/\\r?\\n/g, ' ').split(/\\s+/);"
            "var lines = [];"
            "var current = '';"
            "for (var i = 0; i < words.length; i++) {"
            "  if (!words[i]) continue;"
            "  var candidate = current ? current + ' ' + words[i] : words[i];"
            "  textItem.contents = candidate;"
            "  var measured = fittedLayer.bounds;"
            "  var measuredWidth = Math.max(px(measured[2]) - px(measured[0]), 1);"
            "  if (current && measuredWidth > " + str(target_width) + ") {"
            "    lines.push(current);"
            "    current = words[i];"
            "  } else {"
            "    current = candidate;"
            "  }"
            "}"
            "if (current) lines.push(current);"
            "textItem.contents = lines.join('\\r');"
            "var blockers = " + blockers_literal + ";"
            "function overlaps(a, b, gap) {"
            "  return a[0] < b[2] + gap && a[2] > b[0] - gap && a[1] < b[3] + gap && a[3] > b[1] - gap;"
            "}"
            "var bounds = fittedLayer.bounds;"
            "var collision = false;"
            "var currentBounds = [px(bounds[0]), px(bounds[1]), px(bounds[2]), px(bounds[3])];"
            "for (var b = 0; b < blockers.length; b++) {"
            "  if (overlaps(currentBounds, blockers[b], 6)) { collision = true; break; }"
            "}"
            "if (collision) {"
            "  $.writeln('Autoflyer: description kept original PSD font size but still exceeds available space.');"
            "}"
            "var currentCenterX = (px(bounds[0]) + px(bounds[2])) / 2;"
            "fittedLayer.translate(new UnitValue(" + str(target_center_x) + " - currentCenterX, 'px'), new UnitValue(0, 'px'));"
        )
        self.app.DoJavaScript(script)

    @staticmethod
    def _find_price_group(group: Any) -> Any:
        if not hasattr(group, "LayerSets"):
            return None
        try:
            for index in range(group.LayerSets.Count):
                layer_set = group.LayerSets[index]
                name = str(getattr(layer_set, "Name", "") or "").upper()
                if any(token in name for token in ("PRE", "PRICE", "PREÇO", "PRECO")):
                    return layer_set
        except Exception:
            return None
        return None

    @staticmethod
    def _description_safe_bounds(
        description_bounds: tuple[float, float, float, float],
        text_area: tuple[float, float, float, float],
        blocking_bounds: list[tuple[float, float, float, float]],
    ) -> tuple[float, float, float, float]:
        """Find the nearest free rectangle around a description layer."""
        left, top, right, bottom = text_area
        gap = max((bottom - top) * 0.04, 8.0)
        for blocker in blocking_bounds:
            vertical_overlap = description_bounds[1] < blocker[3] and blocker[1] < description_bounds[3]
            horizontal_overlap = description_bounds[0] < blocker[2] and blocker[0] < description_bounds[2]
            if vertical_overlap:
                if blocker[0] >= description_bounds[2] - gap:
                    right = min(right, blocker[0] - gap)
                elif blocker[2] <= description_bounds[0] + gap:
                    left = max(left, blocker[2] + gap)
            if horizontal_overlap and blocker[1] >= description_bounds[3] - gap:
                bottom = min(bottom, blocker[1] - gap)
            elif horizontal_overlap and blocker[3] <= description_bounds[1] + gap:
                top = max(top, blocker[3] + gap)
        if bottom <= top + 4:
            bottom = description_bounds[3]
        if right <= left + 12:
            right = left + 12
        return left, top, right, max(bottom, top + 4)

    @staticmethod
    def _bounds_union(bounds_list: list[tuple[float, float, float, float]]) -> Optional[tuple[float, float, float, float]]:
        if not bounds_list:
            return None
        return (
            min(bounds[0] for bounds in bounds_list),
            min(bounds[1] for bounds in bounds_list),
            max(bounds[2] for bounds in bounds_list),
            max(bounds[3] for bounds in bounds_list),
        )

    @classmethod
    def _description_blockers(cls, group: Any, description_layer: Any) -> list[tuple[float, float, float, float]]:
        blockers = []
        for layer in cls._iter_layers(group):
            if layer is description_layer or not bool(getattr(layer, "Visible", True)):
                continue
            if not (cls._is_text_layer(layer) or int(getattr(layer, "Kind", 0)) == 17):
                continue
            bounds = cls._bounds_signature(layer)
            if bounds is not None and cls._valid_bounds(bounds):
                blockers.append(bounds)
        return blockers

    @staticmethod
    def _image_target_bounds(
        shape: tuple[float, float, float, float],
        description_bounds: Optional[tuple[float, float, float, float]],
    ) -> tuple[float, float, float, float]:
        left, top, right, bottom = shape
        margin_x = max((right - left) * 0.08, 4.0)
        margin_y = max((bottom - top) * 0.08, 4.0)
        top += margin_y
        bottom -= margin_y
        if description_bounds is not None:
            # Keep a visible gap between the description and the image area.
            top = max(top, description_bounds[3] + max((bottom - top) * 0.10, 12.0))
        if bottom <= top:
            top, bottom = shape[1] + margin_y, shape[3] - margin_y
        return left + margin_x, top, right - margin_x, bottom

    @staticmethod
    def _preserve_image_position(
        image_bounds: tuple[float, float, float, float],
        shape_bounds: Optional[tuple[float, float, float, float]],
    ) -> tuple[float, float, float, float]:
        """Keep the Smart Object position; use the shape only as a size limit."""
        if shape_bounds is None:
            return image_bounds
        image_width = max(image_bounds[2] - image_bounds[0], 1.0)
        image_height = max(image_bounds[3] - image_bounds[1], 1.0)
        shape_width = max(shape_bounds[2] - shape_bounds[0], 1.0)
        shape_height = max(shape_bounds[3] - shape_bounds[1], 1.0)
        scale = min(1.0, shape_width / image_width, shape_height / image_height)
        center_x = (image_bounds[0] + image_bounds[2]) / 2.0
        center_y = (image_bounds[1] + image_bounds[3]) / 2.0
        width = image_width * scale
        height = image_height * scale
        return (
            center_x - width / 2.0,
            center_y - height / 2.0,
            center_x + width / 2.0,
            center_y + height / 2.0,
        )

    @staticmethod
    def _valid_bounds(bounds: Optional[tuple[float, float, float, float]]) -> bool:
        return bool(
            bounds is not None
            and bounds[2] > bounds[0] + 2
            and bounds[3] > bounds[1] + 2
        )

    def replace_smart_object(self, layer_name: str, image_path: str | Path) -> bool:
        if self.app is None:
            logger.info("Stub mode: smart object '%s' would be replaced with %s", layer_name, image_path)
            return True

        try:
            doc = self.app.ActiveDocument
            if doc is None:
                return False
            for layer in self._iter_layers(doc):
                if getattr(layer, "Name", "") == layer_name and self._replace_smart_object_layer(doc, layer, image_path):
                    return True
            logger.warning("Smart object '%s' not found in Photoshop document.", layer_name)
            return False
        except Exception as exc:  # pragma: no cover - COM fallback
            logger.warning("Failed to replace smart object '%s': %s", layer_name, exc)
            return False

    def _replace_smart_object_layer(
        self,
        doc: Any,
        layer: Any,
        image_path: str | Path,
        original_bounds: Optional[tuple[float, float, float, float]] = None,
    ) -> bool:
        try:
            if int(getattr(layer, "Kind", 0)) != 17:
                return False

            before = original_bounds or self._bounds_signature(layer)
            path_literal = str(Path(image_path).resolve()).replace("\\", "\\\\").replace('"', '\\"')
            layer_id = int(getattr(layer, "ID"))
            script = (
                'function findLayer(container, targetId) {'
                '  for (var i = 0; i < container.layers.length; i++) {'
                '    var candidate = container.layers[i];'
                '    if (candidate.id == targetId) return candidate;'
                '    if (candidate.typename == "LayerSet") {'
                '      var nested = findLayer(candidate, targetId);'
                '      if (nested) return nested;'
                '    }'
                '  }'
                '  return null;'
                '}'
                'var targetLayer = findLayer(app.activeDocument, ' + str(layer_id) + ');'
                'if (!targetLayer) throw new Error("Layer not found: ' + str(layer_id) + '");'
                'app.activeDocument.activeLayer = targetLayer;'
                'var descriptor = new ActionDescriptor();'
                'descriptor.putPath(charIDToTypeID("null"), new File("' + path_literal + '"));'
                'executeAction(stringIDToTypeID("placedLayerReplaceContents"), descriptor, DialogModes.NO);'
            )
            self.app.DoJavaScript(script)
            layer.Visible = True
            self._wait_for_update()
            if before is not None:
                self._fit_layer_to_bounds(layer, before)
                logger.info("Fitted Smart Object '%s' inside its original slot bounds.", getattr(layer, "Name", ""))
            logger.info("Replaced smart object '%s' with %s", getattr(layer, "Name", ""), image_path)
            return True
        except Exception as exc:  # pragma: no cover - COM fallback
            logger.warning("Failed to replace Smart Object '%s': %s", getattr(layer, "Name", ""), exc)
            return False

    def update_offer_slot(self, offer: Any, slot_number: Optional[int] = None) -> bool:
        target_slot = slot_number if slot_number is not None else getattr(offer, "slot", None)
        if target_slot is None:
            logger.warning("No slot number available for offer %s", offer)
            return False

        if self.app is None:
            logger.info("Stub mode: offer slot %s would be mapped to PSD group %s", target_slot, target_slot)
            return True

        try:
            doc = self.app.ActiveDocument
            if doc is None:
                logger.warning("Photoshop document not open for slot %s", target_slot)
                return False

            group_node = self._native_slot_node(int(target_slot))
            group = self._layer_from_native_node(group_node) or self._find_slot_group(doc, int(target_slot))
            if group is None:
                logger.warning("Could not find PSD slot group for slot %s", target_slot)
                return False

            # O nome do produto deve ser estritamente o da oferta (planilha/IA ortográfica),
            # eliminando qualquer risco de vazamento de debug ou alucinações de layout.
            product_name = getattr(offer, "nome", "") or ""
            changed = False
            shape_references = self._shape_references(group)
            price_group = self._find_price_group(group)
            price_container = price_group or group
            price_layers = self._text_layers(price_container)
            description_bounds = None
            if product_name:
                structured_description = self._native_description_node(group_node)
                description_layer = (
                    self._layer_from_native_node(structured_description)
                    if structured_description is not None
                    else None
                ) or self._find_description_layer(group)
                if description_layer is not None:
                    description_bounds = self._bounds_signature(description_layer)
                    blocking_bounds = self._description_blockers(group, description_layer)
                    if description_bounds is not None:
                        try:
                            try:
                                result = self.fit_description_with_collision_v2(
                                    description_layer,
                                    group,
                                    product_name,
                                    group_node=group_node,
                                    preferred_font_scale=self.description_font_scales.get(int(target_slot)),
                                    preferred_line_spacing_scale=self.description_line_spacing_scales.get(int(target_slot), 0.9),
                                    min_scale=0.45,
                                    max_scale=1.05,
                                    min_margin=5.0,
                                    max_iterations=14,
                                    tolerance=1.0,
                                )
                                changed = True
                                if not result.get("success", False):
                                    logger.warning(
                                        "Slot %s description fallback warning: %s",
                                        target_slot,
                                        result.get("message", "Ajuste não concluído"),
                                    )
                            except Exception as exc:
                                logger.warning("Could not use v2 collision fit for layer '%s': %s", getattr(description_layer, "Name", ""), exc)
                                self._fit_description_layer_with_collision(
                                    group,
                                    description_layer,
                                    description_bounds,
                                    shape_references,
                                    blocking_bounds,
                                    target_slot,
                                )
                                changed = True
                            description_bounds = self._bounds_signature(description_layer) or description_bounds
                        except Exception as exc:
                            logger.warning("Could not fit description layer '%s': %s", getattr(description_layer, "Name", ""), exc)
                    else:
                        changed = self._apply_text_value(description_layer, product_name) or changed
                else:
                    logger.warning("No description text layer found in slot %s", target_slot)

            image_path = getattr(offer, "imagem", None)
            if image_path:
                image_layers = self._smart_objects_with_bounds(group)
                if image_layers:
                    used_shapes: set[int] = set()
                    for layer, image_bounds in image_layers:
                        reference_bounds = self._match_shape_to_image(image_bounds, shape_references, used_shapes)
                        target_bounds = self._preserve_image_position(image_bounds, reference_bounds)
                        if not self._valid_bounds(target_bounds):
                            target_bounds = image_bounds
                        logger.info("Using image target bounds for slot %s: %s", target_slot, target_bounds)
                        image_replaced = self._replace_smart_object_layer(doc, layer, image_path, target_bounds)
                        if image_replaced:
                            changed = True
                        else:
                            logger.warning("Could not replace image Smart Object '%s' in slot %s", getattr(layer, "Name", ""), target_slot)
                else:
                    logger.warning("No measurable image Smart Object found in slot %s", target_slot)

            if price_group is not None and hasattr(price_group, "ArtLayers"):
                price_layers = [price_group.ArtLayers[i] for i in range(price_group.ArtLayers.Count)]
                numeric_layers = [
                    layer for layer in price_layers
                    if self._is_text_layer(layer) and re.fullmatch(r"\d+", self._text_content(layer))
                ]
                price_value = float(getattr(offer, "preco_por", 0) or 0)
                inteiro = int(price_value)
                cents = int(round((price_value - inteiro) * 100))
                if len(numeric_layers) >= 2:
                    changed = self._apply_text_value(numeric_layers[-2], str(cents).zfill(2)) or changed
                    changed = self._apply_text_value(numeric_layers[-1], str(inteiro)) or changed

                combined_layers = [
                    layer for layer in price_layers
                    if self._is_text_layer(layer) and re.fullmatch(r"\d+[,.]\d{2}", self._text_content(layer))
                ]
                for layer in combined_layers:
                    changed = self._apply_text_value(layer, f"{price_value:.2f}".replace(".", ",")) or changed

                for layer in price_layers:
                    if not self._is_text_layer(layer):
                        continue
                    name = getattr(layer, "Name", "") or ""
                    upper = name.upper().strip()
                    current = self._text_content(layer).upper().strip()
                    if self._is_unit_layer(upper, current):
                        unit = getattr(offer, "unidade", None) or current or upper
                        changed = self._apply_text_value(layer, str(unit).upper()) or changed
                    elif re.match(r"^DE", current):
                        changed = self._apply_text_value(layer, f"DE;{float(getattr(offer, 'preco_de', 0) or 0):.2f}".replace('.', ',')) or changed
                    elif upper in {"POR", "R$"}:
                        changed = self._apply_text_value(layer, upper) or changed
                    elif upper == ",":
                        changed = self._apply_text_value(layer, ",") or changed

            if price_group is None:
                price_layers = self._text_layers(group)
                price_value = float(getattr(offer, "preco_por", 0) or 0)
                inteiro = int(price_value)
                cents = int(round((price_value - inteiro) * 100))
                integer_layers = [
                    layer for layer in price_layers
                    if re.fullmatch(r"\d+", self._text_content(layer))
                ]
                decimal_layers = [
                    layer for layer in price_layers
                    if re.fullmatch(r"[,\.]\d{2}", self._text_content(layer))
                ]
                if decimal_layers:
                    changed = self._apply_text_value(decimal_layers[0], f",{cents:02d}") or changed
                if integer_layers:
                    changed = self._apply_text_value(integer_layers[-1], str(inteiro)) or changed

                combined_layers = [
                    layer for layer in price_layers
                    if self._is_text_layer(layer) and re.fullmatch(r"\d+[,.]\d{2}", self._text_content(layer))
                ]
                for layer in combined_layers:
                    changed = self._apply_text_value(layer, f"{price_value:.2f}".replace(".", ",")) or changed

                for layer in price_layers:
                    text = self._text_content(layer).upper().strip()
                    if self._is_unit_layer(getattr(layer, "Name", ""), text):
                        unit = getattr(offer, "unidade", None)
                        if unit:
                            changed = self._apply_text_value(layer, str(unit).upper()) or changed
                    elif re.match(r"^(?:DE|BD)\b", text):
                        value = getattr(offer, "preco_de", None)
                        if value is not None:
                            changed = self._apply_text_value(layer, f"DE;{float(value):.2f}".replace(".", ",")) or changed

            self._wait_for_update(0.5)
            if not changed:
                logger.warning("No editable text layer was changed for offer %s in PSD slot %s", getattr(offer, 'nome', ''), target_slot)
                return False
            logger.info("Applied offer %s into PSD slot %s", getattr(offer, 'nome', ''), target_slot)
            return True
        except Exception as exc:  # pragma: no cover - COM fallback
            logger.warning("Failed to apply offer to slot %s: %s", target_slot, exc)
            return False

    def export_image(self, output_path: str | Path, file_format: str = "JPG", quality: int = 90) -> Path:
        target = Path(output_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        format_name = str(file_format).upper()

        if format_name == "PNG":
            return self.export_png(target, quality=quality)
        return self.export_jpeg(target, quality=quality)

    def export_jpeg(self, output_path: str | Path, quality: int = 90) -> Path:
        target = Path(output_path).resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        if self.app is not None:
            for attempt in range(3):
                try:
                    self._wait_for_update(0.5)
                    doc = self.app.ActiveDocument
                    if doc is not None:
                        jpg_options = self._make_save_options("JPG")
                        jpg_options.Quality = self._normalize_jpeg_quality(quality)
                        doc.SaveAs(str(target), jpg_options, True)
                        logger.info("Exported JPEG via Photoshop: %s", target)
                        return target
                except Exception as exc:  # pragma: no cover - COM fallback
                    logger.warning("Photoshop export failed on attempt %s/%s: %s", attempt + 1, 3, exc)
                    if attempt < 2:
                        time.sleep(0.5 * (attempt + 1))

        if self.photoshop_installed:
            logger.warning(
                "Photoshop is detected as installed, but COM could not be initialized. "
                "The export will use the PSD preview fallback instead of the real Photoshop export."
            )

        if self.template_path is not None and self.template_path.exists():
            logger.info("Using PSD preview fallback for JPEG export: %s", self.template_path)
            return self._render_template_fallback(target)

        from PIL import Image, ImageDraw

        image = Image.new("RGB", (1600, 900), color=(255, 255, 255))
        draw = ImageDraw.Draw(image)
        draw.text((80, 80), "Autoflyer", fill=(0, 0, 0))
        draw.text((80, 140), "Arte em modo fallback", fill=(60, 60, 60))
        image.save(target, format="JPEG", quality=quality)
        logger.info("Generated non-empty fallback JPEG preview at %s", target)
        return target

    def export_png(self, output_path: str | Path, quality: int = 90) -> Path:
        target = Path(output_path).resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        if self.app is not None:
            for attempt in range(3):
                try:
                    self._wait_for_update(0.5)
                    doc = self.app.ActiveDocument
                    if doc is not None:
                        png_options = self._make_save_options("PNG")
                        png_options.Compression = 9
                        doc.SaveAs(str(target), png_options, True)
                        logger.info("Exported PNG via Photoshop: %s", target)
                        return target
                except Exception as exc:  # pragma: no cover - COM fallback
                    logger.warning("Photoshop PNG export failed on attempt %s/%s: %s", attempt + 1, 3, exc)
                    if attempt < 2:
                        time.sleep(0.5 * (attempt + 1))

        if self.photoshop_installed:
            logger.warning(
                "Photoshop is detected as installed, but COM could not be initialized. "
                "The export will use the PSD preview fallback instead of the real Photoshop export."
            )

        if self.template_path is not None and self.template_path.exists():
            logger.info("Using PSD preview fallback for PNG export: %s", self.template_path)
            return self._render_template_fallback(target)

        from PIL import Image, ImageDraw

        image = Image.new("RGB", (1600, 900), color=(255, 255, 255))
        draw = ImageDraw.Draw(image)
        draw.text((80, 80), "Autoflyer", fill=(0, 0, 0))
        draw.text((80, 140), "Arte em modo fallback", fill=(60, 60, 60))
        image.save(target, format="PNG")
        logger.info("Generated non-empty fallback PNG preview at %s", target)
        return target
