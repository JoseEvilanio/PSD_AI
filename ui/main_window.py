from __future__ import annotations

import logging
import threading
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Optional

import tkinter as tk

from core.data_loader import DataLoader
from core.template_manager import TemplateManager
from core.validator import Validator
from core.workflow import GenerationWorkflow
from ui.loading_overlay import PhotoshopLoadingOverlay

logger = logging.getLogger(__name__)


class MainWindow(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Autoflyer")
        self.geometry("820x500")
        self.minsize(700, 420)

        self.loading_overlay = PhotoshopLoadingOverlay(self, tema_escuro=True)

        self.base_dir = Path(__file__).resolve().parent.parent
        self.templates_dir = self.base_dir / "data" / "templates"
        self.products_dir = self.base_dir / "data" / "products"
        self.inputs_dir = self.base_dir / "data" / "inputs"
        self.template_path: Optional[Path] = None
        self.data_path: Optional[Path] = None
        self.image_search_dir: Optional[Path] = None

        self._build_ui()
        self._ensure_directories()

        default_template = self._detect_default_template()
        if default_template is not None:
            self.template_path = default_template
            self.template_var.set(str(default_template))
            self.status_var.set(f"Template padrão carregado: {default_template.name}")

        default_image_dir = Path(r"F:\PRODUTO")
        if default_image_dir.is_dir():
            self.image_search_dir = default_image_dir
            self.image_dir_var.set(str(default_image_dir))

    def _detect_default_template(self) -> Optional[Path]:
        candidate_dirs = [self.base_dir / "arquivo.psd", self.base_dir / "data" / "templates", self.base_dir]
        for folder in candidate_dirs:
            if folder.exists() and folder.is_dir():
                matches = [p for p in sorted(folder.rglob("*")) if p.is_file() and p.suffix.lower() in {".psd", ".psb"}]
                if matches:
                    return matches[0]
        return None

    def _ensure_directories(self) -> None:
        for folder in [self.templates_dir, self.products_dir, self.inputs_dir, self.base_dir / "logs"]:
            folder.mkdir(parents=True, exist_ok=True)

    def _build_ui(self) -> None:
        pad = 12
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        title = tk.Label(self, text="Autoflyer — Automação de encartes", font=("Arial", 16, "bold"))
        title.grid(row=0, column=0, sticky="w", padx=pad, pady=(pad, 6))

        frame = ttk.Frame(self, padding=pad)
        frame.grid(row=1, column=0, sticky="nsew")
        frame.columnconfigure(1, weight=1)

        ttk.Label(frame, text="Template PSD:").grid(row=0, column=0, sticky="w", pady=4)
        self.template_var = tk.StringVar()
        self.template_entry = ttk.Entry(frame, textvariable=self.template_var)
        self.template_entry.grid(row=0, column=1, sticky="ew", padx=(8, 6))
        ttk.Button(frame, text="Procurar", command=self.choose_template).grid(row=0, column=2, sticky="e")

        ttk.Label(frame, text="Planilha (.xlsx/.csv):").grid(row=1, column=0, sticky="w", pady=4)
        self.data_var = tk.StringVar()
        self.data_entry = ttk.Entry(frame, textvariable=self.data_var)
        self.data_entry.grid(row=1, column=1, sticky="ew", padx=(8, 6))
        ttk.Button(frame, text="Procurar", command=self.choose_data).grid(row=1, column=2, sticky="e")

        ttk.Label(frame, text="Pasta de imagens:").grid(row=2, column=0, sticky="w", pady=4)
        self.image_dir_var = tk.StringVar()
        self.image_dir_entry = ttk.Entry(frame, textvariable=self.image_dir_var)
        self.image_dir_entry.grid(row=2, column=1, sticky="ew", padx=(8, 6))
        ttk.Button(frame, text="Procurar", command=self.choose_image_dir).grid(row=2, column=2, sticky="e")

        self.status_var = tk.StringVar(value="Pronto para processar.")
        ttk.Label(frame, textvariable=self.status_var, foreground="#1a4d8f").grid(row=3, column=0, columnspan=3, sticky="w", pady=(12, 0))

        actions = ttk.Frame(frame)
        actions.grid(row=4, column=0, columnspan=3, sticky="ew", pady=(18, 0))
        actions.columnconfigure(0, weight=1)
        actions.columnconfigure(1, weight=1)

        ttk.Button(actions, text="Validar dados", command=self.validate_data).grid(row=0, column=0, sticky="ew", padx=(0, 6))
        ttk.Button(actions, text="Gerar arte", command=self.generate_art).grid(row=0, column=1, sticky="ew", padx=(6, 0))

    def choose_template(self) -> None:
        path = filedialog.askopenfilename(
            title="Selecione o template PSD",
            filetypes=[("PSD", "*.psd"), ("PSD Big", "*.psb"), ("Todos", "*.*")],
        )
        if not path:
            return
        self.template_path = Path(path)
        self.template_var.set(str(self.template_path))
        self.status_var.set(f"Template selecionado: {self.template_path.name}")

    def choose_data(self) -> None:
        path = filedialog.askopenfilename(
            title="Selecione a planilha ou CSV",
            filetypes=[("Excel", "*.xlsx *.xls"), ("CSV", "*.csv"), ("Todos", "*.*")],
        )
        if not path:
            return
        self.data_path = Path(path)
        self.data_var.set(str(self.data_path))
        self.status_var.set(f"Planilha selecionada: {self.data_path.name}")

    def choose_image_dir(self) -> None:
        path = filedialog.askdirectory(title="Selecione a pasta das imagens dos produtos")
        if not path:
            return
        self.image_search_dir = Path(path).resolve()
        self.image_dir_var.set(str(self.image_search_dir))
        self.status_var.set(f"Pasta de imagens selecionada: {self.image_search_dir}")

    def validate_data(self) -> None:
        if self.data_path is None:
            messagebox.showwarning("Dados faltantes", "Selecione uma planilha antes de validar.")
            return

        try:
            loader = DataLoader(products_dir=self.products_dir, image_search_dir=self.image_search_dir)
            rows, _ = loader.load_file(self.data_path)
            result = Validator.validate_offers(rows, products_dir=self.products_dir)
            if result.is_valid:
                self.status_var.set(f"Validação OK: {len(rows)} ofertas carregadas.")
                messagebox.showinfo("Sucesso", f"Planilha válida. {len(rows)} ofertas carregadas.")
            else:
                self.status_var.set(f"Validação com {len(result.errors)} erros e {len(result.warnings)} avisos.")
                messagebox.showwarning("Validação com avisos", "\n".join(result.errors[:3] or result.warnings[:3]))
        except Exception as exc:  # pragma: no cover - UI feedback only
            logger.exception("Erro ao validar planilha")
            messagebox.showerror("Erro", str(exc))
            self.status_var.set("Erro ao validar dados.")

    def generate_art(self) -> None:
        if self.template_path is None or self.data_path is None:
            messagebox.showwarning("Dados incompletos", "Selecione o template e a planilha antes de gerar.")
            return

        # 1. Abre a animação de loading na tela
        self.loading_overlay.iniciar("Conectando ao Photoshop e preparando dados...")
        self.status_var.set("Gerando arte...")

        def task() -> None:
            try:
                if self.image_search_dir is None or not self.image_search_dir.is_dir():
                    raise ValueError("Selecione uma pasta válida de imagens antes de gerar a arte.")

                workflow = GenerationWorkflow(
                    products_dir=self.products_dir,
                    templates_dir=self.base_dir / "arquivo.psd",
                    outputs_dir=self.base_dir / "data" / "outputs",
                    image_search_dir=self.image_search_dir,
                )
                result = workflow.run(self.template_path, self.data_path)
                output = result.output_path or (self.base_dir / "data" / "outputs" / (self.template_path.stem + "_gerado.jpg"))

                self.status_var.set(f"Arte gerada com sucesso: {output.name}")
                self.after(0, lambda: messagebox.showinfo("Sucesso", f"Arte exportada em:\n{output}"))
            except Exception as exc:  # pragma: no cover - UI feedback only
                logger.exception("Erro ao gerar arte")
                self.status_var.set("Erro ao gerar arte.")
                self.after(0, lambda e=exc: messagebox.showerror("Erro", str(e)))
            finally:
                # 4. Fecha a animação automaticamente ao finalizar (com sucesso ou erro)
                self.after(0, self.loading_overlay.fechar)

        # 2. Executa em Thread separada para manter a animação fluida
        threading.Thread(target=task, daemon=True).start()
