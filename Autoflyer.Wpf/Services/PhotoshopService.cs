using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Text;
using Autoflyer.Wpf.Models;

namespace Autoflyer.Wpf.Services
{
    /// <summary>
    /// Serviço de automação de alto desempenho com o Adobe Photoshop.
    /// Utiliza ExtendScript nativo (DoJavaScript) com classificação espacial (coordenadas X)
    /// para identificação perfeita de Inteiro e Centavos, blindagem de slots e limites de encarte.
    /// </summary>
    public class PhotoshopService
    {
        private dynamic? _photoshopApp;
        private dynamic? _activeDoc;

        public bool Connect()
        {
            try
            {
                Type? psType = Type.GetTypeFromProgID("Photoshop.Application");
                if (psType == null) return false;

                _photoshopApp = Activator.CreateInstance(psType);
                if (_photoshopApp == null) return false;

                _photoshopApp.Visible = true;
                try { _photoshopApp.DisplayDialogs = 3; } catch { } // 3 = psDisplayNoDialogs
                return true;
            }
            catch (Exception ex)
            {
                Debug.WriteLine($"[PhotoshopService] Erro ao conectar: {ex.Message}");
                return false;
            }
        }

        public void Conectar()
        {
            if (!Connect())
            {
                throw new Exception("Adobe Photoshop não encontrado ou falha ao conectar via COM.");
            }
        }

        public bool OpenTemplate(string psdPath)
        {
            if (string.IsNullOrWhiteSpace(psdPath) || !File.Exists(psdPath))
                return false;

            if (_photoshopApp == null)
            {
                if (!Connect()) return false;
            }

            try
            {
                _activeDoc = _photoshopApp.Open(psdPath);
                return _activeDoc != null;
            }
            catch (Exception ex)
            {
                Debug.WriteLine($"[PhotoshopService] Erro ao abrir template: {ex.Message}");
                return false;
            }
        }

        public void AbrirTemplate(string psdPath)
        {
            if (!OpenTemplate(psdPath))
            {
                throw new Exception($"Falha ao abrir template PSD: {psdPath}");
            }
        }

        /// <summary>
        /// Atualiza os dados de um slot com classificação espacial e estrutural rigorosa.
        /// Se o slot não existir no template PSD, a operação é ignorada para não corromper outros slots.
        /// </summary>
        public void UpdateOfferSlot(OfferItem offer, int slotIndex)
        {
            if (_photoshopApp == null)
            {
                if (!Connect())
                    throw new InvalidOperationException("Photoshop não está conectado.");
            }

            string script = BuildSlotUpdateScript(offer, slotIndex);

            try
            {
                string result = _photoshopApp.DoJavaScript(script);
                Debug.WriteLine($"[PhotoshopService] Slot {slotIndex} resultado: {result}");
            }
            catch (Exception ex)
            {
                Debug.WriteLine($"[PhotoshopService] Erro em UpdateOfferSlot (Slot {slotIndex}): {ex.Message}");
            }
        }

