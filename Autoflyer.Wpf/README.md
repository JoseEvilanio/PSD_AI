# Autoflyer (.NET 8.0 WPF)

Aplicação desktop nativa Windows em C# e WPF para automação completa de encartes de supermercado no Adobe Photoshop.

## Arquitetura (MVVM)

- **`Models/OfferItem.cs`**: Objeto de dados com `INotifyPropertyChanged` para suporte à edição em tempo real no `DataGrid`.
- **`Services/PhotoshopService.cs`**: Automação COM (Late-Binding) com Adobe Photoshop:
  - Substituição de Smart Objects.
  - Atualização dos valores inteiros e centavos.
  - Algoritmo tipográfico de quebra de linha sob demanda (Tentativa 1: Sem quebra -> Tentativa 2: Quebra após 2º espaço -> Tentativa 3: Quebra após 1º espaço).
- **`Services/DataLoaderService.cs`**: Leitura de planilhas Excel (`EPPlus`) e CSV (`CsvHelper`):
  - Mapeamento estrito de colunas (`nome` > `produto` > `titulo` > `descricao`).
  - Bloqueio de falsos positivos e conflitos de marcas (ex: `Moça` vs `Mococa`).
- **`Services/OllamaService.cs`**: Integração com API local do Ollama (`http://localhost:11434`) com temperatura `0.0` e prompt estrito focado em correção ortográfica sem alucinações.
- **`ViewModels/MainViewModel.cs`**: Gestão de estado, comandos assíncronos e orquestração.
- **`Views/PhotoshopLoadingOverlay.xaml`**: Overlay animado no Canvas simulando a ferramenta Ctrl + T do Photoshop (*marching ants*, alças pulsantes e vetor rotativo).
- **`Views/MainWindow.xaml`**: Tela principal em Dark Theme com `DataGrid` editável e ações de processamento.

## Como Executar

### Pré-requisitos
- .NET 8.0 SDK para Windows (Desktop Runtime / WPF)
- Adobe Photoshop (versão CS6 ou qualquer versão CC) instalado no Windows

### Compilação e Execução via Terminal
```powershell
cd Autoflyer.Wpf
dotnet restore
dotnet build
dotnet run
```
Ou abra o projeto diretamente no Visual Studio 2022 (`Autoflyer.Wpf.csproj`).
