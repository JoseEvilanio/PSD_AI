from __future__ import annotations

import logging
from typing import Any

import requests

from .data_loader import OfferItem
from .product_abbreviator import abreviar_produto

logger = logging.getLogger("autoflyer")


class AIOfferGenerator:
    """Optimizes offer names through local Ollama without changing offer data."""

    def __init__(self, config: dict[str, Any]) -> None:
        settings = config.get("ollama", {})
        self.enabled = bool(settings.get("enabled", False))
        self.host = str(settings.get("host", "http://localhost:11434")).rstrip("/")
        self.model = str(settings.get("model", "llama3.2"))
        self.temperature = float(settings.get("temperature", 0.3))
        self.timeout = int(settings.get("timeout", 60))
        self._available: bool | None = None

    def is_available(self) -> bool:
        if not self.enabled:
            return False
        if self._available is not None:
            return self._available
        try:
            response = requests.get(f"{self.host}/api/tags", timeout=5)
            response.raise_for_status()
            models = [str(item.get("name", "")) for item in response.json().get("models", [])]
            self._available = any(name == self.model or name.startswith(f"{self.model}:") for name in models)
        except (OSError, ValueError, requests.RequestException) as exc:
            logger.info("Ollama indisponível para otimização de nomes: %s", exc)
            self._available = False
        return self._available

    def optimize_offer_name(self, item: OfferItem) -> str:
        original = str(item.nome or "").strip()
        if not original or not self.is_available():
            return original

        # Nomes de até 38 caracteres não precisam de encurtamento preliminar
        if len(original) <= 38:
            return original

        system = (
            "Você é redator de encartes de supermercado. Retorne o nome do produto ajustado para caber no encarte. "
            "REGRA OBRIGATÓRIA: NUNCA remova a marca (ex: ABOVE, OMO, CAMIL, SOYA, MOÇA, MOCA) nem o peso/volume (ex: 150ML, 1.6KG, 5KG, 900ML, 395G). "
            "Se o nome for longo, abrevie termos comuns (ex: DESODORANTE -> DESOD., REFRIGERANTE -> REFRIG., CONDENSADO -> COND.). "
            "Não inclua preço, moeda (R$), palavras como 'oferta', aspas ou explicações."
        )
        prompt = f"Nome original: {original}\nRetorne o nome padronizado com marca e volume:"
        try:
            response = requests.post(
                f"{self.host}/api/generate",
                json={
                    "model": self.model,
                    "prompt": prompt,
                    "system": system,
                    "stream": False,
                    "options": {"temperature": self.temperature, "num_predict": 80},
                },
                timeout=self.timeout,
            )
            response.raise_for_status()
            candidate = str(response.json().get("response", "")).strip().replace("\r", " ").replace("\n", " ")
            candidate = " ".join(candidate.split()).strip(" \"'")
            if self._is_valid_candidate(candidate, original):
                logger.info("Slot %s: nome otimizado por Ollama: '%s' -> '%s'", item.slot, original, candidate)
                return candidate
            logger.warning("Slot %s: resposta do Ollama rejeitada; aplicando abreviação inteligente de encarte.", item.slot)
            return abreviar_produto(original, limite_caracteres=34)
        except (OSError, ValueError, KeyError, requests.RequestException) as exc:
            logger.warning("Erro no Ollama ao otimizar slot %s (%s); aplicando abreviação inteligente.", item.slot, exc)
            return abreviar_produto(original, limite_caracteres=34)
        return original

    @staticmethod
    def _is_valid_candidate(candidate: str, original: str) -> bool:
        if not candidate or len(candidate) > 42 or len(candidate) < 2:
            return False
        if any(token in candidate.upper() for token in ("R$", "RS ", "OFERTA", "SLOGAN", "PREÇO", "PRECO")):
            return False
        original_words = {word.upper() for word in original.split() if len(word) >= 3}
        candidate_words = {word.upper() for word in candidate.split()}
        return bool(original_words & candidate_words)
