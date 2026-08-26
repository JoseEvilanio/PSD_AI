from __future__ import annotations

import json
import logging
import os
import re
import shutil
import time
import unicodedata
from pathlib import Path
from typing import Any, Iterator, Optional

logger = logging.getLogger(__name__)


class PhotoshopEngine:
    """Wrapper for Adobe Photoshop automation.

    On Windows with Adobe Photoshop installed, it will attempt to connect to the
    COM interface. If Photoshop is unavailable, it falls back to a safe stub so
    the app remains usable in development and test environments.
    """

    def __init__(self, visible: bool = True, display_dialogs: bool = False):
        self.visible = visible
        self.display_dialogs = display_dialogs
        self.app: Optional[Any] = None
        self.template_path: Optional[Path] = None
        self.photoshop_installed = self._is_photoshop_installed()
        self.com_error: Optional[str] = None
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
            "children": [],
        }
        if cls._is_text_layer(layer):
            node["text"] = cls._text_content(layer)

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

    def export_native_layer_tree_json(self, output_path: str | Path) -> Optional[Path]:
        """Save the open Photoshop DOM tree as UTF-8 JSON, when COM is available."""
        tree = self.get_native_layer_tree()
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

    def _apply_text_value(self, layer: Any, value: str) -> bool:
        if layer is None or not self._is_text_layer(layer):
            return False
        try:
            expected = str(value)
            layer.TextItem.Contents = expected
            actual = str(layer.TextItem.Contents)
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

            group = self._find_slot_group(doc, int(target_slot))
            if group is None:
                logger.warning("Could not find PSD slot group for slot %s", target_slot)
                return False

            product_name = getattr(offer, "nome", "") or ""
            changed = False
            shape_references = self._shape_references(group)
            price_group = self._find_price_group(group)
            price_container = price_group or group
            price_layers = self._text_layers(price_container)
            description_bounds = None
            if product_name:
                description_layer = self._find_description_layer(group)
                if description_layer is not None:
                    description_bounds = self._bounds_signature(description_layer)
                    blocking_bounds = self._description_blockers(group, description_layer)
                    changed = self._apply_text_value(description_layer, product_name) or changed
                    if description_bounds is not None and shape_references:
                        try:
                            description_shape = min(
                                shape_references,
                                key=lambda shape: (
                                    ((shape[0] + shape[2]) / 2.0 - (description_bounds[0] + description_bounds[2]) / 2.0) ** 2
                                    + ((shape[1] + shape[3]) / 2.0 - (description_bounds[1] + description_bounds[3]) / 2.0) ** 2
                                ),
                            )
                            description_shape_center_x = (description_shape[0] + description_shape[2]) / 2.0
                            safe_description_shape = self._description_safe_bounds(
                                description_bounds,
                                description_shape,
                                blocking_bounds,
                            )
                            self._fit_text_to_bounds(
                                description_layer,
                                safe_description_shape,
                                description_bounds,
                                horizontal_center=(safe_description_shape[0] + safe_description_shape[2]) / 2.0,
                                blocking_bounds=blocking_bounds,
                            )
                            description_bounds = self._bounds_signature(description_layer) or description_bounds
                        except Exception as exc:
                            logger.warning("Could not fit description layer '%s': %s", getattr(description_layer, "Name", ""), exc)
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