        private string BuildSlotUpdateScript(OfferItem offer, int slotIndex)
        {
            string offerNome = EscapeJs(offer.Nome);
            string offerInteiro = EscapeJs(offer.PrecoPorInteiro);
            string offerCentavos = EscapeJs(offer.PrecoPorCentavos);
            string offerDe = EscapeJs(offer.PrecoDeFormatado);
            string offerUnidade = EscapeJs(offer.Unidade);
            string offerPrecoPor = offer.PrecoPor.HasValue
                ? EscapeJs(offer.PrecoPor.Value.ToString("N2", new CultureInfo("pt-BR")))
                : "null";

            string imagePath = !string.IsNullOrWhiteSpace(offer.ImagemPath) && File.Exists(offer.ImagemPath)
                ? EscapeJs(offer.ImagemPath.Replace("\\", "/"))
                : "null";

            return $@"
(function() {{
    try {{
        if (app.documents.length === 0) {{
            return JSON.stringify({{ success: false, error: 'Nenhum documento aberto' }});
        }}
        var doc = app.activeDocument;
        var slotIndex = {slotIndex};
        var offerNome = {offerNome};
        var offerInteiro = {offerInteiro};
        var offerCentavos = {offerCentavos};
        var offerDe = {offerDe};
        var offerPrecoPor = {offerPrecoPor};
        var offerUnidade = {offerUnidade};
        var imagePath = {imagePath};

        // 1. Localiza estritamente o grupo do slot (ex: 'GRUPO 1', 'PRODUTO 1', 'SLOT 1', etc.)
        function findSlotGroup(container, targetSlot) {{
            if (!container || !container.layerSets) return null;
            for (var i = 0; i < container.layerSets.length; i++) {{
                var g = container.layerSets[i];
                var nameUpper = g.name.toUpperCase();
                var m = nameUpper.match(/(\d+)/);
                if (m && parseInt(m[1], 10) === targetSlot) {{
                    return g;
                }}
                var sub = findSlotGroup(g, targetSlot);
                if (sub) return sub;
            }}
            return null;
        }}

        var slotGroup = findSlotGroup(doc, slotIndex);

        // REGRA DE OURO: Se o template não possui este slot (ex: planilha tem 8 itens, PSD só tem 6),
        // NUNCA altere o documento global para não sobrescrever outros slots!
        if (!slotGroup) {{
            return JSON.stringify({{ success: false, ignored: true, reason: 'Slot ' + slotIndex + ' não existe no PSD.' }});
        }}

        // 2. Coleta todas as camadas recursivamente apenas dentro do grupo do slot
        function collectLayers(container, outList) {{
            if (!container || !container.layers) return;
            for (var i = 0; i < container.layers.length; i++) {{
                var l = container.layers[i];
                outList.push(l);
                if (l.typename === 'LayerSet') {{
                    collectLayers(l, outList);
                }}
            }}
        }}

        var allSlotLayers = [];
        collectLayers(slotGroup, allSlotLayers);

        var textLayers = [];
        var smartObjects = [];

        for (var i = 0; i < allSlotLayers.length; i++) {{
            var l = allSlotLayers[i];
            if (l.typename === 'ArtLayer') {{
                if (l.kind === LayerKind.TEXT) {{
                    textLayers.push(l);
                }} else if (l.kind === LayerKind.SMARTOBJECT) {{
                    smartObjects.push(l);
                }}
            }}
        }}

        // 3. CLASSIFICAÇÃO RIGOROSA DAS CAMADAS DO SLOT
        var precoDeLayer = null;
        var unitLayer = null;
        var currencyLayer = null;
        var remainingTextLayers = [];

        for (var i = 0; i < textLayers.length; i++) {{
            var tl = textLayers[i];
            var n = tl.name.toUpperCase();
            var txt = '';
            try {{ txt = tl.textItem.contents.replace(/^\s+|\s+$/g, ''); }} catch(e) {{}}
            var txtUpper = txt.toUpperCase();

            // Preço DE (badge)
            if (/^DE[;\:\s\-_0-9]/i.test(n) || /^DE$/i.test(n) || /PRECO_DE|PRECODE|VALOR_DE/i.test(n) || /^DE[;\:\s\-_0-9]/i.test(txt)) {{
                if (!precoDeLayer) precoDeLayer = tl;
            }}
            // Moeda (R$)
            else if (/^R\$$/i.test(txt) || /^R\$\s*copiar/i.test(n) || /^MOEDA/i.test(n)) {{
                if (!currencyLayer) currencyLayer = tl;
            }}
            // Unidade (UN, KG, LT, CX, etc.)
            else if (/^(UN|KG|LT|CX|PCT|G|ML|PC)$/i.test(txtUpper) || /^(UNIDADE|MEDIDA)$/i.test(n)) {{
                if (!unitLayer) unitLayer = tl;
            }}
            else {{
                remainingTextLayers.push(tl);
            }}
        }}

        // 4. IDENTIFICAÇÃO ESPACIAL DE INTEIRO E CENTAVOS (BASEADA EM COORDENADAS X)
        // No layout de supermercado:
        // - A descrição é a camada de texto mais larga/com texto longo
        // - Os 2 números de preço ficam à direita da moeda R$
        // - O INTEIRO fica sempre à ESQUERDA (menor X)
        // - Os CENTAVOS ficam sempre à DIREITA (maior X)
        var descLayer = null;
        var priceNumberLayers = [];

        // Filtra a descrição: procura por palavra-chave ou camada com texto mais longo
        for (var r = 0; r < remainingTextLayers.length; r++) {{
            var n = remainingTextLayers[r].name.toUpperCase();
            if (/DESCRI|NOME|PRODUTO|TITULO|TEXTO/i.test(n)) {{
                descLayer = remainingTextLayers[r];
                break;
            }}
        }}

        if (!descLayer) {{
            // Entre as camadas restantes, a que tiver maior largura/comprimento de texto é a descrição
            var maxLen = -1;
            var descIdx = -1;
            for (var r = 0; r < remainingTextLayers.length; r++) {{
                var t = '';
                try {{ t = remainingTextLayers[r].textItem.contents; }} catch(e) {{}}
                // Camadas de dígitos de preço costumam ter poucos caracteres (1 a 4)
                if (t.length > maxLen && t.length > 4) {{
                    maxLen = t.length;
                    descIdx = r;
                }}
            }}
            if (descIdx >= 0) {{
                descLayer = remainingTextLayers[descIdx];
            }}
        }}

        // As camadas restantes que não são a descrição são os números do preço
        for (var r = 0; r < remainingTextLayers.length; r++) {{
            if (remainingTextLayers[r] !== descLayer) {{
                priceNumberLayers.push(remainingTextLayers[r]);
            }}
        }}

        var inteiroLayer = null;
        var centavosLayer = null;

        if (priceNumberLayers.length >= 2) {{
            // ORDENAÇÃO ESPACIAL HORIZONTAL: Menor bounds[0] = Inteiro, Maior bounds[0] = Centavos
            priceNumberLayers.sort(function(a, b) {{
                var xA = a.bounds[0].as('px');
                var xB = b.bounds[0].as('px');
                return xA - xB;
            }});
            inteiroLayer = priceNumberLayers[0]; // À esquerda: INTEIRO
            centavosLayer = priceNumberLayers[1]; // À direita: CENTAVOS
        }} else if (priceNumberLayers.length === 1) {{
            // Se só existir uma camada numérica, verifica se é inteiro ou preço único
            inteiroLayer = priceNumberLayers[0];
        }}

        // 5. APLICAÇÃO DOS PREÇOS (100% SEPARADA E SEM DUPLICAÇÃO)
        if (offerDe && precoDeLayer) {{
            try {{ precoDeLayer.textItem.contents = offerDe; }} catch(e) {{}}
        }}

        if (offerInteiro && inteiroLayer) {{
            try {{ inteiroLayer.textItem.contents = offerInteiro; }} catch(e) {{}}
        }}

        if (offerCentavos && centavosLayer) {{
            try {{ centavosLayer.textItem.contents = offerCentavos; }} catch(e) {{}}
        }}

        if (offerUnidade && unitLayer) {{
            try {{ unitLayer.textItem.contents = offerUnidade; }} catch(e) {{}}
        }}

        // A camada 'R$' permanece intacta como símbolo de moeda!

        // 6. ATUALIZAÇÃO DA DESCRIÇÃO (BLINDADA)
        var descUpdated = false;
        if (descLayer && offerNome) {{
            try {{
                var ti = descLayer.textItem;
                var origBounds = descLayer.bounds;
                var origW = Math.abs(origBounds[2].as('px') - origBounds[0].as('px'));

                ti.contents = offerNome;
                descUpdated = true;

                // Quebra sob demanda para evitar colisão
                var words = offerNome.split(' ');
                var newBounds = descLayer.bounds;
                var newW = Math.abs(newBounds[2].as('px') - newBounds[0].as('px'));

                if (origW > 30 && newW > origW * 1.15) {{
                    if (words.length >= 3) {{
                        ti.contents = words[0] + ' ' + words[1] + '\r' + words.slice(2).join(' ');
                    }} else if (words.length >= 2) {{
                        ti.contents = words[0] + '\r' + words.slice(1).join(' ');
                    }}
                }}
            }} catch(e) {{
                try {{ descLayer.textItem.contents = offerNome; descUpdated = true; }} catch(e2) {{}}
            }}
        }}

        // 7. ATUALIZAÇÃO DA IMAGEM / SMART OBJECT
        var imgUpdated = false;
        if (imagePath) {{
            var imgFile = new File(imagePath);
            if (imgFile.exists && smartObjects.length > 0) {{
                var maxArea = 0;
                var targetSO = null;
                for (var s = 0; s < smartObjects.length; s++) {{
                    try {{
                        var b = smartObjects[s].bounds;
                        var area = Math.abs(b[2].as('px') - b[0].as('px')) * Math.abs(b[3].as('px') - b[1].as('px'));
                        if (area > maxArea) {{
                            maxArea = area;
                            targetSO = smartObjects[s];
                        }}
                    }} catch(e) {{}}
                }}

                if (targetSO) {{
                    try {{
                        var origBounds = targetSO.bounds;
                        var targetW = Math.abs(origBounds[2].as('px') - origBounds[0].as('px'));
                        var targetH = Math.abs(origBounds[3].as('px') - origBounds[1].as('px'));
                        var targetCX = (origBounds[0].as('px') + origBounds[2].as('px')) / 2;
                        var targetCY = (origBounds[1].as('px') + origBounds[3].as('px')) / 2;

                        doc.activeLayer = targetSO;

                        var desc = new ActionDescriptor();
                        desc.putPath(charIDToTypeID('null'), imgFile);
                        executeAction(stringIDToTypeID('placedLayerReplaceContents'), desc, DialogModes.NO);

                        var nb = targetSO.bounds;
                        var curW = Math.abs(nb[2].as('px') - nb[0].as('px'));
                        var curH = Math.abs(nb[3].as('px') - nb[1].as('px'));
                        if (curW > 0 && curH > 0 && targetW > 0 && targetH > 0) {{
                            var scaleX = Math.abs(targetW / curW) * 100;
                            var scaleY = Math.abs(targetH / curH) * 100;
                            var scale = Math.abs(Math.min(scaleX, scaleY));
                            if (Math.abs(scale - 100) > 2) {{
                                targetSO.resize(scale, scale, AnchorPosition.MIDDLECENTER);
                            }}
                            nb = targetSO.bounds;
                            var curCX = (nb[0].as('px') + nb[2].as('px')) / 2;
                            var curCY = (nb[1].as('px') + nb[3].as('px')) / 2;
                            targetSO.translate(new UnitValue(targetCX - curCX, 'px'), new UnitValue(targetCY - curCY, 'px'));
                        }}
                        imgUpdated = true;
                    }} catch(soEx) {{}}
                }}
            }}
        }}

        // 8. LIMPA SELEÇÃO E ALÇAS DE TRANSFORMAÇÃO LIVRE (Ctrl+T)
        try {{ doc.selection.deselect(); }} catch(e) {{}}
        try {{
            if (doc.layers.length > 0) {{
                doc.activeLayer = doc.layers[doc.layers.length - 1];
            }}
        }} catch(e) {{}}

        return JSON.stringify({{
            success: true,
            slot: slotIndex,
            groupFound: slotGroup.name,
            descUpdated: descUpdated,
            inteiroUpdated: !!inteiroLayer,
            centavosUpdated: !!centavosLayer,
            imgUpdated: imgUpdated
        }});
    }} catch(globalEx) {{
        return JSON.stringify({{ success: false, error: globalEx.toString() }});
    }}
}})();
";
        }

