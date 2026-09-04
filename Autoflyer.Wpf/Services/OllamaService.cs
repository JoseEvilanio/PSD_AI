using System;
using System.Net.Http;
using System.Text;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;

namespace Autoflyer.Wpf.Services
{
    /// <summary>
    /// Serviço de integração com o Ollama para correção ortográfica estrita e sem alucinações.
    /// </summary>
    public class OllamaService
    {
        private readonly HttpClient _httpClient;
        public string Host { get; set; } = "http://localhost:11434";
        public string Model { get; set; } = "llama3.2";
        public bool Enabled { get; set; } = true;

        private const string SystemPrompt =
            "Você é um corretor ortográfico e gramatical de língua portuguesa extremamente rigoroso.\n" +
            "Sua ÚNICA tarefa é corrigir erros de português, digitação, acentuação ou ortografia do texto enviado.\n" +
            "REGRAS ABSOLUTAS:\n" +
            "1. Retorne APENAS o texto corrigido, sem aspas, explicações, introduções ou comentários.\n" +
            "2. NUNCA adicione palavras novas, adjetivos, marcas ou slogans que não estejam no texto original.\n" +
            "3. NUNCA responda com textos conversacionais (ex: 'Aqui estão', 'Segue a correção', 'Opção corrigida').\n" +
            "4. NUNCA traduza marcas comerciais, nomes próprios ou termos estrangeiros consagrados (ex: 'Above' deve continuar 'Above' e NUNCA ser traduzido para 'Acima'; 'Soya' deve continuar 'Soya'; 'Downy' deve continuar 'Downy'; 'Colgate' deve continuar 'Colgate').\n" +
            "5. Se o texto original já estiver correto, retorne exatamente o mesmo texto recebido, caractere por caractere.\n" +
            "Exemplo de entrada: 'Arros tpo 1 Camil'\n" +
            "Exemplo de saída: 'Arroz Tipo 1 Camil'";

        public OllamaService(HttpClient? httpClient = null)
        {
            _httpClient = httpClient ?? new HttpClient { Timeout = TimeSpan.FromSeconds(15) };
        }

        /// <summary>
        /// Verifica se a instância local do Ollama está respondendo.
        /// </summary>
        public async Task<bool> CheckAvailabilityAsync()
        {
            if (!Enabled) return false;
            try
            {
                var response = await _httpClient.GetAsync($"{Host.TrimEnd('/')}/api/tags");
                return response.IsSuccessStatusCode;
            }
            catch
            {
                return false;
            }
        }

        /// <summary>
        /// Executa a correção ortográfica estrita do nome do produto com fallback seguro.
        /// </summary>
        public async Task<string> CorrigirNomeProdutoAsync(string nomeOriginal, CancellationToken ct = default)
        {
            if (!Enabled || string.IsNullOrWhiteSpace(nomeOriginal))
                return nomeOriginal;

            try
            {
                var payload = new
                {
                    model = Model,
                    prompt = $"Corrija apenas se houver erros de português: {nomeOriginal}",
                    system = SystemPrompt,
                    stream = false,
                    options = new
                    {
                        temperature = 0.0 // Garante determinismo total e zero invenção
                    }
                };

                string json = JsonSerializer.Serialize(payload);
                using var content = new StringContent(json, Encoding.UTF8, "application/json");

                var response = await _httpClient.PostAsync($"{Host.TrimEnd('/')}/api/generate", content, ct);
                if (!response.IsSuccessStatusCode)
                    return nomeOriginal;

                string responseBody = await response.Content.ReadAsStringAsync(ct);
                using var doc = JsonDocument.Parse(responseBody);

                if (doc.RootElement.TryGetProperty("response", out var respProp))
                {
                    string textoCorrigido = respProp.GetString()?.Trim().Trim('"', '\'', '\r', '\n') ?? string.Empty;

                    // Proteção contra alucinação conversacional ou respostas longas
                    if (!string.IsNullOrWhiteSpace(textoCorrigido) && textoCorrigido.Length <= nomeOriginal.Length * 1.3)
                    {
                        string lower = textoCorrigido.ToLowerInvariant();
                        if (!lower.StartsWith("aqui ") &&
                            !lower.StartsWith("opç") &&
                            !lower.StartsWith("sugest") &&
                            !lower.StartsWith("claro") &&
                            !lower.StartsWith("segue") &&
                            !lower.StartsWith("título") &&
                            !lower.StartsWith("nome:"))
                        {
                            return textoCorrigido;
                        }
                    }
                }
            }
            catch
            {
                // Fallback silencioso e seguro para manter o fluxo sem travamentos
            }

            return nomeOriginal;
        }
    }
}
