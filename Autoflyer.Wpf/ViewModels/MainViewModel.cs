using System;
using System.Collections.ObjectModel;
using System.ComponentModel;
using System.IO;
using System.Runtime.CompilerServices;
using System.Threading.Tasks;
using System.Windows.Input;
using Autoflyer.Wpf.Models;
using Autoflyer.Wpf.Services;
using Microsoft.Win32;

namespace Autoflyer.Wpf.ViewModels
{
    /// <summary>
    /// ViewModel principal gerenciando o estado da interface, comandos e orquestração assíncrona.
    /// </summary>
    public class MainViewModel : INotifyPropertyChanged
    {
        private readonly DataLoaderService _dataLoader;
        private readonly PhotoshopService _photoshop;
        private readonly OllamaService _ollama;

        private string? _templatePath;
        private string? _spreadsheetPath;
        private string? _imagesDirPath;
        private string _outputDir = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "outputs");

        private bool _isBusy;
        private string _loadingStage = "Iniciando processamento...";
        private string _statusMessage = "Pronto para carregar planilha.";
        private bool _useAiCorrection = true;

        public event PropertyChangedEventHandler? PropertyChanged;

        public ObservableCollection<OfferItem> Offers { get; } = new();

        public string? TemplatePath
        {
            get => _templatePath;
            set { if (_templatePath != value) { _templatePath = value; OnPropertyChanged(); } }
        }

        public string? SpreadsheetPath
        {
            get => _spreadsheetPath;
            set { if (_spreadsheetPath != value) { _spreadsheetPath = value; OnPropertyChanged(); } }
        }

        public string? ImagesDirPath
        {
            get => _imagesDirPath;
            set { if (_imagesDirPath != value) { _imagesDirPath = value; OnPropertyChanged(); } }
        }

        public string OutputDir
        {
            get => _outputDir;
            set { if (_outputDir != value) { _outputDir = value; OnPropertyChanged(); } }
        }

        public bool IsBusy
        {
            get => _isBusy;
            set { if (_isBusy != value) { _isBusy = value; OnPropertyChanged(); } }
        }

        public string LoadingStage
        {
            get => _loadingStage;
            set { if (_loadingStage != value) { _loadingStage = value; OnPropertyChanged(); } }
        }

        public string StatusMessage
        {
            get => _statusMessage;
            set { if (_statusMessage != value) { _statusMessage = value; OnPropertyChanged(); } }
        }

        public bool UseAiCorrection
        {
            get => _useAiCorrection;
            set { if (_useAiCorrection != value) { _useAiCorrection = value; OnPropertyChanged(); } }
        }

        public ICommand BrowseTemplateCommand { get; }
        public ICommand BrowseSpreadsheetCommand { get; }
        public ICommand BrowseImagesDirCommand { get; }
        public ICommand LoadSpreadsheetCommand { get; }
        public ICommand CorrectGrammarCommand { get; }
        public ICommand GenerateFlyerCommand { get; }

        public MainViewModel()
        {
            _dataLoader = new DataLoaderService();
            _photoshop = new PhotoshopService();
            _ollama = new OllamaService();

            BrowseTemplateCommand = new RelayCommand(BrowseTemplate);
            BrowseSpreadsheetCommand = new RelayCommand(BrowseSpreadsheet);
            BrowseImagesDirCommand = new RelayCommand(BrowseImagesDir);
            LoadSpreadsheetCommand = new RelayCommand(async () => await LoadSpreadsheetAsync());
            CorrectGrammarCommand = new RelayCommand(async () => await CorrectGrammarAsync(), () => Offers.Count > 0 && !IsBusy);
            GenerateFlyerCommand = new RelayCommand(async () => await GenerateFlyerAsync(), () => Offers.Count > 0 && !string.IsNullOrEmpty(TemplatePath) && !IsBusy);

            // Detecção padrão de caminhos conhecidos
            DetectDefaultPaths();
        }

        private void DetectDefaultPaths()
        {
            string baseDir = AppDomain.CurrentDomain.BaseDirectory;
            string defaultPsd = Path.Combine(baseDir, "arquivo.psd");
            if (Directory.Exists(defaultPsd))
            {
                var files = Directory.GetFiles(defaultPsd, "*.psd");
                if (files.Length > 0) TemplatePath = files[0];
            }

            if (Directory.Exists(@"F:\PRODUTO"))
            {
                ImagesDirPath = @"F:\PRODUTO";
            }
        }

        private void BrowseTemplate()
        {
            var dialog = new OpenFileDialog
            {
                Title = "Selecione o Template PSD",
                Filter = "Arquivos Photoshop (*.psd;*.psb)|*.psd;*.psb|Todos os Arquivos (*.*)|*.*"
            };
            if (dialog.ShowDialog() == true)
            {
                TemplatePath = dialog.FileName;
                StatusMessage = $"Template selecionado: {Path.GetFileName(TemplatePath)}";
            }
        }

