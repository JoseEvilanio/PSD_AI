using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Text;
using System.Text.RegularExpressions;
using Autoflyer.Wpf.Models;
using OfficeOpenXml;

namespace Autoflyer.Wpf.Services
{
    /// <summary>
    /// Serviço de carregamento e higienização de dados de planilhas Excel e CSV.
    /// Implementa regras de prioridade de colunas e prevenção de falso positivo em imagens.
    /// </summary>
    public class DataLoaderService
    {
        static DataLoaderService()
        {
            // Configuração de licença não-comercial para o EPPlus 7
            ExcelPackage.LicenseContext = LicenseContext.NonCommercial;
        }

        // Mapeamento com hierarquia estrita de prioridades
        private static readonly string[] PrioridadeNome = new[] { "nome", "produto", "titulo", "descricao" };
        private static readonly string[] PrioridadePrecoDe = new[] { "preco_de", "preco_original", "de", "precode", "valor_de" };
        private static readonly string[] PrioridadePrecoPor = new[] { "preco_por", "por", "preco_promocional", "preco", "valor_por", "valor" };
        private static readonly string[] PrioridadeImagem = new[] { "imagem", "foto", "img", "arquivo_imagem", "foto_produto" };
        private static readonly string[] PrioridadeSlot = new[] { "slot", "posicao", "item", "numero", "ordem" };
        private static readonly string[] PrioridadeUnidade = new[] { "unidade", "un", "medida", "tipo_unidade" };

        // Lista de marcas conhecidas que geram falsos positivos por substring
        private static readonly (string Termo1, string Termo2)[] ConflitosConhecidos = new[]
        {
            ("moca", "mococa"),
            ("omo", "comfort"),
            ("soya", "liza"),
            ("camil", "tio joao"),
            ("kicaldo", "camil")
        };

        /// <summary>
        /// Carrega e converte os dados da planilha para a lista de OfferItem.
        /// </summary>
        public List<OfferItem> LoadOffers(string filePath, string? imagesDirectory = null)
        {
            if (!File.Exists(filePath))
                throw new FileNotFoundException("Arquivo de planilha não encontrado.", filePath);

            string ext = Path.GetExtension(filePath).ToLowerInvariant();
            List<Dictionary<string, string>> rawRows;

            if (ext == ".xlsx" || ext == ".xls")
            {
                rawRows = ReadExcel(filePath);
            }
            else
            {
                rawRows = ReadCsv(filePath);
            }

            var offers = new List<OfferItem>();
            int autoSlot = 1;

            foreach (var row in rawRows)
            {
                string nome = GetPrioritizedValue(row, PrioridadeNome);
                if (string.IsNullOrWhiteSpace(nome))
                    continue; // Pula linhas sem descrição/nome

                string slotStr = GetPrioritizedValue(row, PrioridadeSlot);
                int slot = int.TryParse(slotStr, out int s) ? s : autoSlot;

                string precoDeStr = GetPrioritizedValue(row, PrioridadePrecoDe);
                string precoPorStr = GetPrioritizedValue(row, PrioridadePrecoPor);
                string unidadeStr = GetPrioritizedValue(row, PrioridadeUnidade);
                string imagemInformada = GetPrioritizedValue(row, PrioridadeImagem);

                var item = new OfferItem
                {
                    Slot = slot,
                    Nome = nome.Trim(),
                    PrecoDe = ParsePrice(precoDeStr),
                    PrecoPor = ParsePrice(precoPorStr),
                    Unidade = string.IsNullOrWhiteSpace(unidadeStr) ? "UN" : unidadeStr.Trim().ToUpperInvariant()
                };

                // Resolução Inteligente da Imagem com Detecção de Conflitos
                ResolveImage(item, imagemInformada, imagesDirectory);

                offers.Add(item);
                autoSlot++;
            }

            return offers;
        }

        private void ResolveImage(OfferItem item, string? imagemInformada, string? imagesDirectory)
        {
            if (!string.IsNullOrWhiteSpace(imagemInformada) && File.Exists(imagemInformada))
            {
                item.ImagemPath = imagemInformada;
                return;
            }

            if (string.IsNullOrWhiteSpace(imagesDirectory) || !Directory.Exists(imagesDirectory))
                return;

            string[] searchFiles = Directory.GetFiles(imagesDirectory, "*.*", SearchOption.AllDirectories)
                .Where(f => f.EndsWith(".png", StringComparison.OrdinalIgnoreCase) ||
                            f.EndsWith(".jpg", StringComparison.OrdinalIgnoreCase) ||
                            f.EndsWith(".jpeg", StringComparison.OrdinalIgnoreCase))
                .ToArray();

            string nomeNormalizado = NormalizeText(item.Nome);
            string[] palavrasNome = nomeNormalizado.Split(new[] { ' ' }, StringSplitOptions.RemoveEmptyEntries);

            string? melhorMatch = null;
            int maxScore = 0;

            foreach (var file in searchFiles)
            {
                string fileName = Path.GetFileNameWithoutExtension(file);
                string fileNormalizado = NormalizeText(fileName);
                string[] palavrasArquivo = fileNormalizado.Split(new[] { ' ' }, StringSplitOptions.RemoveEmptyEntries);

                // Prevenção de Conflito Crítico (Ex: Moça vs Mococa)
                bool conflitoDetectado = false;
                foreach (var (t1, t2) in ConflitosConhecidos)
                {
                    bool nomeTemT1 = palavrasNome.Contains(t1);
                    bool arqTemT2 = palavrasArquivo.Contains(t2);
                    if (nomeTemT1 && arqTemT2)
                    {
                        conflitoDetectado = true;
                        item.HasImageConflict = true;
                        item.ConflictMessage = $"Conflito bloqueado: Imagem '{fileName}' contém '{t2}' para produto '{item.Nome}'.";
                        break;
                    }
                }

                if (conflitoDetectado)
                    continue;

                // Prevenção de Conflito de Embalagem (Ex: Lata vs TP / Caixa / Tetra Pak)
                bool nomeIsLata = palavrasNome.Contains("lata") || palavrasNome.Contains("latas");
                bool arqIsLata = palavrasArquivo.Contains("lata") || palavrasArquivo.Contains("latas");
                bool nomeIsCaixa = palavrasNome.Contains("tp") || palavrasNome.Contains("caixa") || palavrasNome.Contains("caixinha") || palavrasNome.Contains("tetrapak");
                bool arqIsCaixa = palavrasArquivo.Contains("tp") || palavrasArquivo.Contains("caixa") || palavrasArquivo.Contains("caixinha") || palavrasArquivo.Contains("tetrapak");

                if (nomeIsLata && arqIsCaixa)
                {
                    // Produto especifica LATA, não pode associar imagem de CAIXA/TP
                    continue;
                }

                if (nomeIsCaixa && arqIsLata)
                {
                    // Produto especifica CAIXA/TP, não pode associar imagem de LATA
                    continue;
                }

                // Contagem de correspondência de palavras inteiras
                int matchCount = palavrasNome.Count(p => palavrasArquivo.Contains(p) && p.Length > 2);

                // Bônus de correspondência exata de embalagem
                if (nomeIsLata && arqIsLata) matchCount += 3;
                if (nomeIsCaixa && arqIsCaixa) matchCount += 3;

                if (matchCount > maxScore)
                {
                    maxScore = matchCount;
                    melhorMatch = file;
                }
            }

            if (melhorMatch != null && maxScore >= 2)
            {
                item.ImagemPath = melhorMatch;
            }
        }

