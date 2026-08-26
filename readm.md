# Autoflyer

Sistema desktop para gerar encartes promocionais a partir de um template Adobe Photoshop (`.psd` ou `.psb`) e de uma planilha de ofertas (`.csv`, `.xlsx` ou `.xls`). O programa lê os produtos, valida os dados, localiza imagens, identifica os grupos de ofertas do PSD, atualiza textos e Smart Objects e exporta a arte final.

> **Estado atual:** o projeto possui integração com Photoshop por COM e um modo fallback para desenvolvimento. Não existe, neste código, integração implementada com Ollama ou outro serviço de IA.

## Funcionalidades

- Interface gráfica em Tkinter para selecionar:
  - template PSD/PSB;
  - planilha CSV ou Excel;
  - pasta de imagens dos produtos.
- Detecção automática de template dentro de `arquivo.psd`, `data/templates` ou na raiz do projeto.
- Leitura de CSV, XLSX e XLS com `pandas`.
- Reconhecimento de nomes alternativos de colunas, incluindo `produto`, `descricao`, `por`, `preco`, `foto`, `un` e `medida`.
- Conversão de preços brasileiros e internacionais, por exemplo `R$ 9,90`, `9.90`, `1.234,56` e `1,234.56`.
- Busca de imagens por caminho informado, nome do arquivo, nome do produto e palavras em comum.
- Geração automática de imagem placeholder PNG quando nenhuma imagem é encontrada.
- Validação de slots, nomes, preços, imagens ausentes e duplicidade de posições.
- Inspeção do PSD com `psd-tools` para reconhecer grupos de produtos e extrair metadados.
- Automação do Photoshop instalado no Windows usando `Photoshop.Application` via COM.
- Exportação da árvore nativa do documento aberto no Photoshop para JSON, com grupos, camadas, textos, IDs, tipos, visibilidade, opacidade e limites.
- Atualização de nome do produto, preço promocional, preço anterior, unidade, indicação `cada` e imagens Smart Object.
- Ajuste de texto para caber na área original e ajuste proporcional de imagens dentro do espaço do template.
- Análise de colisão entre a descrição e cada elemento visível do grupo: cada camada vizinha de texto ou imagem é medida individualmente, recebe uma distância mínima e pode restringir a caixa por qualquer lado, sem alterar o tamanho original da fonte.
- Exportação para JPG ou PNG.
- Tentativas de repetição durante a atualização de cada slot e durante a exportação.
- Registro de execução em `logs/autoflyer.log` e no console.
- Modo fallback quando o Photoshop não está disponível ou o COM não consegue conectar.

## Requisitos

- Windows para automação real do Photoshop.
- Python 3.10 ou superior recomendado.
- Adobe Photoshop instalado e acessível para preencher/exportar o PSD de verdade.
- Python e Photoshop com arquiteturas compatíveis, normalmente ambos 64-bit.
- Dependências listadas em `requirements.txt`.

Instalação:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

Dependências principais:

- `pywin32`: conexão COM com o Photoshop;
- `pandas`: leitura e tratamento de dados;
- `openpyxl`: leitura de arquivos `.xlsx`;
- `PyYAML`: leitura de `config/settings.yaml`;
- `Pillow`: criação e exportação de imagens auxiliares;
- `psd-tools`: inspeção e composição de PSD no modo fallback. Ele é usado pelo código, embora ainda não esteja listado em `requirements.txt`; instale-o com `pip install psd-tools` para habilitar essa parte.

## Execução

Na pasta do projeto:

```powershell
python main.py
```

O programa configura o log, abre a janela `Autoflyer — Automação de encartes` e cria automaticamente as pastas necessárias. Caso a GUI não possa ser iniciada, o programa executa um smoke test de console que carrega `data/inputs/example_offers.csv`, valida os itens e lista os templates encontrados.

## Fluxo completo de geração

1. `main.py` carrega o YAML e configura o arquivo `logs/autoflyer.log`.
2. A janela procura automaticamente um PSD em:
   - `arquivo.psd/`;
   - `data/templates/`;
   - raiz do projeto.
