from __future__ import annotations

import re
import unicodedata
import zlib
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import pandas as pd


def _normalize_token(text: str) -> str:
    if not text:
        return ""
    normalized = unicodedata.normalize("NFKD", str(text))
    without_accents = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    return re.sub(r"[^a-zA-Z0-9]+", "_", without_accents).strip("_").lower()


def _normalized_words(text: str) -> Set[str]:
    return {
        word for word in _normalize_token(text).split("_")
        if len(word) >= 2
    }


class OfferItem:
    def __init__(
        self,
        slot: int,
        nome: str,
        preco_de: Optional[float] = None,
        preco_por: Optional[float] = None,
        imagem: Optional[str] = None,
        unidade: Optional[str] = None,
        cada: Optional[str] = None,
        extra_fields: Optional[Dict[str, Any]] = None,
        provided_fields: Optional[Set[str]] = None,
    ) -> None:
        self.slot = int(slot)
        self.nome = str(nome).strip() if nome is not None and not pd.isna(nome) else ""
        self.preco_de = float(preco_de) if preco_de is not None and not pd.isna(preco_de) else None
        self.preco_por = float(preco_por) if preco_por is not None and not pd.isna(preco_por) else None
        self.imagem = str(imagem).strip() if imagem is not None and not pd.isna(imagem) else None
        self.unidade = str(unidade).strip() if unidade is not None and not pd.isna(unidade) else None
        self.cada = str(cada).strip() if cada is not None and not pd.isna(cada) else None
        self.extra_fields = extra_fields or {}
        self.provided_fields = provided_fields or set()

    def has_field(self, field_name: str) -> bool:
        return field_name in self.provided_fields

    @property
    def preco_por_inteiro(self) -> Optional[str]:
        if self.preco_por is None:
            return None
        return str(int(self.preco_por))

    @property
    def preco_por_decimal(self) -> Optional[str]:
        if self.preco_por is None:
            return None
        return f",{int(round((self.preco_por - int(self.preco_por)) * 100)):02d}"

    @property
    def preco_por_str(self) -> str:
        return "" if self.preco_por is None else f"R$ {self.preco_por:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

    @property
    def preco_de_str(self) -> str:
        return "" if self.preco_de is None else f"R$ {self.preco_de:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "slot": self.slot,
            "nome": self.nome,
            "preco_de": self.preco_de,
            "preco_por": self.preco_por,
            "imagem": self.imagem,
            "unidade": self.unidade,
            "cada": self.cada,
            "provided_fields": sorted(self.provided_fields),
            **self.extra_fields,
        }


