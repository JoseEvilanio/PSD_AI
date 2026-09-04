#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
detector_conflito_imagens.py
-----------------------------
Utilitário preventivo para varredura de ofertas e fotos antes da geração no Photoshop.
Identifica e previne falsos positivos de imagem (ex: Moça vs Mococa), ambiguidades e itens sem foto.
"""

from __future__ import annotations

import argparse
import difflib
import os
import re
import sys
import unicodedata
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

# Tenta importar utilitários do core do Autoflyer se disponível
try:
    from core.data_loader import DataLoader, mapear_colunas_com_prioridade
except ImportError:
    DataLoader = None
    mapear_colunas_com_prioridade = None


# Tenta configurar stdout para UTF-8 no Windows
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Cores ANSI para saída rica no terminal
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
CYAN = "\033[96m"
BOLD = "\033[1m"
RESET = "\033[0m"


def normalizar_texto(texto: str) -> str:
    """Remove acentos, pontuações e converte para minúsculas."""
    if not texto:
        return ""
    nfkd = unicodedata.normalize("NFKD", str(texto))
    sem_acento = "".join(c for c in nfkd if not unicodedata.combining(c))
    limpo = re.sub(r"[^a-zA-Z0-9]+", " ", sem_acento).strip().lower()
    return limpo


def extrair_tokens(texto: str) -> Set[str]:
    """Extrai palavras com 2 ou mais caracteres para indexação."""
    norm = normalizar_texto(texto)
    return {w for w in norm.split() if len(w) >= 2}


def calcular_similaridade(a: str, b: str) -> float:
    """Calcula a taxa de similaridade difflib entre duas strings normalizadas."""
    return difflib.SequenceMatcher(None, normalizar_texto(a), normalizar_texto(b)).ratio()


# Lista de palavras comuns e genéricas em supermercados que não definem marca
STOPWORDS_VAREJO = {
    "de", "em", "para", "com", "sem", "tipo", "kg", "g", "gr", "ml", "l", "lt", 
    "un", "pct", "cx", "lata", "tp", "pet", "refil", "tradicional", "integral",
    "desnatado", "semidesnatado", "promocao", "oferta", "produto", "preco"
}


def extrair_marcas_candidatas(texto: str) -> List[str]:
    """Filtra palavras-chave que provavelmente representam marcas ou variantes críticas."""
    tokens = [w for w in normalizar_texto(texto).split() if len(w) >= 3 and w not in STOPWORDS_VAREJO]
    return tokens


class DetectorConflitoImagens:
    def __init__(self, threshold_conflito: float = 0.75):
        self.threshold_conflito = threshold_conflito

    def analisar_ofertas_e_imagens(
        self,
        ofertas: List[Dict[str, Any]],
        caminhos_imagens: List[Path]
    ) -> Dict[str, List[Dict[str, Any]]]:
        """
        Analisa a lista de ofertas contra as imagens disponíveis e classifica em 4 grupos:
        - matches_seguros
        - conflitos_criticos
        - ambiguidades
        - sem_imagem
        """
        resultados = {
            "matches_seguros": [],
            "conflitos_criticos": [],
            "ambiguidades": [],
            "sem_imagem": []
        }

        # Mapeia as imagens disponíveis
        imagens_info = []
        for img_path in caminhos_imagens:
            stem = img_path.stem
            parent_name = img_path.parent.name if img_path.parent else ""
            full_text = f"{parent_name} {stem}"
            tokens = extrair_tokens(full_text)
            palavras_chave = extrair_marcas_candidatas(stem)
            imagens_info.append({
                "path": img_path,
                "stem": stem,
                "tokens": tokens,
                "palavras_chave": palavras_chave,
                "norm": normalizar_texto(stem)
            })

        for oferta in ofertas:
            nome_produto = oferta.get("nome", "")
            slot = oferta.get("slot", "?")
            imagem_especificada = oferta.get("imagem")

            if not nome_produto:
                continue

            tokens_produto = extrair_tokens(nome_produto)
            marcas_produto = extrair_marcas_candidatas(nome_produto)
            norm_produto = normalizar_texto(nome_produto)

            # 1. Se uma imagem específica foi fornecida e existe no disco
            if imagem_especificada:
                p = Path(imagem_especificada)
                if p.exists() or any(p.name.lower() == img["path"].name.lower() for img in imagens_info):
                    resultados["matches_seguros"].append({
                        "slot": slot,
                        "produto": nome_produto,
                        "imagem": str(imagem_especificada),
                        "motivo": "Imagem explicitamente indicada no arquivo de dados."
                    })
                    continue

            # 2. Busca e pontua todas as imagens candidatas
            candidatos = []
            for img in imagens_info:
                overlap = tokens_produto & img["tokens"]
                score_overlap = len(overlap)
                sim_global = calcular_similaridade(norm_produto, img["norm"])

                # Verifica conflito crítico de marca/termo chave (ex: moca vs mococa)
                conflito_detectado = None
                for mp in marcas_produto:
                    # Se a palavra exata já existe na imagem, não é um falso positivo
                    if mp in img["palavras_chave"] or mp in img["tokens"]:
                        continue
                    for mi in img["palavras_chave"]:
                        # Se a palavra da imagem já existe no produto, também não é conflito
                        if mi in marcas_produto or mi in tokens_produto:
                            continue
                        sim_marca = difflib.SequenceMatcher(None, mp, mi).ratio()
                        # Se as marcas são parecidas (ex: moca e mococa = 80.0%) mas NÃO são iguais
                        if 0.70 <= sim_marca < 1.0:
                            conflito_detectado = {
                                "marca_produto": mp,
                                "marca_imagem": mi,
                                "similaridade": sim_marca * 100.0
                            }
                            break
                    if conflito_detectado:
                        break

                if score_overlap >= 2 or sim_global >= 0.65 or norm_produto in img["norm"] or img["norm"] in norm_produto:
                    candidatos.append({
                        "img": img,
                        "score_overlap": score_overlap,
                        "sim_global": sim_global,
                        "conflito": conflito_detectado
                    })

            # 3. Classifica com base nos candidatos encontrados
            if not candidatos:
                resultados["sem_imagem"].append({
                    "slot": slot,
                    "produto": nome_produto,
                    "motivo": "Nenhum arquivo correspondente encontrado no diretório de imagens."
                })
            else:
                # Ordena os candidatos por relevância
                candidatos.sort(key=lambda c: (c["score_overlap"], c["sim_global"]), reverse=True)
                melhor = candidatos[0]

                # Verifica se o melhor candidato possui conflito crítico (Falso Positivo perigoso)
                if melhor["conflito"]:
                    confl = melhor["conflito"]
                    resultados["conflitos_criticos"].append({
                        "slot": slot,
                        "produto": nome_produto,
                        "imagem_conflitante": str(melhor["img"]["path"].name),
                        "caminho_completo": str(melhor["img"]["path"]),
                        "marca_produto": confl["marca_produto"],
                        "marca_imagem": confl["marca_imagem"],
                        "similaridade": confl["similaridade"],
                        "motivo": (
                            f"Risco de Falso Positivo! O produto contém '{confl['marca_produto']}' "
                            f"mas a imagem candidata é de '{confl['marca_imagem']}' "
                            f"(Similaridade de caracteres: {confl['similaridade']:.1f}%)."
                        )
                    })
                elif len(candidatos) > 1 and abs(candidatos[0]["score_overlap"] - candidatos[1]["score_overlap"]) == 0 and abs(candidatos[0]["sim_global"] - candidatos[1]["sim_global"]) < 0.05:
                    # Múltiplas imagens com scores praticamente idênticos
                    resultados["ambiguidades"].append({
                        "slot": slot,
                        "produto": nome_produto,
                        "opcoes": [str(c["img"]["path"].name) for c in candidatos[:3]],
                        "motivo": f"Existem {len(candidatos)} imagens candidatas com pontuação muito similar."
                    })
                else:
                    resultados["matches_seguros"].append({
                        "slot": slot,
                        "produto": nome_produto,
                        "imagem": str(melhor["img"]["path"].name),
                        "caminho_completo": str(melhor["img"]["path"]),
                        "score_overlap": melhor["score_overlap"],
                        "similaridade": melhor["sim_global"] * 100.0,
                        "motivo": f"Correspondência clara com {melhor['score_overlap']} palavras coincidentes."
                    })

        return resultados


def imprimir_relatorio(resultados: Dict[str, List[Dict[str, Any]]]) -> None:
    """Imprime o relatório consolidado no terminal com formatação visual."""
    total_seguros = len(resultados["matches_seguros"])
    total_conflitos = len(resultados["conflitos_criticos"])
    total_ambiguidades = len(resultados["ambiguidades"])
    total_sem_imagem = len(resultados["sem_imagem"])
    total_analisados = total_seguros + total_conflitos + total_ambiguidades + total_sem_imagem

    print("\n" + "=" * 78)
    print(f"{BOLD}{CYAN}      DETECTOR DE CONFLITOS DE IMAGENS E VALIDAÇÃO DE ENCARTE{RESET}")
    print("=" * 78)
    print(f"Total de ofertas analisadas: {BOLD}{total_analisados}{RESET}\n")

    # 1. Conflitos Críticos (Alerta Máximo)
    if total_conflitos > 0:
        print(f"{BOLD}{RED}[!] CONFLITOS CRITICOS (Falsos Positivos Prevenidos): {total_conflitos}{RESET}")
        print("-" * 78)
        for item in resultados["conflitos_criticos"]:
            print(f"  * {BOLD}Slot {item['slot']}:{RESET} {item['produto']}")
            print(f"    {RED}--> Imagem rejeitada:{RESET} {item['imagem_conflitante']}")
            print(f"    {YELLOW}--> Alerta:{RESET} {item['motivo']}")
        print()
    else:
        print(f"{BOLD}{GREEN}[OK] CONFLITOS CRITICOS:{RESET} Nenhum falso positivo detectado!\n")

    # 2. Ambiguidades
    if total_ambiguidades > 0:
        print(f"{BOLD}{YELLOW}[?] AMBIGUIDADES (Multiplas Imagens Candidatas): {total_ambiguidades}{RESET}")
        print("-" * 78)
        for item in resultados["ambiguidades"]:
            print(f"  * {BOLD}Slot {item['slot']}:{RESET} {item['produto']}")
            print(f"    {YELLOW}--> Opcoes encontradas:{RESET} {', '.join(item['opcoes'])}")
        print()

    # 3. Sem Imagem
    if total_sem_imagem > 0:
        print(f"{BOLD}{CYAN}[o] PRODUTOS SEM IMAGEM (Usarao Placeholder): {total_sem_imagem}{RESET}")
        print("-" * 78)
        for item in resultados["sem_imagem"]:
            print(f"  * {BOLD}Slot {item['slot']}:{RESET} {item['produto']}")
        print()

    # 4. Matches Seguros
    if total_seguros > 0:
        print(f"{BOLD}{GREEN}[OK] MATCHES SEGUROS (1 para 1 Confirmados): {total_seguros}{RESET}")
        print("-" * 78)
        for item in resultados["matches_seguros"]:
            print(f"  * {BOLD}Slot {item['slot']}:{RESET} {item['produto']}")
            print(f"    {GREEN}--> Foto associada:{RESET} {item['imagem']}")
        print()

    print("=" * 78)
    if total_conflitos > 0:
        print(f"{BOLD}{RED}Status Final: REQUER ATENCAO! Corrija os conflitos criticos acima antes de exportar.{RESET}")
    else:
        print(f"{BOLD}{GREEN}Status Final: TUDO PRONTO! Imagens validadas e seguras para geracao no Photoshop.{RESET}")
    print("=" * 78 + "\n")


def carregar_planilha_robusta(caminho_arquivo: Path) -> List[Dict[str, Any]]:
    """Carrega dados da planilha aplicando a regra estrita de prioridade de colunas."""
    import pandas as pd

    ext = caminho_arquivo.suffix.lower()
    if ext == ".csv":
        df = pd.read_csv(caminho_arquivo)
    elif ext in {".xlsx", ".xls"}:
        df = pd.read_excel(caminho_arquivo)
    else:
        raise ValueError(f"Formato não suportado: {ext}")

    df = df.dropna(how="all").copy()

    # Usa mapeamento com prioridade se disponível
    if mapear_colunas_com_prioridade is not None:
        mapa = mapear_colunas_com_prioridade(list(df.columns))
        col_to_internal = {orig: chave for chave, orig in mapa.items()}
        df = df.rename(columns=col_to_internal)
    else:
        # Fallback de prioridade caso o core não esteja no path
        cols_lower = {str(c).lower(): c for c in df.columns}
        renomear = {}
        for candidate in ["nome", "produto", "titulo", "descricao"]:
            if candidate in cols_lower:
                renomear[cols_lower[candidate]] = "nome"
                break
        df = df.rename(columns=renomear)

    ofertas = []
    for idx, row in df.iterrows():
        nome = row.get("nome")
        if not nome or pd.isna(nome) or str(nome).strip() == "":
            continue
        slot_val = row.get("slot")
        slot = int(float(slot_val)) if slot_val not in (None, "") and not pd.isna(slot_val) else idx + 1
        img_val = row.get("imagem")
        img_str = str(img_val).strip() if img_val is not None and not pd.isna(img_val) else None
        ofertas.append({
            "slot": slot,
            "nome": str(nome).strip(),
            "imagem": img_str
        })
    return ofertas


def executar_cenario_demonstracao() -> None:
    """Executa uma demonstração preventiva com o clássico cenário de conflito Moça vs Mococa."""
    print(f"\n{BOLD}{CYAN}[MODO DEMONSTRAÇÃO PREVENTIVA]{RESET}")
    print("Nenhum arquivo fornecido. Simulando cenário real de supermercado para teste do algoritmo...")

    ofertas_exemplo = [
        {"slot": 1, "nome": "DESODORANTE AEROSOL ABOVE 150ML", "imagem": None},
        {"slot": 2, "nome": "SABAO EM PO OMO LAVAGEM PERFEITA 1.6KG", "imagem": None},
        {"slot": 3, "nome": "ARROZ TIPO 1 CAMIL 5KG", "imagem": None},
        {"slot": 4, "nome": "FEIJAO CARIOCA KICALDO 1KG", "imagem": None},
        {"slot": 5, "nome": "OLEO DE SOJA SOYA 900ML", "imagem": None},
        # Cenário Crítico: Produto é Leite Moça, mas pasta contém foto da Mococa!
        {"slot": 6, "nome": "LEITE CONDENSADO MOCA LATA 395G", "imagem": None},
        {"slot": 7, "nome": "CAFE TRADICIONAL PILAO 500G", "imagem": None},
    ]

    imagens_exemplo = [
        Path("F:/PRODUTO/ARROZ/ARROZ TIPO 1 CAMIL 5KG.png"),
        Path("F:/PRODUTO/FEIJAO/FEIJAO CARIOCA KICALDO 1KG.png"),
        Path("F:/PRODUTO/OLEO/OLEO DE SOJA SOYA 900ML.png"),
        Path("F:/PRODUTO/HIGIENE/SABÂO EM PÓ LAVAGEM PERFEITA.png"),
        # Simula pasta que contém foto da Mococa quando o produto cadastrado é Moça
        Path("F:/PRODUTO/LATICINIOS/LEITE CONDENSADO MOCOCA TP 395G.png"),
        # Duas opções para o Above gerando ambiguidade controlada
        Path("F:/PRODUTO/HIGIENE/DESODORANTE AEROSOL ABOVE MEN 150ML.png"),
        Path("F:/PRODUTO/HIGIENE/DESODORANTE AEROSOL ABOVE WOMEN 150ML.png"),
    ]

    detector = DetectorConflitoImagens()
    resultados = detector.analisar_ofertas_e_imagens(ofertas_exemplo, imagens_exemplo)
    imprimir_relatorio(resultados)


def main():
    parser = argparse.ArgumentParser(
        description="Detector preventivo de conflitos de imagens para encartes Autoflyer."
    )
    parser.add_argument("--planilha", type=str, default=None, help="Caminho para o arquivo CSV ou Excel.")
    parser.add_argument("--imagens", type=str, default=None, help="Caminho para o diretório raiz das imagens.")
    parser.add_argument("--threshold", type=float, default=0.75, help="Limiar de similaridade difflib (default: 0.75).")
    args = parser.parse_args()

    # Se nenhum argumento for passado, executa a simulação didática preventiva
    if not args.planilha and not args.imagens:
        executar_cenario_demonstracao()
        return

    # Se argumentos forem fornecidos, valida a existência dos caminhos
    planilha_path = Path(args.planilha).resolve() if args.planilha else None
    if not planilha_path or not planilha_path.exists():
        print(f"{RED}Erro: Arquivo de planilha não encontrado: {args.planilha}{RESET}")
        sys.exit(1)

    imagens_dir = Path(args.imagens).resolve() if args.imagens else Path("data/products").resolve()
    if not imagens_dir.exists():
        print(f"{RED}Erro: Diretório de imagens não encontrado: {imagens_dir}{RESET}")
        sys.exit(1)

    # Coleta todas as imagens válidas no diretório especificado
    extensoes_validas = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
    arquivos_imagens = [p for p in imagens_dir.rglob("*") if p.is_file() and p.suffix.lower() in extensoes_validas]

    ofertas = carregar_planilha_robusta(planilha_path)
    detector = DetectorConflitoImagens(threshold_conflito=args.threshold)
    resultados = detector.analisar_ofertas_e_imagens(ofertas, arquivos_imagens)
    imprimir_relatorio(resultados)


if __name__ == "__main__":
    main()
