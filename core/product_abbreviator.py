import re
import unicodedata
from typing import Optional


def remover_acentos(texto: str) -> str:
    """Remove acentos e caracteres especiais para compatibilidade com fontes do Photoshop."""
    nfkd = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def abreviar_produto(
    nome_produto: str,
    limite_caracteres: int = 26,
    agressivo: bool = False,
) -> str:
    """Abrevia nomes de produtos de supermercado de forma legível para encartes.

    Estratégia:
    1. Normaliza o texto e remove acentos
    2. Protege quantidades e unidades (350ML, 1,5KG...)
    3. Aplica dicionário de abreviações de encarte
    4. Remove stopwords de baixo valor
    5. Se ainda passar do limite, encurta de forma inteligente mantendo marcas e unidades
    """
    if not nome_produto or not str(nome_produto).strip():
        return ""

    # -------------------------------------------------
    # 1. Normalização e remoção de acentos
    # -------------------------------------------------
    nome = remover_acentos(str(nome_produto).upper().strip())
    nome = re.sub(r"\s+", " ", nome)

    # -------------------------------------------------
    # 2. Dicionário de abreviações
    # -------------------------------------------------
    abreviacoes = {
        # Categorias
        "REFRIGERANTE": "REFRI",
        "DETERGENTE": "DET",
        "AMACIANTE": "AMAC",
        "CHOCOLATE": "CHOC",
        "BISCOITO": "BISC",
        "BOLACHA": "BOL",
        "SHAMPOO": "SHAMP",
        "CONDICIONADOR": "COND",
        "SABONETE": "SAB",
        "DESODORANTE": "DESOD",
        "CREME": "CREME",
        "PASTA": "PST",
        "MOLHO": "MOLHO",
        "AZEITE": "AZEITE",
        "ÓLEO": "ÓLEO",
        "OLEO": "ÓLEO",
        "LEITE": "LEITE",
        "IOGURTE": "IOG",
        "QUEIJO": "QUEIJO",
        "PRESUNTO": "PRES",
        "MORTADELA": "MORT",
        "HAMBÚRGUER": "HAMB",
        "HAMBURGUER": "HAMB",
        "SALSICHA": "SALS",
        "LINGUIÇA": "LING",
        "LINGUICA": "LING",
        "FEIJÃO": "FEIJAO",
        "FEIJAO": "FEIJAO",
        "ARROZ": "ARROZ",
        "AÇÚCAR": "AÇÚCAR",
        "ACUCAR": "AÇÚCAR",
        "FARINHA": "FAR",
        "MACARRÃO": "MACARRÃO",
        "MACARRAO": "MACARRÃO",
        "CAFÉ": "CAFE",
        "CAFE": "CAFE",
        "ACHÓCOLATADO": "ACHÓC",
        "ACHOCOLATADO": "ACHCOL",
        "CONDENSADO": "COND",

        # Qualidades / tipos
        "INTEGRAL": "INT",
        "TRADICIONAL": "TRAD",
        "PREMIUM": "PREM",
        "LIGHT": "LT",
        "ZERO": "ZERO",
        "DIET": "DIET",
        "NATURAL": "NAT",
        "ORGÂNICO": "ORG",
        "ORGANICO": "ORG",
        "CONCENTRADO": "CONC",
        "LÍQUIDO": "LIQ",
        "LIQUIDO": "LIQ",
        "EM PÓ": "PO",
        "EM PO": "PO",
        "PERFEITA": "PERF",
        "LAVAGEM": "LAV",
        "SACHÊ": "SACHE",
        "SACHE": "SACHE",
        "AEROSOL": "AEROS",

        # Embalagens
        "GARRAFA": "GF",
        "LATA": "LT",
        "PACOTE": "PCT",
        "CAIXA": "CX",
        "SACO": "SCO",
        "POTE": "POTE",
        "FRASCO": "FR",
        "UNIDADE": "UN",
        "PACK": "PACK",
        "FARDO": "FARDO",
    }

    # -------------------------------------------------
    # 3. Proteger quantidades e unidades (ex: 350ML, 1,5KG, 200G, 2L)
    # -------------------------------------------------
    unidades = re.findall(
        r"\b\d+[.,]?\d*\s?(?:ML|L|G|KG|MG|CM|M|UN|CX|PCT)\b",
        nome,
        flags=re.IGNORECASE,
    )
    unidades += re.findall(
        r"\b\d+[.,]?\d*(?:ML|L|G|KG|MG|CM|M|UN|CX|PCT)\b",
        nome,
        flags=re.IGNORECASE,
    )
    unidades = list(dict.fromkeys(unidades))

    # Remove temporariamente as unidades para proteção
    nome_sem_unidades = nome
    for u in unidades:
        nome_sem_unidades = nome_sem_unidades.replace(u.upper(), " §UNIT§ ")

    # -------------------------------------------------
    # 4. Remover stopwords
    # -------------------------------------------------
    stopwords = {
        "DE", "DA", "DO", "DAS", "DOS",
        "COM", "PARA", "EM", "E", "OU",
        "TIPO", "SABOR", "REF", "PRODUTO"
    }

    palavras = [p for p in nome_sem_unidades.split() if p and p not in stopwords]

    # -------------------------------------------------
    # 5. Aplicar dicionário de abreviações
    # -------------------------------------------------
    palavras_proc = []
    for p in palavras:
        if p == "§UNIT§":
            continue
        palavras_proc.append(abreviacoes.get(p, p))

    # -------------------------------------------------
    # 6. Reinserir unidades no final
    # -------------------------------------------------
    unidades_limpa = []
    for u in unidades:
        u = u.upper().replace(" ", "")
        unidades_limpa.append(u)

    nome_base = " ".join(palavras_proc).strip()
    if unidades_limpa:
        nome_base = f"{nome_base} {' '.join(unidades_limpa)}".strip()

    if len(nome_base) <= limite_caracteres:
        return nome_base

    # -------------------------------------------------
    # 7. Encurtamento inteligente se exceder limite
    # -------------------------------------------------
    partes = nome_base.split()
    if not partes:
        return nome_base[:limite_caracteres]

    unidade_final = ""
    if partes and re.search(r"\d", partes[-1]) and re.search(r"(ML|L|G|KG|UN|CX|PCT)$", partes[-1]):
        unidade_final = partes[-1]
        partes = partes[:-1]

    novas = []
    for i, p in enumerate(partes):
        if i == 0:
            novas.append(p[:8] if len(p) > 10 else p)
        else:
            if len(p) > 5 and not p[-1].isdigit():
                novas.append(p[:4] if not agressivo else p[:3])
            else:
                novas.append(p)

    resultado = " ".join(novas)
    if unidade_final:
        resultado = f"{resultado} {unidade_final}".strip()

    if len(resultado) > limite_caracteres:
        if unidade_final and resultado.endswith(unidade_final):
            espaco_disponivel = limite_caracteres - len(unidade_final) - 1
            if espaco_disponivel > 4:
                resultado = resultado[:espaco_disponivel].rstrip() + " " + unidade_final
            else:
                resultado = resultado[:limite_caracteres]
        else:
            resultado = resultado[:limite_caracteres]

    return resultado.strip()


def quebrar_linhas_inteligente(texto: str, max_por_linha: int = 16) -> str:
    """Quebra um nome de produto em 2 linhas equilibradas com \\r para o Photoshop."""
    limpo = str(texto or "").replace("\\r\\n", " ").replace("\\r", " ").replace("\\n", " ").replace("\r\n", " ").replace("\r", " ").replace("\n", " ")
    palavras = limpo.split()
    if len(palavras) <= 1:
        return limpo
    if len(palavras) == 2:
        if len(limpo) > max_por_linha:
            return f"{palavras[0]}\r{palavras[1]}"
        return limpo

    # Procura a melhor quebra próxima do meio
    total_len = len(limpo)
    target = total_len // 2
    melhor_i = 1
    menor_dif = float("inf")

    atual_len = 0
    for i in range(len(palavras) - 1):
        atual_len += len(palavras[i]) + (1 if i > 0 else 0)
        dif = abs(atual_len - target)
        if dif < menor_dif:
            menor_dif = dif
            melhor_i = i + 1

    linha1 = " ".join(palavras[:melhor_i])
    linha2 = " ".join(palavras[melhor_i:])
    return f"{linha1}\r{linha2}"
