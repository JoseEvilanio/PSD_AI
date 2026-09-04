using System;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using System.Windows.Shapes;
using System.Windows.Threading;

namespace Autoflyer.Wpf.Views
{
    /// <summary>
    /// Code-behind da animação vetorial do Photoshop (Ctrl + T / Marching Ants / Rotação).
    /// </summary>
    public partial class PhotoshopLoadingOverlay : UserControl
    {
        private readonly DispatcherTimer _timer;
        private double _rotationAngle = 0;
        private double _dashOffset = 0;
        private double _pulseScale = 1.0;
        private double _pulseDirection = 1.0;

        private readonly SolidColorBrush _accentBrush = new SolidColorBrush(Color.FromRgb(0, 122, 204)); // #007ACC
        private readonly SolidColorBrush _whiteBrush = new SolidColorBrush(Colors.White);
        private readonly SolidColorBrush _blackBrush = new SolidColorBrush(Colors.Black);
        private readonly SolidColorBrush _cyanBrush = new SolidColorBrush(Color.FromRgb(79, 172, 254));

        public PhotoshopLoadingOverlay()
        {
            InitializeComponent();

            _timer = new DispatcherTimer(DispatcherPriority.Render)
            {
                Interval = TimeSpan.FromMilliseconds(25) // ~40 FPS suave
            };
            _timer.Tick += (s, e) => RenderFrame();

            IsVisibleChanged += (s, e) =>
            {
                if (IsVisible)
                    _timer.Start();
                else
                    _timer.Stop();
            };
        }

        private void RenderFrame()
        {
            if (AnimCanvas.ActualWidth <= 0 || AnimCanvas.ActualHeight <= 0)
                return;

            AnimCanvas.Children.Clear();

            double centerX = AnimCanvas.ActualWidth / 2.0;
            double centerY = AnimCanvas.ActualHeight / 2.0;

            // 1. Dimensões da Caixa de Seleção Ctrl + T com pulso suave
            double boxWidth = 160.0 * _pulseScale;
            double boxHeight = 100.0 * _pulseScale;
            double x1 = centerX - boxWidth / 2.0;
            double y1 = centerY - boxHeight / 2.0;

            _dashOffset = (_dashOffset + 0.5) % 8;

            // Fundo da Seleção Tracejada (Branco)
            var rectWhite = new Rectangle
            {
                Width = boxWidth,
                Height = boxHeight,
                Stroke = _whiteBrush,
                StrokeThickness = 1,
                StrokeDashArray = new DoubleCollection { 4, 4 },
                StrokeDashOffset = _dashOffset
            };
            Canvas.SetLeft(rectWhite, x1);
            Canvas.SetTop(rectWhite, y1);
            AnimCanvas.Children.Add(rectWhite);

            // Frente da Seleção Tracejada (Preto) com contraste
            var rectBlack = new Rectangle
            {
                Width = boxWidth,
                Height = boxHeight,
                Stroke = _blackBrush,
                StrokeThickness = 1,
                StrokeDashArray = new DoubleCollection { 4, 4 },
                StrokeDashOffset = (_dashOffset + 4) % 8
            };
            Canvas.SetLeft(rectBlack, x1);
            Canvas.SetTop(rectBlack, y1);
            AnimCanvas.Children.Add(rectBlack);

            // 2. Alças de Controle (Anchor Points nos cantos e pontos médios)
            double x2 = centerX + boxWidth / 2.0;
            double y2 = centerY + boxHeight / 2.0;
            double handleSize = 6.0;

            Point[] handlePoints = new[]
            {
                new Point(x1, y1), new Point(x2, y1), new Point(x1, y2), new Point(x2, y2), // Cantos
                new Point(centerX, y1), new Point(centerX, y2), new Point(x1, centerY), new Point(x2, centerY) // Médios
            };

            foreach (var pt in handlePoints)
            {
                var handle = new Rectangle
                {
                    Width = handleSize,
                    Height = handleSize,
                    Fill = _whiteBrush,
                    Stroke = _accentBrush,
                    StrokeThickness = 1.5
                };
                Canvas.SetLeft(handle, pt.X - handleSize / 2.0);
                Canvas.SetTop(handle, pt.Y - handleSize / 2.0);
                AnimCanvas.Children.Add(handle);
            }

            // 3. Vetor Giratório do Cursor / Renderização
            double spinnerRadius = 26.0;
            int numPoints = 8;
            for (int i = 0; i < numPoints; i++)
            {
                double angleDeg = _rotationAngle + (i * (360.0 / numPoints));
                double angleRad = angleDeg * Math.PI / 180.0;
                double px = centerX + spinnerRadius * Math.Cos(angleRad);
                double py = centerY + spinnerRadius * Math.Sin(angleRad);

                double pointSize = 2.0 + (i * 0.7);
                Brush ptBrush = i == numPoints - 1 ? _accentBrush : (i >= 4 ? _cyanBrush : new SolidColorBrush(Color.FromRgb(80, 80, 80)));

                var dot = new Ellipse
                {
                    Width = pointSize * 2,
                    Height = pointSize * 2,
                    Fill = ptBrush
                };
                Canvas.SetLeft(dot, px - pointSize);
                Canvas.SetTop(dot, py - pointSize);
                AnimCanvas.Children.Add(dot);
            }

            // 4. Pivô de Ancoragem Central (Mira com retículo)
            var pivot = new Ellipse
            {
                Width = 10,
                Height = 10,
                Stroke = _accentBrush,
                StrokeThickness = 1.5
            };
            Canvas.SetLeft(pivot, centerX - 5);
            Canvas.SetTop(pivot, centerY - 5);
            AnimCanvas.Children.Add(pivot);

            var lineH = new Line
            {
                X1 = centerX - 8,
                Y1 = centerY,
                X2 = centerX + 8,
                Y2 = centerY,
                Stroke = _accentBrush,
                StrokeThickness = 1.2
            };
            AnimCanvas.Children.Add(lineH);

            var lineV = new Line
            {
                X1 = centerX,
                Y1 = centerY - 8,
                X2 = centerX,
                Y2 = centerY + 8,
                Stroke = _accentBrush,
                StrokeThickness = 1.2
            };
            AnimCanvas.Children.Add(lineV);

            // 5. Atualização de parâmetros para o próximo frame
            _rotationAngle = (_rotationAngle + 6.0) % 360.0;
            _pulseScale += 0.003 * _pulseDirection;
            if (_pulseScale >= 1.04) _pulseDirection = -1.0;
            else if (_pulseScale <= 0.96) _pulseDirection = 1.0;
        }
    }
}