        private void BrowseSpreadsheet()
        {
            var dialog = new OpenFileDialog
            {
                Title = "Selecione a Planilha de Ofertas",
                Filter = "Planilhas (*.xlsx;*.csv)|*.xlsx;*.csv|Excel (*.xlsx)|*.xlsx|CSV (*.csv)|*.csv"
            };
            if (dialog.ShowDialog() == true)
            {
                SpreadsheetPath = dialog.FileName;
                StatusMessage = $"Planilha selecionada: {Path.GetFileName(SpreadsheetPath)}";
            }
        }

        private void BrowseImagesDir()
        {
            var dialog = new OpenFolderDialog
            {
                Title = "Selecione a Pasta de Imagens dos Produtos"
            };
            if (dialog.ShowDialog() == true)
            {
                ImagesDirPath = dialog.FolderName;
                StatusMessage = $"Pasta de imagens: {ImagesDirPath}";
            }
        }

        public async Task LoadSpreadsheetAsync()
        {
            if (string.IsNullOrEmpty(SpreadsheetPath) || !File.Exists(SpreadsheetPath))
            {
                StatusMessage = "Selecione um arquivo de planilha válido.";
                return;
            }

            IsBusy = true;
            LoadingStage = "Lendo e mapeando planilha de ofertas...";

            try
            {
                var loaded = await Task.Run(() => _dataLoader.LoadOffers(SpreadsheetPath, ImagesDirPath));
                Offers.Clear();
                foreach (var item in loaded)
                {
                    Offers.Add(item);
                }
                StatusMessage = $"{Offers.Count} ofertas carregadas com sucesso. Células prontas para edição.";
            }
            catch (Exception ex)
            {
                StatusMessage = $"Erro ao carregar planilha: {ex.Message}";
            }
            finally
            {
                IsBusy = false;
            }
        }

        public async Task CorrectGrammarAsync()
        {
            if (Offers.Count == 0) return;

            IsBusy = true;
            LoadingStage = "Conectando ao Ollama para correção ortográfica...";

            try
            {
                for (int i = 0; i < Offers.Count; i++)
                {
                    var offer = Offers[i];
                    LoadingStage = $"Corrigindo ortografia ({i + 1}/{Offers.Count}): {offer.Nome}";
                    string corrigido = await _ollama.CorrigirNomeProdutoAsync(offer.Nome);
                    offer.Nome = corrigido;
                }
                StatusMessage = "Correção ortográfica concluída.";
            }
            catch (Exception ex)
            {
                StatusMessage = $"Falha na correção: {ex.Message}";
            }
            finally
            {
                IsBusy = false;
            }
        }

        public async Task GenerateFlyerAsync()
        {
            if (string.IsNullOrEmpty(TemplatePath) || Offers.Count == 0)
            {
                StatusMessage = "Selecione o template e carregue ofertas antes de gerar.";
                return;
            }

            IsBusy = true;

            try
            {
                // 1. Correção ortográfica prévia se ativada
                if (UseAiCorrection)
                {
                    LoadingStage = "Otimizando nomes com IA (Ollama)...";
                    for (int i = 0; i < Offers.Count; i++)
                    {
                        var offer = Offers[i];
                        offer.Nome = await _ollama.CorrigirNomeProdutoAsync(offer.Nome);
                    }
                }

                // 2. Automação no Photoshop em thread secundária
                await Task.Run(() =>
                {
                    LoadingStage = "Iniciando o Motor do Adobe Photoshop...";
                    if (!_photoshop.Connect())
                        throw new InvalidOperationException("Não foi possível conectar ao Adobe Photoshop.");

                    LoadingStage = "Abrindo Template PSD...";
                    if (!_photoshop.OpenTemplate(TemplatePath))
                        throw new InvalidOperationException("Não foi possível abrir o template PSD.");

                    for (int i = 0; i < Offers.Count; i++)
                    {
                        var offer = Offers[i];
                        LoadingStage = $"Inserindo Oferta Slot {offer.Slot}: {offer.Nome}";
                        _photoshop.UpdateOfferSlot(offer, offer.Slot);
                    }

                    LoadingStage = "Exportando arte final em alta resolução...";
                    Directory.CreateDirectory(OutputDir);
                    string fileName = $"{Path.GetFileNameWithoutExtension(TemplatePath)}_gerado.jpg";
                    string finalPath = Path.Combine(OutputDir, fileName);
                    _photoshop.ExportJpeg(finalPath, 90);

                    StatusMessage = $"Encarte gerado com sucesso: {finalPath}";
                });
            }
            catch (Exception ex)
            {
                StatusMessage = $"Erro durante a geração: {ex.Message}";
            }
            finally
            {
                IsBusy = false;
            }
        }

        protected void OnPropertyChanged([CallerMemberName] string? propertyName = null)
        {
            PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(propertyName));
        }
    }
}
