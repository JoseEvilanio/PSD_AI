from __future__ import annotations

import json
import logging
from typing import Any, Optional

import requests

logger = logging.getLogger(__name__)


class AIProvider:
    """Optional local Ollama provider used to enrich template analysis."""

    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        model: str = "llama3.2",
        timeout: int = 60,
        enabled: bool = True,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = int(timeout)
        self.enabled = bool(enabled)
        self._available: Optional[bool] = None

    def is_available(self) -> bool:
        if not self.enabled:
            return False
        if self._available is not None:
            return self._available
        try:
            response = requests.get(f"{self.base_url}/api/tags", timeout=5)
            if response.status_code != 200:
                self._available = False
                return False
            models = [str(item.get("name", "")) for item in response.json().get("models", [])]
            self._available = any(name == self.model or name.startswith(f"{self.model}:") for name in models)
        except (OSError, ValueError, requests.RequestException) as exc:
            logger.info("Ollama indisponível: %s", exc)
            self._available = False
        return self._available

    def classify_layers(self, group_summary: dict[str, Any]) -> dict[str, str]:
        if not self.is_available():
            return {}
        prompt = self._build_classification_prompt(group_summary)
        try:
            return self._parse_json_response(self._chat(prompt))
        except (OSError, ValueError, KeyError, requests.RequestException) as exc:
            logger.warning("Falha na classificação via Ollama: %s", exc)
            return {}

    def suggest_layout_adjustment(self, group_analysis: dict[str, Any]) -> dict[str, Any]:
        if not self.is_available():
            return {}
        prompt = self._build_layout_prompt(group_analysis)
        try:
            parsed = self._parse_json_response(self._chat(prompt))
            if parsed:
                if "formatted_text" in parsed and parsed["formatted_text"]:
                    parsed["formatted_text"] = self._clean_formatted_text(parsed["formatted_text"])
                return parsed
        except (OSError, ValueError, KeyError, requests.RequestException) as exc:
            logger.warning("Falha na sugestão de layout via Ollama: %s", exc)
        return {}

    @staticmethod
    def _clean_formatted_text(val: Any) -> str:
        if not val:
            return ""
        lines = [p.strip() for p in str(val).replace("\r\n", "\r").replace("\n", "\r").split("\r") if p.strip()]
        return "\r".join(lines)

    def resolve_collision(
        self,
        offer_name: str,
        available_width: float,
        available_height: float,
        current_font_size: float,
        collision_reason: str = "",
    ) -> dict[str, Any]:
        """Resolve uma colisão de texto detectada no Photoshop sugerindo quebras e escalas via Ollama."""
        if not self.is_available():
            return {}
        prompt = (
            "Você é um especialista em tipografia e design de encartes de supermercado no Photoshop.\n"
            "Foi detectada uma colisão no texto da descrição do produto com outro elemento (como preço ou borda).\n"
            "Sua tarefa é ajustar o texto para caber perfeitamente no espaço disponível sem colisões.\n\n"
            f"Nome do produto: \"{offer_name}\"\n"
            f"Largura disponível na caixa: {available_width:.0f}px\n"
            f"Altura disponível na caixa: {available_height:.0f}px\n"
            f"Tamanho de fonte atual: {current_font_size:.1f}pt\n"
            f"Detalhe da colisão: {collision_reason}\n\n"
            "Responda SOMENTE um objeto JSON com:\n"
            "{\n"
            "  \"formatted_text\": \"Texto com quebras de linha usando \\r entre linhas (máximo 2 ou 3 linhas, equilibradas esteticamente)\",\n"
            "  \"font_scale\": número entre 0.65 e 1.0 (ex: 0.85),\n"
            "  \"line_spacing_scale\": número entre 0.75 e 0.95 (ex: 0.85),\n"
            "  \"compact_text\": \"Se o texto for longo demais mesmo com quebras, versão levemente abreviada mantendo marca, tipo e peso/volume\",\n"
            "  \"reason\": \"Breve motivo do ajuste\"\n"
            "}"
        )
        try:
            parsed = self._parse_json_response(self._chat(prompt))
            if parsed:
                if "formatted_text" in parsed and parsed["formatted_text"]:
                    parsed["formatted_text"] = self._clean_formatted_text(parsed["formatted_text"])
                if "compact_text" in parsed and parsed["compact_text"]:
                    parsed["compact_text"] = self._clean_formatted_text(parsed["compact_text"])
            return parsed
        except (OSError, ValueError, KeyError, requests.RequestException) as exc:
            logger.warning("Falha ao resolver colisão via Ollama: %s", exc)
            return {}

    def diagnose_error(self, error_message: str, context: Optional[dict[str, Any]] = None) -> str:
        if not self.is_available():
            return error_message
        prompt = (
            "Explique em português, de forma direta, este erro de automação do Photoshop "
            "e indique a causa mais provável.\n\n"
            f"Erro: {error_message}\nContexto:\n{json.dumps(context or {}, ensure_ascii=False, indent=2)}"
        )
        try:
            return self._chat(prompt)
        except (OSError, ValueError, KeyError, requests.RequestException):
            return error_message

    def _chat(self, prompt: str, system: Optional[str] = None) -> str:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        response = requests.post(
            f"{self.base_url}/api/chat",
            json={
                "model": self.model,
                "messages": messages,
                "stream": False,
                "format": "json",
                "options": {"temperature": 0.2, "num_predict": 800},
            },
            timeout=self.timeout,
        )
        response.raise_for_status()
        return str(response.json()["message"]["content"]).strip()

    @staticmethod
    def _parse_json_response(text: str) -> dict[str, Any]:
        value = str(text or "").strip()
        if "```" in value:
            parts = value.split("```")
            value = parts[1].removeprefix("json").strip() if len(parts) > 1 else value
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            start, end = value.find("{"), value.rfind("}") + 1
            if start >= 0 and end > start:
                try:
                    parsed = json.loads(value[start:end])
                    return parsed if isinstance(parsed, dict) else {}
                except json.JSONDecodeError:
                    pass
            logger.warning("Resposta do Ollama não contém JSON válido: %s", value[:200])
            return {}

    @staticmethod
    def _build_classification_prompt(group_summary: dict[str, Any]) -> str:
        return (
            "Classifique cada camada deste grupo de encarte. Responda somente JSON, usando um papel por camada: "
            "description, price_integer, price_decimal, price_de, unit, currency, image, shape ou other.\n\n"
            f"Grupo:\n{json.dumps(group_summary, ensure_ascii=False, indent=2)}"
        )

    @staticmethod
    def _build_layout_prompt(group_analysis: dict[str, Any]) -> str:
        desc_info = group_analysis.get("description") or {}
        text = group_analysis.get("recommended_text") or (desc_info.get("text") if isinstance(desc_info, dict) else "")
        font_size = desc_info.get("font_size") if isinstance(desc_info, dict) else 36.0
        dist = group_analysis.get("horizontal_distance_to_price")
        collisions = group_analysis.get("surrounding_collisions", [])
        avail_w = group_analysis.get("available_width", 160.0)
        avail_h = group_analysis.get("available_height", 80.0)

        return (
            "Você é um especialista em tipografia e design de encartes de supermercado no Photoshop.\n"
            "Analise este grupo de oferta e defina a melhor quebra de linha e escala para a descrição do produto "
            "evitar qualquer colisão com os preços e outros elementos do encarte.\n\n"
            f"Nome do produto: \"{text}\"\n"
            f"Tamanho da fonte base: {font_size}pt\n"
            f"Largura disponível estimada para texto: {avail_w:.0f}px\n"
            f"Altura disponível estimada para texto: {avail_h:.0f}px\n"
            f"Distância horizontal até o preço: {dist}px\n"
            f"Colisões próximas: {', '.join(collisions) if collisions else 'nenhuma'}\n\n"
            "Diretrizes:\n"
            "- Se o texto for longo (mais de 18 caracteres ou 2 palavras) ou estiver próximo do preço (< 15px), divida em 2 ou 3 linhas bem equilibradas.\n"
            "- Mantenha a separação gramatical e estética correta (ex: quebrar antes da marca ou antes do peso/volume).\n"
            "- Defina font_scale entre 0.65 e 1.0 para que caiba na largura sem colidir.\n"
            "- Use \\r para representar quebras de linha em formatted_text.\n\n"
            "Responda SOMENTE JSON no formato:\n"
            "{\n"
            "  \"needs_line_break\": true,\n"
            "  \"formatted_text\": \"LINHA 1\\rLINHA 2\",\n"
            "  \"font_scale\": 0.85,\n"
            "  \"line_spacing_scale\": 0.85,\n"
            "  \"compact_text\": \"Versão compactada se necessário\",\n"
            "  \"reason\": \"Motivo da formatação sugerida\"\n"
            "}"
        )