3. O usuário seleciona o template, a planilha e a pasta de imagens.
4. **Validar dados** carrega a planilha e executa `Validator.validate_offers`.
5. **Gerar arte** exige um template, uma planilha e uma pasta de imagens válida.
6. `GenerationWorkflow` garante que o template exista. Se o caminho selecionado não existir, procura o primeiro `.psd` ou `.psb` nos diretórios de templates.
7. `DataLoader` lê e normaliza os itens, resolve as imagens e ordena as ofertas pelo slot.
8. Ofertas sem imagem recebem um placeholder em `data/products`.
9. O validador interrompe a geração somente quando existem erros; avisos são mantidos no resultado.
10. `PsdTemplateInspector` abre o PSD e procura grupos reconhecíveis, como `GRUPO 01`, `GROUP_01`, `PRODUTO 01` ou nomes contendo `DESCRI` e `PRE`/`PREÇO`.
11. `PhotoshopEngine` conecta ao Photoshop, abre o template e atualiza cada slot. Cada slot pode ser tentado até oito vezes.
12. Com o Photoshop conectado, a árvore de camadas do documento é salva em `data/outputs/<nome-do-template>_camadas.json`.
13. O resultado é salvo em `data/outputs/<nome-do-template>_gerado.jpg` ou `.png`.

## Modelo da planilha

Colunas padronizadas:

| Coluna | Obrigatória | Descrição |
|---|---:|---|
| `slot` | Não | Posição do produto no encarte. Se ausente, usa o número da linha, começando em 1. |
| `nome` | Sim | Nome ou descrição do produto. Linhas sem nome são ignoradas na leitura. |
| `preco_de` | Não | Preço anterior, usado para exibir a oferta `DE`. |
| `preco_por` | Não | Preço promocional. A ausência gera aviso. |
| `imagem` | Não | Caminho ou nome do arquivo da imagem. |
| `unidade` | Não | Unidade como `UN`, `KG`, `LT`, `CX`, `PCT`, `G` ou `ML`. |
| `cada` | Não | Texto adicional normalmente usado para indicar venda por unidade. |

Sinônimos aceitos:

- `slot`: `posicao`, `item`, `ordem`;
- `nome`: `produto`, `descricao`, `titulo`;
- `preco_de`: `preco_original`, `de`, `precode`;
- `preco_por`: `por`, `preco_promocional`, `preco`;
- `imagem`: `img`, `foto`, `image`;
- `unidade`: `un`, `medida`.

Exemplo:

```csv
slot,nome,preco_de,preco_por,imagem,unidade,cada
1,Leite Integral,9.90,7.99,leite.png,UN,cada
2,Arroz Tipo 1,12.50,10.99,arroz.png,KG,
```

### Regras de preços

- Valores numéricos são convertidos para `float`.
- `R$`, `USD`, `BRL`, espaços e separadores são tratados.
- A exibição brasileira usa, por exemplo, `R$ 7,99`.
- No Photoshop, o preço composto é separado em parte inteira e centavos.
- Se o PSD tiver um grupo de preço, camadas numéricas, `DE`, `POR`, `R$`, vírgula e unidade são atualizadas por reconhecimento de conteúdo/nome.
- Sem grupo de preço, o sistema procura camadas de texto numéricas e camadas com unidade ou `DE` diretamente no grupo do produto.

## Localização de imagens

A imagem é procurada nesta ordem geral:

1. caminho absoluto informado na planilha;
2. pasta da própria planilha;
3. pasta de imagens escolhida na interface;
4. `data/products`;
5. busca recursiva por nome exato ou por palavras do nome do produto.

São aceitos `.png`, `.jpg`, `.jpeg`, `.webp` e `.bmp`. A busca por palavras exige evidência suficiente para evitar associar uma imagem genérica ao produto errado. Quando não há correspondência, um PNG placeholder de 600x600 é criado em `data/products`.

## Estrutura esperada do template PSD

O template deve possuir grupos de produtos identificáveis por número, por exemplo `GRUPO 1`, `PRODUTO_02` ou `GROUP 03`. Dentro de cada grupo, o sistema tenta encontrar:

- uma camada de texto mais longa para o nome;
- camadas de texto para o preço anterior e promocional;
- unidade e texto `cada`;
- um ou mais Smart Objects para imagens;
- camadas nomeadas como `SHAPE`, `RECTANGLE`, `RETANGULO`, `ELLIPSE` ou `ELIPSE` para delimitar áreas.