        public void ExportJpeg(string outputPath, int quality = 90)
        {
            if (_activeDoc == null)
            {
                throw new InvalidOperationException("Nenhum documento ativo no Photoshop para exportar.");
            }

            string? dir = Path.GetDirectoryName(outputPath);
            if (!string.IsNullOrEmpty(dir) && !Directory.Exists(dir))
            {
                Directory.CreateDirectory(dir);
            }

            string script = $@"
(function() {{
    try {{
        var doc = app.activeDocument;

        // 1. Desmarca qualquer seleção ativa
        try {{ doc.selection.deselect(); }} catch(e) {{}}

        // 2. Remove o foco de Smart Objects para ocultar quadradinhos/alças de transformação
        try {{
            if (doc.layers.length > 0) {{
                doc.activeLayer = doc.layers[doc.layers.length - 1];
            }}
        }} catch(e) {{}}

        var file = new File('{outputPath.Replace("\\", "/")}');
        var opt = new JPEGSaveOptions();
        opt.quality = {Math.Clamp((int)Math.Round(quality / 100.0 * 12.0), 1, 12)};
        doc.saveAs(file, opt, true);
        return 'OK';
    }} catch(e) {{
        return e.toString();
    }}
}})();
";
            try
            {
                _photoshopApp.DoJavaScript(script);
            }
            catch
            {
                try
                {
                    Type? saveOptionsType = Type.GetTypeFromProgID("Photoshop.JPEGSaveOptions");
                    if (saveOptionsType != null)
                    {
                        dynamic jpegOptions = Activator.CreateInstance(saveOptionsType)!;
                        jpegOptions.Quality = Math.Clamp((int)Math.Round(quality / 100.0 * 12.0), 1, 12);
                        _activeDoc.SaveAs(outputPath, jpegOptions, true);
                        return;
                    }
                }
                catch { }
                _activeDoc.SaveAs(outputPath);
            }
        }

        private static string EscapeJs(string? text)
        {
            if (text == null) return "null";
            return "\"" + text
                .Replace("\\", "\\\\")
                .Replace("\"", "\\\"")
                .Replace("\r", "\\r")
                .Replace("\n", "\\n") + "\"";
        }
    }
}