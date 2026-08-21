from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from .data_loader import DataLoader
from .photoshop_engine import PhotoshopEngine
from .psd_template_inspector import PsdTemplateInspector
from .validator import Validator

logger = logging.getLogger(__name__)


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

        validation = Validator.validate_offers(items, products_dir=self.products_dir)

        if not validation.is_valid:
            raise ValueError("Planilha inválida: " + "; ".join(validation.errors[:5]))

        slot_layout = PsdTemplateInspector.inspect_template(template_path)
        if not slot_layout:
            raise ValueError(f"O template PSD não possui grupos de oferta reconhecíveis: {template_path}")

        engine = PhotoshopEngine(visible=True, display_dialogs=False)
        engine.open_template(template_path)

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
            warnings=validation.warnings + update_warnings + [f"PSD template recognized with {len(slot_layout)} product slots; {len(items)} offers mapped; export format: {self.export_format}."],
            errors=validation.errors,
        )
