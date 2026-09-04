from __future__ import annotations

import logging
from typing import Any

try:
    import ollama
except ImportError:
    ollama = None

from .data_loader import OfferItem

logger = logging.getLogger("autoflyer")


# Prompts especializados por departamento
PROMPTS_DEPARTAMENTO = {
    "acougue": (
        "Você é um redator profissional especializado em cartazes de açougue de supermercado. "
        "Sua tarefa é tornar o nome de um produto de carne altamente apetitoso e nobre. "
        "Use adjetivos comerciais de alta conversão como 'Fresco', 'Macio', 'Selecionado', 'Corte Nobre' ou 'Especial para Churrasco'. "
        "Retorne apenas o nome do produto reescrito. Limite estrito de 32 caracteres. "
        "Nunca mude ou invente unidades de medida ou marcas."
    ),
    "hortifruti": (
        "Você é um especialista em comunicação para feiras e hortifrúti de varejo. "
        "Escreva chamadas que destaquem o frescor do campo, colheita do dia ou seleção manual. "
        "Use termos como 'Fresco', 'Selecionado', 'Direto do Produtor', 'Doce' ou 'Higienizado'. "
        "Retorne exclusivamente o nome do produto otimizado. Limite máximo de 32 caracteres. "
        "Preserve a pesagem original."
    ),
    "bebidas": (
        "Você é um especialista em vendas para o setor de bebidas frias e adega. "
        "Crie títulos focados na temperatura ideal de consumo e ocasiões especiais. "
        "Use gatilhos como 'Gelada', 'Trincando', 'Puro Malte', 'Refrescante' ou 'Reserva'. "
        "Retorne apenas a resposta limpa, sem pontuações ou aspas. Máximo de 32 caracteres."
    ),
    "limpeza": (
        "Você é um redator focado em produtos de higiene e cuidados com o lar. "
        "Suas descrições devem ressaltar a eficiência, proteção, perfume marcante ou rendimento do produto. "
        "Use palavras como 'Rendimento', 'Poder Ativo', 'Fragrância' ou 'Proteção'. "
        "Retorne somente o nome do produto. Limite de 32 caracteres."
    ),
    "padrao": (
        "Você é um redator de alta conversão para produtos de mercearia de supermercado. "
        "Crie chamadas tradicionais que valorizem a qualidade alimentícia da marca. "
        "Use termos como 'Tradicional', 'Premium', 'Saboroso' ou 'Familiar'. "
        "Retorne estritamente o título limpo em até 32 caracteres."
    ),
}


class AIOfferGenerator:
    def __init__(self, config: dict[str, Any]):
        self.ollama_config = config.get("ollama", {})
        self.enabled = bool(self.ollama_config.get("enabled", False))
        self.host = str(self.ollama_config.get("host", "http://localhost:11434"))
        self.model = str(self.ollama_config.get("model", "llama3.2"))
        self.temperature = float(self.ollama_config.get("temperature", 0.2))
        self.client = None

        if self.enabled:
            if ollama is None:
                logger.warning("Biblioteca 'ollama' não instalada. Desabilitando módulo de IA.")
                self.enabled = False
            else:
                try:
                    # Inicializa o cliente do Ollama apontando para o host configurado
                    self.client = ollama.Client(host=self.host)
                    logger.info(f"Ollama configurado no host {self.host} usando modelo '{self.model}'.")
                except Exception as e:
                    logger.error(f"Erro ao conectar com o serviço Ollama: {e}")
                    self.enabled = False

    def is_available(self) -> bool:
        return self.enabled and self.client is not None

    @staticmethod
    def detectar_departamento(texto: str) -> str:
        """Detecta o departamento do produto com base em palavras-chave."""
        t = texto.lower()
        if any(w in t for w in ("carne", "bovin", "frango", "suin", "peixe", "alcatra", "picanha", "costela", "linguica", "contrafile", "patinho", "acem", "maminha", "cupim", "file", "tilapia", "salmao")):
            return "acougue"
        if any(w in t for w in ("banana", "maca", "laranja", "limao", "tomate", "batata", "cebola", "alface", "cenoura", "melancia", "melao", "uva", "manga", "mamao", "abacaxi", "alho", "feira", "verdura", "fruta")):
            return "hortifruti"
        if any(w in t for w in ("cerveja", "vinho", "refrigerante", "suco", "vodka", "whisky", "gin", "energetico", "agua", "cha", "espumante", "chopp", "latao")):
            return "bebidas"
        if any(w in t for w in ("sabao", "omo", "amaciante", "detergente", "desinfetante", "agua sanitaria", "papel higienico", "shampoo", "condicionador", "sabonete", "desodorante", "creme dental", "pasta de dente", "fralda", "above", "pinho")):
            return "limpeza"
        return "padrao"

    def otimizar_nome_produto(self, item: OfferItem) -> str:
        if not self.enabled or self.client is None:
            return item.nome

        # Prompt ultra-estrito focado apenas em correção gramatical e ortográfica
        system_prompt = (
            "Você é um corretor ortográfico e gramatical de língua portuguesa extremamente rigoroso.\n"
            "Sua ÚNICA tarefa é corrigir erros de português, digitação, acentuação ou ortografia do texto enviado.\n"
            "REGRAS ABSOLUTAS:\n"
            "1. Retorne APENAS o texto corrigido, sem aspas, explicações, introduções ou comentários.\n"
            "2. NUNCA adicione palavras novas, adjetivos, marcas ou slogans que não estejam no texto original.\n"
            "3. NUNCA responda com textos conversacionais (ex: 'Aqui estão', 'Segue a correção', 'Opção corrigida').\n"
            "4. Se o texto original já estiver correto, retorne exatamente o mesmo texto recebido, caractere por caractere.\n"
            "Exemplo de entrada: 'Arros tpo 1 Camil'\n"
            "Exemplo de saída: 'Arroz Tipo 1 Camil'"
        )

        try:
            response = self.client.generate(
                model=self.model,
                prompt=f"Corrija apenas se houver erros de português: {item.nome}",
                system=system_prompt,
                options={"temperature": 0.0},  # Temperatura ZERO garante que o modelo não invente nada
            )

            texto_corrigido = (
                response.get("response", "").strip()
                if isinstance(response, dict)
                else getattr(response, "response", "").strip()
            )
            texto_corrigido = texto_corrigido.strip("\"' \r\n")

            # Se a IA alucinar e tentar retornar um texto longo de conversa, bloqueamos e usamos o original
            if texto_corrigido and len(texto_corrigido) <= len(item.nome) * 1.3:
                lower_c = texto_corrigido.lower()
                if not any(
                    lower_c.startswith(pref)
                    for pref in ("aqui ", "opç", "sugest", "claro", "segue", "para o", "título", "nome:")
                ):
                    logger.info(f"[IA] Slot {item.slot}: Corrigido '{item.nome}' -> '{texto_corrigido}'")
                    return texto_corrigido

        except Exception as e:
            logger.error(f"[IA] Falha na correção do slot {item.slot}: {e}")

        return item.nome  # Fallback seguro: usa o texto original da planilha

    def optimize_offer_name(self, item: OfferItem) -> str:
        """Alias para manter compatibilidade."""
        return self.otimizar_nome_produto(item)