O inspetor também extrai, quando disponíveis, nome, preço `DE`, preço promocional, unidade, `cada` e referência de imagem. Se nenhum grupo reconhecível for encontrado, a geração falha com a mensagem de que o template não possui grupos de oferta reconhecíveis.

### Proteção contra sobreposição

Antes de finalizar o nome do produto, o motor mede os limites de todas as camadas visíveis vizinhas, incluindo `R$`, preço inteiro, centavos, unidade, `DE`, outros textos e Smart Objects. Para cada elemento, calcula se há interseção horizontal ou vertical com a descrição e estabelece a margem mínima de segurança. Em seguida, quebra o texto em linhas e habilita entrelinha automática, mantendo intacto o tamanho de fonte definido no PSD. Depois do ajuste, o Photoshop mede novamente a caixa renderizada; se o texto ainda não couber, a ocorrência é registrada no log em vez de alterar a tipografia original. Essa análise ocorre para cada grupo de oferta durante a geração.

## Photoshop e modo fallback

Quando o Photoshop está instalado e o COM funciona, o sistema:

- abre o PSD no Photoshop;
- fecha documentos abertos antes de carregar o template;
- substitui o conteúdo dos Smart Objects;
- preserva a posição da imagem e limita seu tamanho à área correspondente;
- altera as camadas de texto e quebra nomes longos em linhas;
- salva a arte com as opções de qualidade configuradas.
- disponibiliza o documento aberto pelo DOM COM e o serializa para JSON através de `get_native_layer_tree()` e `export_native_layer_tree_json()`.

Se o Photoshop estiver ausente, o COM falhar ou houver incompatibilidade de arquitetura, o sistema não executa alterações reais nas camadas: usa um stub para permitir testes e gera uma composição do PSD com `psd-tools` quando possível. Se essa composição também falhar, cria uma imagem placeholder informando que o Photoshop não está disponível. Portanto, o fallback confirma o fluxo técnico e gera uma prévia, mas não produz uma arte realmente preenchida com as ofertas.

## Validações

São considerados erros:

- planilha sem ofertas válidas;
- slot menor que 1 ou maior que 50;
- template inexistente, diretório sem PSD/PSB ou extensão não suportada.

São considerados avisos:

- slot duplicado, pois a entrada posterior pode sobrescrever a anterior;
- preço promocional ausente ou menor/igual a zero;
- preço `de` menor ou igual ao preço promocional;
- imagem não encontrada ou não mapeada;
- slot que não pôde ser atualizado no Photoshop.

Erros de validação impedem a geração. Avisos não impedem a exportação.

## Configuração

Arquivo: `config/settings.yaml`

```yaml
paths:
  templates_dir: arquivo.psd
  products_dir: data/products
  inputs_dir: data/inputs
  outputs_dir: data/outputs
  logs_dir: logs

photoshop:
  visible: true
  display_dialogs: false

export:
  format: JPG
  quality: 90
```

`format` pode ser `JPG` ou `PNG`. A qualidade é limitada pelo Photoshop ao intervalo de 0 a 100 e convertida para a escala interna de qualidade JPEG. A interface atualmente usa seus diretórios padrão e passa `JPG` com qualidade 90 ao workflow; as opções YAML são usadas pelo carregamento geral e pelo smoke test, mas não são aplicadas integralmente aos controles da GUI.

## Estrutura do projeto

```text
autoflyer/
├── main.py                         # Entrada da aplicação e smoke test
├── requirements.txt                # Dependências Python
├── config/settings.yaml            # Caminhos e opções de exportação
├── core/
│   ├── data_loader.py              # Leitura, normalização e busca de imagens
│   ├── layer_identifier.py         # Classificação auxiliar de camadas
│   ├── photoshop_engine.py         # COM, atualização do PSD e exportação
│   ├── price_mode_detector.py      # Detecção de preço simples ou composto
│   ├── psd_template_inspector.py   # Inspeção estrutural do PSD
│   ├── template_manager.py         # Listagem e seleção de templates
│   ├── validator.py                # Validação de ofertas e templates
│   └── workflow.py                 # Orquestração da geração
├── ui/main_window.py               # Janela Tkinter
├── data/inputs/                    # CSVs e planilhas de entrada
├── data/products/                  # Imagens e placeholders
├── data/templates/                 # Templates opcionais
├── data/outputs/                   # Artes exportadas
├── arquivo.psd/                    # Local alternativo usado pelo projeto
└── logs/                           # Logs da execução
```