class DataLoader:
    COLUMN_SYNONYMS = {
        "slot": ["slot", "posicao", "item", "ordem"],
        "nome": ["nome", "produto", "descricao", "titulo"],
        "preco_de": ["preco_de", "preco_original", "de", "precode"],
        "preco_por": ["preco_por", "por", "preco_promocional", "preco"],
        "imagem": ["imagem", "img", "foto", "image"],
        "unidade": ["unidade", "un", "medida"],
        "cada": ["cada"],
    }

    def __init__(self, products_dir: Optional[str | Path] = None, image_search_dir: Optional[str | Path] = None):
        self.products_dir = Path(products_dir).resolve() if products_dir else None
        self.image_search_dir = Path(image_search_dir).resolve() if image_search_dir else None

    def _match_column(self, col_name: str) -> Optional[str]:
        clean = col_name.strip().lower().replace(" ", "_").replace("-", "_")
        for standard_name, synonyms in self.COLUMN_SYNONYMS.items():
            if clean in synonyms:
                return standard_name
        return None

    def _clean_price(self, value: Any) -> Optional[float]:
        if value is None or pd.isna(value):
            return None
        if isinstance(value, (int, float)):
            return float(value)

        text = str(value).strip()
        if not text:
            return None

        negative = text.startswith("(") and text.endswith(")")
        if negative:
            text = text[1:-1]
        if text.startswith("-"):
            negative = True
            text = text[1:]

        text = text.replace("R$", "").replace("USD", "").replace("BRL", "").replace(" ", "")
        if not text:
            return None

        if "," in text and "." in text:
            if text.rfind(",") > text.rfind("."):
                text = text.replace(".", "").replace(",", ".")
            else:
                text = text.replace(",", "")
        elif "," in text:
            text = text.replace(",", ".")

        try:
            result = float(text)
            return -result if negative else result
        except ValueError:
            return None

    @staticmethod
    def _create_placeholder_png(width: int, height: int, out_path: Path) -> Path:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        raw = bytearray()
        for y in range(height):
            raw.append(0)
            for x in range(width):
                if x < 8 or y < 8 or x > width - 9 or y > height - 9:
                    color = (211, 211, 211, 255)
                elif (x + y) % 20 < 10:
                    color = (255, 244, 214, 255)
                else:
                    color = (248, 248, 248, 255)
                raw.extend(color)

        def chunk(tag: bytes, payload: bytes) -> bytes:
            return (
                struct.pack(">I", len(payload))
                + tag
                + payload
                + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF)
            )

        import struct

        png_bytes = b"\x89PNG\r\n\x1a\n"
        png_bytes += chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
        png_bytes += chunk(b"IDAT", zlib.compress(bytes(raw), 9))
        png_bytes += chunk(b"IEND", b"")
        out_path.write_bytes(png_bytes)
        return out_path

    @classmethod
    def ensure_placeholder_image(cls, products_dir: str | Path, product_name: str, requested_name: Optional[str] = None) -> str:
        root = Path(products_dir).resolve()
        root.mkdir(parents=True, exist_ok=True)

        base_name = str(requested_name or product_name or "produto").strip()
        if not base_name:
            base_name = "produto"
        safe_name = re.sub(r"[^a-zA-Z0-9_\-]+", "_", base_name).strip("_") or "produto"
        target = root / f"{safe_name}.png"
        if not target.exists():
            cls._create_placeholder_png(600, 600, target)
        return str(target)

    def _resolve_image_path(self, img_name: Optional[str], product_name: str = "", context_dir: Optional[Path] = None) -> Optional[str]:
        if not img_name and not product_name:
            return None

        candidates: List[Path] = []
        raw = str(img_name).strip() if img_name else ""
        search_roots = [
            root for root in [self.image_search_dir, self.products_dir]
            if root and root.exists()
        ]

        if raw:
            candidate_paths = [
                Path(raw),
                Path(raw.replace("\\", "/")),
            ]
            for p in candidate_paths:
                if p.is_absolute() and p.exists():
                    return str(p)

        if context_dir and raw:
            candidates.append(context_dir / raw)
            candidates.append(context_dir / Path(raw).name)

        if raw:
            for root in search_roots:
                candidates.append(root / raw)
                candidates.append(root / Path(raw).name)

        for p in candidates:
            if p.exists():
                return str(p)

        if product_name:
            product_words = _normalized_words(product_name)
            ranked: List[Tuple[int, int, Path]] = []
            for root in [*search_roots, context_dir]:
                if not root or not root.exists():
                    continue
                for file in root.rglob("*"):
                    if not file.is_file() or file.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp", ".bmp"}:
                        continue
                    filename_words = _normalized_words(file.stem)
                    path_words = filename_words | _normalized_words(file.parent.name)
                    overlap = product_words & path_words
                    exact_stem = _normalize_token(file.stem) == _normalize_token(product_name)
                    if exact_stem:
                        return str(file)
                    if overlap:
                        ranked.append((len(overlap), len(filename_words & product_words), file))

            if ranked:
                ranked.sort(key=lambda item: (item[0], item[1], -len(str(item[2]))), reverse=True)
                best_score, filename_score, best_file = ranked[0]
                # Require enough evidence to avoid assigning an unrelated image
                # merely because a generic token such as "aerosol" matched.
                if best_score >= 2 or filename_score >= 2:
                    return str(best_file)

        if self.products_dir:
            return self.ensure_placeholder_image(self.products_dir, product_name, raw or product_name)

        return raw

    def load_file(self, file_path: str | Path) -> Tuple[List[OfferItem], Dict[str, Any]]:
        path = Path(file_path).resolve()
        if not path.exists():
            raise FileNotFoundError(f"File not found: {path}")

        ext = path.suffix.lower()
        if ext == ".csv":
            df = pd.read_csv(path)
        elif ext in {".xlsx", ".xls"}:
            df = pd.read_excel(path)
        else:
            raise ValueError(f"Unsupported file type: {ext}")

        return self._parse_dataframe(df, context_dir=path.parent)

    def _parse_dataframe(self, df: pd.DataFrame, context_dir: Optional[Path] = None) -> Tuple[List[OfferItem], Dict[str, Any]]:
        df = df.dropna(how="all").copy()

        column_map = {}
        for col in df.columns:
            mapped = self._match_column(str(col))
            if mapped:
                column_map[col] = mapped
        renamed = df.rename(columns=column_map)

        items: List[OfferItem] = []
        for idx, row in renamed.iterrows():
            slot_value = row.get("slot")
            slot = int(float(slot_value)) if slot_value not in (None, "") and not pd.isna(slot_value) else idx + 1

            product_name = row.get("nome")
            if product_name is None or pd.isna(product_name) or str(product_name).strip() == "":
                continue

            provided_fields: Set[str] = {"nome"}
            raw_preco_de = row.get("preco_de")
            preco_de = self._clean_price(raw_preco_de)
            if preco_de is not None:
                provided_fields.add("preco_de")

            raw_preco_por = row.get("preco_por")
            preco_por = self._clean_price(raw_preco_por)
            if preco_por is not None:
                provided_fields.add("preco_por")

            raw_img = row.get("imagem")
            image_path = self._resolve_image_path(str(raw_img).strip() if raw_img is not None and not pd.isna(raw_img) else None, str(product_name), context_dir)
            if image_path:
                provided_fields.add("imagem")

            unidade = row.get("unidade")
            unidade_value = str(unidade).strip() if unidade is not None and not pd.isna(unidade) else None
            if unidade_value:
                provided_fields.add("unidade")

            cada_val = row.get("cada")
            cada_value = str(cada_val).strip() if cada_val is not None and not pd.isna(cada_val) else None
            if cada_value:
                provided_fields.add("cada")

            item = OfferItem(
                slot=slot,
                nome=str(product_name).strip(),
                preco_de=preco_de,
                preco_por=preco_por,
                imagem=image_path,
                unidade=unidade_value,
                cada=cada_value,
                provided_fields=provided_fields,
            )
            items.append(item)

        items.sort(key=lambda item: item.slot)
        return items, {"rows_loaded": len(items)}
