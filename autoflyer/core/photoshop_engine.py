from __future__ import annotations

import logging
import os
import re
import shutil
import time
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
                while self.app.Documents.Count > 0:
                    self.app.ActiveDocument.Close(2)
            except Exception:
                pass
            try:
                self.app.Open(str(path))
                logger.info("Opened PSD template in Photoshop: %s", path)
                return True
            except Exception as exc:  # pragma: no cover - COM fallback
                logger.warning("Could not open template in Photoshop via COM: %s", exc)

        logger.info("Using PSD fallback preview mode to process template: %s", path)
        return True

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
        for layer in self._iter_layers(doc):
            name = getattr(layer, "Name", "") or ""
            if not name:
                continue
            upper = name.upper()
            if "DESCRI" in upper and "PRE" in upper and (f"{slot_number}" in name or target_token in name):
                return layer
        return None

    @staticmethod
    def _is_text_layer(layer: Any) -> bool:
        try:
            kind = getattr(layer, "Kind", None)
            return kind is not None and int(kind) == 2
        except Exception:
            return False

    def _apply_text_value(self, layer: Any, value: str) -> None:
        if layer is None or not self._is_text_layer(layer):
            return
        try:
            layer.TextItem.Contents = str(value)
        except Exception as exc:  # pragma: no cover - COM fallback
            logger.warning("Failed to set text on layer '%s': %s", getattr(layer, "Name", ""), exc)

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
        if self.app is None:
            return
        try:
            self.app.DoJavaScript("app.refresh();")
            time.sleep(0.25)
        except Exception:
            logger.debug("Photoshop refresh is unavailable; continuing after delay.", exc_info=True)

    def _fit_layer_to_bounds(self, layer: Any, target: tuple[float, float, float, float]) -> None:
        target_left, target_top, target_right, target_bottom = target
        target_width = max(target_right - target_left, 1.0)
        target_height = max(target_bottom - target_top, 1.0)
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
            layer.Visible = False
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
            if product_name and hasattr(group, "ArtLayers"):
                for i in range(group.ArtLayers.Count):
                    layer = group.ArtLayers[i]
                    name = getattr(layer, "Name", "") or ""
                    upper = name.upper()
                    if "IMAGEM" in upper or "PRE" in upper or "FORMA" in upper or re.fullmatch(r"[\d,.;\-]+", name.strip()):
                        continue
                    if self._is_text_layer(layer):
                        self._apply_text_value(layer, product_name)
                        break

            image_path = getattr(offer, "imagem", None)
            if image_path and hasattr(group, "LayerSets"):
                for i in range(group.LayerSets.Count):
                    layer_set = group.LayerSets[i]
                    if "IMAGEM" in getattr(layer_set, "Name", "").upper():
                        image_layers = [
                            (layer, self._bounds_signature(layer))
                            for layer in self._iter_layers(layer_set)
                            if int(getattr(layer, "Kind", 0)) == 17
                        ]
                        for layer, original_bounds in image_layers:
                            self._replace_smart_object_layer(doc, layer, image_path, original_bounds)
                        break

            price_group = None
            if hasattr(group, "LayerSets"):
                for i in range(group.LayerSets.Count):
                    layer_set = group.LayerSets[i]
                    name = getattr(layer_set, "Name", "") or ""
                    upper = name.upper()
                    if "PRE" in upper:
                        price_group = layer_set
                        break
            if price_group is not None and hasattr(price_group, "ArtLayers"):
                price_layers = [price_group.ArtLayers[i] for i in range(price_group.ArtLayers.Count)]
                numeric_layers = [
                    layer for layer in price_layers
                    if self._is_text_layer(layer) and re.fullmatch(r"\d+", getattr(layer, "Name", "").strip())
                ]
                price_value = float(getattr(offer, "preco_por", 0) or 0)
                inteiro = int(price_value)
                cents = int(round((price_value - inteiro) * 100))
                if len(numeric_layers) >= 2:
                    self._apply_text_value(numeric_layers[-2], str(cents).zfill(2))
                    self._apply_text_value(numeric_layers[-1], str(inteiro))

                for layer in price_layers:
                    if not self._is_text_layer(layer):
                        continue
                    name = getattr(layer, "Name", "") or ""
                    upper = name.upper().strip()
                    if re.match(r"^DE", upper):
                        self._apply_text_value(layer, f"DE;{float(getattr(offer, 'preco_de', 0) or 0):.2f}".replace('.', ','))
                    elif upper in {"POR", "R$"}:
                        self._apply_text_value(layer, upper)
                    elif upper in {"KG", "UN", "LT", "CX", "PCT", "G", "ML"}:
                        unit = getattr(offer, "unidade", None) or upper
                        self._apply_text_value(layer, str(unit).upper())
                    elif upper == ",":
                        self._apply_text_value(layer, ",")

            self._wait_for_update(0.5)
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
