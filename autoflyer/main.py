from __future__ import annotations

import logging
import os
from pathlib import Path

import yaml

from core.data_loader import DataLoader
from core.template_manager import TemplateManager
from core.validator import Validator

BASE_DIR = Path(__file__).resolve().parent
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
        return yaml.safe_load(fh) or {}


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


def main() -> None:
    configure_logging()
    logger = logging.getLogger("autoflyer")
    logger.info("Starting Autoflyer")

    try:
        import tkinter as tk
        from ui.main_window import MainWindow

        root = MainWindow()
        root.mainloop()
    except Exception as exc:  # pragma: no cover - fallback for headless environments
        logger.warning("GUI unavailable, falling back to console mode: %s", exc)
        console_smoke_test()


if __name__ == "__main__":
    main()
