using System;
using System.ComponentModel;
using System.Globalization;
using System.Runtime.CompilerServices;

namespace Autoflyer.Wpf.Models
{
    /// <summary>
    /// Representa uma oferta individual a ser inserida em um slot do template PSD.
    /// Implementa INotifyPropertyChanged para permitir edição bidirecional em tempo real no DataGrid do WPF.
    /// </summary>
    public class OfferItem : INotifyPropertyChanged
    {
        private int _slot;
        private string _nome = string.Empty;
        private double? _precoDe;
        private double? _precoPor;
        private string? _imagemPath;
        private string? _unidade = "UN";
        private string? _cada;
        private bool _hasImageConflict;
        private string? _conflictMessage;

        public event PropertyChangedEventHandler? PropertyChanged;

        public int Slot
        {
            get => _slot;
            set { if (_slot != value) { _slot = value; OnPropertyChanged(); } }
        }

        public string Nome
        {
            get => _nome;
            set { if (_nome != value) { _nome = value; OnPropertyChanged(); } }
        }

        public double? PrecoDe
        {
            get => _precoDe;
            set
            {
                if (_precoDe != value)
                {
                    _precoDe = value;
                    OnPropertyChanged();
                    OnPropertyChanged(nameof(PrecoDeFormatado));
                }
            }
        }

        public double? PrecoPor
        {
            get => _precoPor;
            set
            {
                if (_precoPor != value)
                {
                    _precoPor = value;
                    OnPropertyChanged();
                    OnPropertyChanged(nameof(PrecoPorInteiro));
                    OnPropertyChanged(nameof(PrecoPorCentavos));
                }
            }
        }

        public string? ImagemPath
        {
            get => _imagemPath;
            set { if (_imagemPath != value) { _imagemPath = value; OnPropertyChanged(); } }
        }

        public string? Unidade
        {
            get => _unidade;
            set { if (_unidade != value) { _unidade = value; OnPropertyChanged(); } }
        }

        public string? Cada
        {
            get => _cada;
            set { if (_cada != value) { _cada = value; OnPropertyChanged(); } }
        }

        public bool HasImageConflict
        {
            get => _hasImageConflict;
            set { if (_hasImageConflict != value) { _hasImageConflict = value; OnPropertyChanged(); } }
        }

        public string? ConflictMessage
        {
            get => _conflictMessage;
            set { if (_conflictMessage != value) { _conflictMessage = value; OnPropertyChanged(); } }
        }

        /// <summary>
        /// Obtém a parte inteira do preço promocional para camadas de destaque numérico (ex: "5").
        /// </summary>
        public string PrecoPorInteiro
        {
            get
            {
                if (!PrecoPor.HasValue) return string.Empty;
                return Math.Truncate(PrecoPor.Value).ToString("0", CultureInfo.InvariantCulture);
            }
        }

        /// <summary>
        /// Obtém a parte decimal do preço formatada com vírgula (ex: ",79").
        /// </summary>
        public string PrecoPorCentavos
        {
            get
            {
                if (!PrecoPor.HasValue) return string.Empty;
                int centavos = (int)Math.Round((PrecoPor.Value - Math.Truncate(PrecoPor.Value)) * 100);
                return $",{centavos:D2}";
            }
        }

        /// <summary>
        /// Formata o preço 'De' padrão de supermercado (ex: "DE;14,99" ou "DE: 14,99").
        /// </summary>
        public string PrecoDeFormatado
        {
            get
            {
                if (!PrecoDe.HasValue) return string.Empty;
                return $"DE;{PrecoDe.Value:N2}".Replace(".", ",");
            }
        }

        protected void OnPropertyChanged([CallerMemberName] string? propertyName = null)
        {
            PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(propertyName));
        }
    }
}
