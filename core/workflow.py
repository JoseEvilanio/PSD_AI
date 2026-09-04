from __future__ import annotations

import logging
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from .data_loader import DataLoader
from .ai_provider import AIProvider
from .ai_generator import AIOfferGenerator
from .intelligent_inspector import IntelligentInspector
from .photoshop_engine import PhotoshopEngine
from .psd_template_inspector import PsdTemplateInspector
from .template_manager import TemplateManager
from .validator import Validator

logger = logging.getLogger(__name__)
BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = BASE_DIR / "config" / "settings.yaml"


def configure_logging() -> None:
    logs_dir = BASE_DIR / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] %(levelname)s %(message)s",
        handlers=[
            logging.FileHandler(logs_dir / "autoflyer.log", encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )


def load_settings() -> dict:
    if not CONFIG_PATH.exists():
        return {
            "paths": {
                "templates_dir": "data/templates",
                "products_dir": "data/products",
                "inputs_dir": "data/inputs",
                "outputs_dir": "data/outputs",
                "logs_dir": "logs",
            },
            "photoshop": {"visible": True, "display_dialogs": False},
            "export": {"format": "JPG", "quality": 90},
        }
    with CONFIG_PATH.open("r", encoding="utf-8") as fh:
        return __import__("yaml").safe_load(fh) or {}


def console_smoke_test() -> None:
    settings = load_settings()
    data_dir = BASE_DIR / settings.get("paths", {}).get("inputs_dir", "data/inputs")
    templates_dir = BASE_DIR / settings.get("paths", {}).get("templates_dir", "data/templates")
    products_dir = BASE_DIR / settings.get("paths", {}).get("products_dir", "data/products")

    data_dir.mkdir(parents=True, exist_ok=True)
    templates_dir.mkdir(parents=True, exist_ok=True)
    products_dir.mkdir(parents=True, exist_ok=True)

    default_template = TemplateManager.find_default_template(BASE_DIR)
    if default_template is not None:
        templates_dir = default_template.parent

    loader = DataLoader(products_dir=products_dir)
    example_file = data_dir / "example_offers.csv"
    if not example_file.exists():
        example_file.write_text(
            "slot,nome,preco_de,preco_por,imagem,unidade,cada\n"
            "1,Leite Integral,9.90,7.99,leite.png,UN,cada\n"
            "2,Arroz Tipo 1,12.50,10.99,arroz.png,KG,\n",
            encoding="utf-8",
        )

    rows, metadata = loader.load_file(example_file)
    validation = Validator.validate_offers(rows, products_dir=products_dir)
    templates = TemplateManager(templates_dir).list_templates()
    if not templates and default_template is not None:
        templates = [TemplateManager(default_template.parent).list_templates()[0]]

    print(f"Autoflyer ready. Found {len(rows)} offers.")
    print(f"Templates available: {len(templates)}")
    for template in templates[:5]:
        print(f"- {template.filename} -> {template.path}")
    print(f"Validation status: {'OK' if validation.is_valid else 'HAS ERRORS'}")
    print(f"Metadata: {metadata}")


def _native_slot_layout(tree: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    slots: List[Dict[str, Any]] = []
    if not tree:
        return slots

    def visit(node: Dict[str, Any]) -> None:
        name = str(node.get("name", "")).strip()
        match = re.search(r"^(?:GRUPO|GROUP|PRODUCT|PRODUTO)\s*[_-]?\s*(\d+)$", name, re.IGNORECASE)
        if match:
            slots.append({"slot": int(match.group(1)), "group_name": name})
        for child in node.get("children", []):
            if isinstance(child, dict):
                visit(child)

    visit(tree)
    return slots


@dataclass
class GenerationResult:
    template_path: Path
    data_path: Path
    items_loaded: int
    validation_ok: bool
    output_path: Optional[Path] = None
    warnings: List[str] | None = None
    errors: List[str] | None = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "template_path": str(self.template_path),
            "data_path": str(self.data_path),
            "items_loaded": self.items_loaded,
            "validation_ok": self.validation_ok,
            "output_path": str(self.output_path) if self.output_path else None,
            "warnings": self.warnings or [],
            "errors": self.errors or [],
        }


class GenerationWorkflow:
    def __init__(
        self,
        products_dir: str | Path,
        templates_dir: str | Path,
        outputs_dir: str | Path,
        image_search_dir: str | Path | None = None,
        export_format: str = "JPG",
        quality: int = 90,
    ):
        self.products_dir = Path(products_dir).resolve()
        self.templates_dir = Path(templates_dir).resolve()
        self.outputs_dir = Path(outputs_dir).resolve()
        self.image_search_dir = Path(image_search_dir).resolve() if image_search_dir else None
        self.export_format = str(export_format).upper()
        self.quality = int(quality)
        self.outputs_dir.mkdir(parents=True, exist_ok=True)

    def run(self, template_path: str | Path, data_path: str | Path) -> GenerationResult:
        template_path = Path(template_path).resolve()
        data_path = Path(data_path).resolve()

        if not template_path.exists():
            candidates = []
            for folder in [self.templates_dir, self.templates_dir.parent, self.templates_dir.parent / "arquivo.psd"]:
                if not folder.exists():
                    continue
                matches = sorted(p for p in folder.rglob("*") if p.is_file() and p.suffix.lower() in {".psd", ".psb"})
                candidates.extend(matches)
            if candidates:
                template_path = candidates[0]

        if not template_path.exists():
            raise FileNotFoundError(f"Template not found: {template_path}")

        loader = DataLoader(products_dir=self.products_dir, image_search_dir=self.image_search_dir)
        items, _ = loader.load_file(data_path)

        for item in items:
            if not item.imagem and item.nome:
                item.imagem = loader.ensure_placeholder_image(self.products_dir, item.nome, item.nome)

        ollama = AIOfferGenerator(load_settings())
        if ollama.is_available():
            logger.info("Ollama name optimization enabled (model=%s)", ollama.model)
            for item in items:
                item.nome = ollama.optimize_offer_name(item)
        else:
            logger.info("Ollama name optimization unavailable; original offer names retained")

        validation = Validator.validate_offers(items, products_dir=self.products_dir)

        if not validation.is_valid:
            raise ValueError("Planilha inválida: " + "; ".join(validation.errors[:5]))

        slot_layout: List[Dict[str, Any]] = []
        inspector_error: Optional[Exception] = None
        try:
            slot_layout = PsdTemplateInspector.inspect_template(template_path)
        except Exception as exc:
            inspector_error = exc
            logger.warning("psd-tools could not inspect template; native Photoshop inspection will be used: %s", exc)

        engine = PhotoshopEngine(visible=True, display_dialogs=False)
        engine.open_template(template_path)
        native_tree = engine.snapshot_native_layer_tree()
        if not slot_layout:
            slot_layout = _native_slot_layout(native_tree)
        if not slot_layout:
            detail = f" ({inspector_error})" if inspector_error else ""
            raise ValueError(f"O template PSD não possui grupos de oferta reconhecíveis: {template_path}{detail}")
        layer_tree_path = engine.export_native_layer_tree_json(
            self.outputs_dir / f"{template_path.stem}_camadas.json"
        )
        inspector = IntelligentInspector(engine)
        product_names = {int(item.slot): str(item.nome or "") for item in items if item.slot is not None}
        analysis = inspector.analyze_document(product_names_by_slot=product_names)
        ai_settings = load_settings().get("ai", {})
        ai = AIProvider(
            base_url=ai_settings.get("base_url", "http://localhost:11434"),
            model=ai_settings.get("model", "llama3.2"),
            timeout=ai_settings.get("timeout", 60),
            enabled=ai_settings.get("enabled", False),
        )
        ai_available = ai.is_available()
        logger.info("Ollama layout authority: %s (model=%s)", "enabled" if ai_available else "fallback", ai.model)
        engine.ai_provider = ai if ai_available else None
        if ai_available:
            for group in analysis.groups:
                group_data = asdict(group)
                if group.description is None or group.horizontal_distance_to_price is None:
                    classification = ai.classify_layers({"group_name": group.group_name, "layers": group_data})
                    self._apply_ai_classification(group, classification)
                    group_data = asdict(group)
                layout = ai.suggest_layout_adjustment(group_data)
                logger.info("Ollama recommendation for %s: %s", group.group_name, layout or "empty")
                self._apply_ai_layout_suggestion(group, layout, inspector)
        analysis_path = inspector.export_analysis_json(
            analysis,
            self.outputs_dir / f"{template_path.stem}_analise_inteligente.json",
        )
        engine.description_recommendations = {}
        engine.description_font_scales = {}
        engine.description_line_spacing_scales = {}
        for group in analysis.groups:
            match = re.search(r"(\d+)", group.group_name)
            if match and group.recommended_text:
                engine.description_recommendations[int(match.group(1))] = group.recommended_text
                engine.description_font_scales[int(match.group(1))] = max(
                    0.58, min(1.0, float(group.recommended_font_scale or 1.0))
                )
                engine.description_line_spacing_scales[int(match.group(1))] = max(
                    0.7, min(0.95, float(group.recommended_line_spacing_scale or 0.9))
                )

        update_warnings: List[str] = []
        for item in items:
            updated = False
            for attempt in range(8):
                if engine.update_offer_slot(item, slot_number=item.slot):
                    updated = True
                    break
                if engine.app is not None:
                    engine._wait_for_update(min(3.0 + attempt * 1.5, 12.0))
            if not updated:
                warning = f"Não foi possível atualizar o slot {item.slot} no PSD."
                update_warnings.append(warning)
                logger.warning(warning)

        output_ext = "png" if self.export_format == "PNG" else "jpg"
        output = self.outputs_dir / f"{template_path.stem}_gerado.{output_ext}"
        if self.export_format == "PNG":
            engine.export_png(output, quality=self.quality)
        else:
            engine.export_jpeg(output, quality=self.quality)

        return GenerationResult(
            template_path=template_path,
            data_path=data_path,
            items_loaded=len(items),
            validation_ok=True,
            output_path=output,
            warnings=validation.warnings + update_warnings + [
                f"PSD template recognized with {len(slot_layout)} product slots; {len(items)} offers mapped; export format: {self.export_format}."
                + (f" Native layer tree exported to {layer_tree_path.name}." if layer_tree_path else "")
                + f" Intelligent analysis exported to {analysis_path.name}."
            ],
            errors=validation.errors,
        )

    @staticmethod
    def _apply_ai_classification(group: Any, classification: dict[str, str]) -> None:
        if not classification:
            return
        def layers_in(layer: Any) -> list[Any]:
            result = [layer]
            for child in getattr(layer, "children", []) or []:
                result.extend(layers_in(child))
            return result

        layers = []
        candidates = []
        if getattr(group, "description", None):
            candidates.append(group.description)
        candidates.extend(getattr(group, "shapes", []))
        for child in candidates:
            if child:
                layers.extend(layers_in(child))
        for layer in layers:
            role = classification.get(layer.name)
            if role == "description" and group.description is None:
                group.description = layer

    @staticmethod
    def _apply_ai_layout_suggestion(group: Any, suggestion: dict[str, Any], inspector: IntelligentInspector) -> None:
        if not suggestion:
            return
        from .product_abbreviator import quebrar_linhas_inteligente
        # Se o Ollama enviou texto formatado com quebras inteligentes, adote-o!
        formatted = suggestion.get("formatted_text")
        if formatted and str(formatted).strip():
            clean = (
                str(formatted)
                .strip()
                .replace("\\r\\n", "\r")
                .replace("\\r", "\r")
                .replace("\\n", "\r")
                .replace("\r\n", "\r")
                .replace("\n", "\r")
            )
            group.recommended_text = clean
            group.needs_line_break = "\r" in group.recommended_text
        elif suggestion.get("needs_line_break"):
            group.needs_line_break = True
            if "\r" not in (group.recommended_text or ""):
                group.recommended_text = quebrar_linhas_inteligente(group.recommended_text or "")

        try:
            scale = float(suggestion.get("font_scale", 1.0))
        except (TypeError, ValueError):
            scale = 1.0
        group.recommended_font_scale = max(0.60, min(1.0, scale))

        try:
            line_spacing = float(suggestion.get("line_spacing_scale", 0.88))
        except (TypeError, ValueError):
            line_spacing = 0.88
        group.recommended_line_spacing_scale = max(0.70, min(0.95, line_spacing))

        if group.description and group.description.font_size:
            group.recommended_font_size = round(group.description.font_size * group.recommended_font_scale, 1)
