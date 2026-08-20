from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class TemplateInfo:
    def __init__(self, file_path: str | Path):
        self.path = Path(file_path).resolve()
        self.name = self.path.stem
        self.filename = self.path.name
        self.size_mb = round(self.path.stat().st_size / (1024 * 1024), 2)

    def to_dict(self) -> Dict[str, object]:
        return {
            "name": self.name,
            "filename": self.filename,
            "path": str(self.path),
            "size_mb": self.size_mb,
        }


class TemplateManager:
    def __init__(self, templates_dir: str | Path):
        self.templates_dir = Path(templates_dir).resolve()
        if not self.templates_dir.exists():
            project_root = self.templates_dir.parent
            alt_dir = project_root / "arquivo.psd"
            if alt_dir.exists():
                self.templates_dir = alt_dir
        self.templates_dir.mkdir(parents=True, exist_ok=True)

    def _iter_template_files(self) -> List[Path]:
        if not self.templates_dir.exists():
            return []

        files: List[Path] = []
        for candidate in sorted(self.templates_dir.rglob("*")):
            if candidate.is_file() and candidate.suffix.lower() in {".psd", ".psb"}:
                files.append(candidate)
        return files

    def list_templates(self) -> List[TemplateInfo]:
        templates: List[TemplateInfo] = []
        for file in self._iter_template_files():
            templates.append(TemplateInfo(file))
        return templates

    def get_template_by_name(self, template_name: str) -> Optional[TemplateInfo]:
        name = template_name.strip().lower()
        for template in self.list_templates():
            if (
                template.name.lower() == name
                or template.filename.lower() == name
                or template.path.stem.lower() == name
                or name in template.path.as_posix().lower()
            ):
                return template
        return None

    @classmethod
    def find_default_template(cls, root_dir: str | Path) -> Optional[Path]:
        base = Path(root_dir).resolve()
        candidates = [base, base / "arquivo.psd", base / "data" / "templates"]
        for folder in candidates:
            if folder.exists() and folder.is_dir():
                matches = [p for p in sorted(folder.rglob("*")) if p.is_file() and p.suffix.lower() in {".psd", ".psb"}]
                if matches:
                    return matches[0]
        return None