## Classes e responsabilidades

### `OfferItem`

Representa uma oferta normalizada. Mantém slot, nome, preços, imagem, unidade, `cada`, campos fornecidos e propriedades formatadas como `preco_por_str`, `preco_de_str`, `preco_por_inteiro` e `preco_por_decimal`.

### `DataLoader`

Carrega CSV/Excel, reconhece colunas, limpa preços, cria `OfferItem`, resolve imagens e retorna os itens ordenados e metadados de carregamento.

### `Validator` e `ValidationResult`

Validam template e ofertas, acumulam erros/avisos e expõem `is_valid` para decidir se o workflow pode continuar.

### `TemplateManager`

Lista PSD/PSB recursivamente, cria `TemplateInfo`, pesquisa template por nome e encontra o primeiro template padrão.

### `PsdTemplateInspector`

Lê a estrutura do PSD sem abrir o Photoshop, detecta grupos de slots e extrai metadados visíveis das camadas.

### `LayerIdentifier` e `PriceModeDetector`

São utilitários de classificação. O primeiro associa possíveis camadas a nome, preço, unidade, `cada` e imagem; o segundo distingue preço oficial único de preço legado composto. A atualização principal do Photoshop usa sua própria análise de camadas.

### `PhotoshopEngine`

Abstrai conexão COM, abertura do documento, busca recursiva de grupos/camadas, atualização de texto, substituição de Smart Objects, ajuste de limites e exportação JPG/PNG.

### `GenerationWorkflow` e `GenerationResult`

Orquestram o processamento completo e retornam caminhos, quantidade carregada, status, avisos e erros por meio de `to_dict()`.

## Saídas e logs

- JPG padrão: `data/outputs/<template>_gerado.jpg`.
- PNG: `data/outputs/<template>_gerado.png`.
- Árvore nativa: `data/outputs/<template>_camadas.json` quando a conexão COM estiver disponível.
- Log: `logs/autoflyer.log`.
- Placeholders: `data/products/<nome>.png`.

O arquivo de saída pode existir mesmo em modo fallback; verifique o log para confirmar se ele foi exportado pelo Photoshop ou composto pelo `psd-tools`.

## Problemas comuns

**A janela não abre**

Execute em uma sessão com suporte gráfico do Windows. Em ambiente headless, o `main.py` tenta continuar pelo smoke test de console.

**Photoshop aparece instalado, mas não atualiza o PSD**

Confirme que o Photoshop está instalado, que `pywin32` está disponível e que Python e Photoshop têm a mesma arquitetura. O log informa o erro COM e o tamanho de ponteiro detectado.

**Template não reconhecido**

Verifique a extensão `.psd`/`.psb`, a abertura do arquivo e os nomes dos grupos. Deve haver grupos numerados ou nomes contendo os marcadores reconhecidos pelo inspetor.

**Imagem errada ou placeholder**

Prefira colocar o caminho/nome exato na coluna `imagem` e confirme a pasta escolhida. A busca automática só aceita correspondência textual com evidência suficiente.

**Oferta não aparece no slot**

Confira se o número do `slot` corresponde ao número do grupo no PSD e consulte `logs/autoflyer.log`. O Photoshop pode exigir novas tentativas quando termina operações assíncronas.

**Erro ao compor PSD no fallback**

Instale `psd-tools` e suas dependências. Ainda assim, composição fallback é apenas prévia; a geração final preenchida exige Photoshop funcionando via COM.

## Limitações conhecidas

- A GUI depende de Tkinter e não oferece edição da planilha.
- O limite padrão de validação é 50 slots.
- A GUI exige explicitamente uma pasta de imagens válida, mesmo quando a planilha já possui caminhos absolutos.
- O template e os grupos precisam seguir convenções de nomes reconhecíveis; não há editor visual de mapeamento.
- O suporte a preço legado composto existe nos utilitários, mas a detecção não é exposta como opção na interface.
- Não há persistência de histórico, banco de dados, API web, processamento em lote na interface ou integração com IA neste estado do projeto.