        private string GetPrioritizedValue(Dictionary<string, string> row, string[] priorities)
        {
            foreach (var key in priorities)
            {
                foreach (var kvp in row)
                {
                    string colNormalizada = NormalizeHeader(kvp.Key);
                    if (colNormalizada == key && !string.IsNullOrWhiteSpace(kvp.Value))
                    {
                        return kvp.Value;
                    }
                }
            }
            return string.Empty;
        }

        private double? ParsePrice(string? text)
        {
            if (string.IsNullOrWhiteSpace(text)) return null;

            string clean = Regex.Replace(text, @"[^\d,\.]", "").Trim();
            if (string.IsNullOrEmpty(clean)) return null;

            if (clean.Contains(',') && clean.Contains('.'))
            {
                clean = clean.Replace(".", "").Replace(',', '.');
            }
            else if (clean.Contains(','))
            {
                clean = clean.Replace(',', '.');
            }

            if (double.TryParse(clean, NumberStyles.Any, CultureInfo.InvariantCulture, out double val))
                return val;

            return null;
        }

        private List<Dictionary<string, string>> ReadExcel(string filePath)
        {
            var list = new List<Dictionary<string, string>>();
            using var package = new ExcelPackage(new FileInfo(filePath));
            var worksheet = package.Workbook.Worksheets.FirstOrDefault();
            if (worksheet == null || worksheet.Dimension == null) return list;

            int colCount = worksheet.Dimension.Columns;
            int rowCount = worksheet.Dimension.Rows;

            var headers = new List<string>();
            for (int col = 1; col <= colCount; col++)
            {
                headers.Add(worksheet.Cells[1, col].Text?.Trim() ?? $"Col_{col}");
            }

            for (int row = 2; row <= rowCount; row++)
            {
                var dict = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
                for (int col = 1; col <= colCount; col++)
                {
                    dict[headers[col - 1]] = worksheet.Cells[row, col].Text?.Trim() ?? string.Empty;
                }
                list.Add(dict);
            }

            return list;
        }

        private List<Dictionary<string, string>> ReadCsv(string filePath)
        {
            var list = new List<Dictionary<string, string>>();
            string[] lines = File.ReadAllLines(filePath, Encoding.UTF8);
            if (lines.Length == 0) return list;

            char delimiter = lines[0].Contains(';') ? ';' : ',';
            string[] headers = lines[0].Split(delimiter).Select(h => h.Trim('"', ' ', '\r', '\n')).ToArray();

            for (int i = 1; i < lines.Length; i++)
            {
                if (string.IsNullOrWhiteSpace(lines[i])) continue;
                string[] values = lines[i].Split(delimiter);
                var dict = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);

                for (int c = 0; c < headers.Length; c++)
                {
                    dict[headers[c]] = c < values.Length ? values[c].Trim('"', ' ', '\r', '\n') : string.Empty;
                }
                list.Add(dict);
            }

            return list;
        }

        private static string NormalizeHeader(string header)
        {
            string s = header.ToLowerInvariant().Normalize(NormalizationForm.FormD);
            var sb = new StringBuilder();
            foreach (char c in s)
            {
                if (CharUnicodeInfo.GetUnicodeCategory(c) != UnicodeCategory.NonSpacingMark)
                {
                    if (char.IsLetterOrDigit(c)) sb.Append(c);
                    else if (c == ' ' || c == '_') sb.Append('_');
                }
            }
            return sb.ToString().Trim('_');
        }

        private static string NormalizeText(string text)
        {
            string s = text.ToLowerInvariant().Normalize(NormalizationForm.FormD);
            var sb = new StringBuilder();
            foreach (char c in s)
            {
                if (CharUnicodeInfo.GetUnicodeCategory(c) != UnicodeCategory.NonSpacingMark)
                {
                    if (char.IsLetterOrDigit(c)) sb.Append(c);
                    else sb.Append(' ');
                }
            }
            return Regex.Replace(sb.ToString(), @"\s+", " ").Trim();
        }
    }
}
