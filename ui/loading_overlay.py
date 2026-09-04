import math
import tkinter as tk


class PhotoshopLoadingOverlay:
    """
    Um overlay de loading moderno e altamente temático para o Autoflyer.
    Simula uma interface de transformação do Photoshop (Ctrl + T) com:
    - Linhas de seleção pontilhadas ("marching ants" / formigas marchantes)
    - Nós de controle de vetor piscantes (Anchor Points)
    - Roda de carregamento de vetor giratória
    - Textos dinâmicos baseados no estágio atual da automação
    """

    def __init__(self, parent, tema_escuro=True):
        self.parent = parent
        self.active = False

        # Paleta de cores baseada na interface clássica do Adobe Photoshop (Dark Theme)
        self.bg_color = "#1e1e1e" if tema_escuro else "#f0f0f0"
        self.accent_color = "#007acc" if tema_escuro else "#005a9e"  # Azul de seleção do PS
        self.text_color = "#e6e6e6" if tema_escuro else "#333333"
        self.border_color = "#434343" if tema_escuro else "#cccccc"

        # Variáveis de controle de animação
        self.angulo_rotacao = 0
        self.offset_pontilhado = 0
        self.direcao_pulso = 1
        self.escala_pulso = 1.0

        # Lista de mensagens criativas de status que simulam ações do Photoshop
        self.estagios = [
            "Iniciando o Motor do Photoshop...",
            "Carregando Template PSD do Encarte...",
            "Lendo Planilha de Ofertas...",
            "Resolvendo Conflitos de Imagens...",
            "Aplicando IA nas Descrições...",
            "Calculando Colisão Tipográfica...",
            "Inserindo Quebras de Linha Inteligentes...",
            "Atualizando Smart Objects de Imagens...",
            "Renderizando Sombras e Ajustando Escalas...",
            "Exportando Arte Final de Alta Qualidade...",
        ]
        self.estagio_atual_idx = 0
        self.top = None
        self.canvas = None
        self.label_status = None
        self.label_sub = None

    def iniciar(self, mensagem_inicial=None):
        """Inicia a exibição e o loop de animação do loading."""
        if self.active:
            return

        self.active = True
        self.estagio_atual_idx = 0

        # Cria uma janela Toplevel modal por cima da principal
        self.top = tk.Toplevel(self.parent)
        self.top.title("Gerando Encarte...")
        self.top.configure(bg=self.bg_color)

        # Remove bordas padrão do Windows para dar cara de Splash/Overlay profissional
        self.top.overrideredirect(True)
        self.top.attributes("-topmost", True)

        # Centraliza o overlay em relação à janela mãe
        self.parent.update_idletasks()
        p_width = self.parent.winfo_width()
        p_height = self.parent.winfo_height()
        p_x = self.parent.winfo_rootx()
        p_y = self.parent.winfo_rooty()

        # Dimensões da janela de loading
        width, height = 450, 320
        x = p_x + max(0, (p_width - width) // 2)
        y = p_y + max(0, (p_height - height) // 2)

        self.top.geometry(f"{width}x{height}+{x}+{y}")

        # Garante foco absoluto e bloqueia cliques atrás
        try:
            self.top.grab_set()
        except Exception:
            pass

        # Borda externa decorativa cinza escura
        self.frame_borda = tk.Frame(self.top, bg=self.border_color, bd=2)
        self.frame_borda.pack(fill=tk.BOTH, expand=True)

        self.content_inner = tk.Frame(self.frame_borda, bg=self.bg_color)
        self.content_inner.pack(fill=tk.BOTH, expand=True, padx=1, pady=1)

        # Canvas para animação vetorizada customizada
        self.canvas = tk.Canvas(
            self.content_inner,
            width=400,
            height=180,
            bg=self.bg_color,
            highlightthickness=0,
        )
        self.canvas.pack(pady=(20, 5))

        # Texto de Status do Processo
        texto_label = mensagem_inicial or (self.estagios[0] if self.estagios else "Processando...")
        self.label_status = tk.Label(
            self.content_inner,
            text=texto_label,
            fg=self.text_color,
            bg=self.bg_color,
            font=("Segoe UI", 11, "bold"),
            wraplength=420,
        )
        self.label_status.pack(pady=5)

        # Subtexto divertido de rodapé
        self.label_sub = tk.Label(
            self.content_inner,
            text="Por favor, não feche o Adobe Photoshop.",
            fg="#888888",
            bg=self.bg_color,
            font=("Segoe UI", 8, "italic"),
        )
        self.label_sub.pack(pady=(0, 10))

        # Inicializa o loop interno de renderização
        self._loop_animacao()
        self._loop_mensagem()

    def definir_mensagem(self, texto):
        """Permite que o orquestrador do fluxo atualize o texto manualmente."""
        if hasattr(self, "label_status") and self.label_status and self.label_status.winfo_exists():
            self.label_status.config(text=texto)

    def avancar_estagio(self):
        """Avança sequencialmente pelas etapas do Photoshop."""
        if self.estagios and self.estagio_atual_idx < len(self.estagios) - 1:
            self.estagio_atual_idx += 1
            self.definir_mensagem(self.estagios[self.estagio_atual_idx])

    def fechar(self):
        """Encerra a animação e fecha a janela modal com segurança."""
        self.active = False
        if hasattr(self, "top") and self.top and self.top.winfo_exists():
            try:
                self.top.grab_release()
            except Exception:
                pass
            try:
                self.top.destroy()
            except Exception:
                pass
            self.top = None
            self.canvas = None
            self.label_status = None

    def _loop_mensagem(self):
        """Simula a passagem automática das etapas se o workflow não atualizar manualmente."""
        if not self.active or not hasattr(self, "top") or not self.top or not self.top.winfo_exists():
            return
        self.avancar_estagio()
        # Avança a cada 2.2 segundos de forma decorativa
        self.top.after(2200, self._loop_mensagem)

    def _loop_animacao(self):
        """Loop principal de desenho vetorial no Canvas (Roda a ~40 FPS)."""
        if not self.active or not hasattr(self, "top") or not self.top or not self.top.winfo_exists():
            return
        if not hasattr(self, "canvas") or not self.canvas or not self.canvas.winfo_exists():
            return

        self.canvas.delete("all")

        # 1. ÂNCORAS DE TRANSFORMAÇÃO (A caixa de Ctrl + T do Photoshop)
        largura_box = 160 * self.escala_pulso
        altura_box = 110 * self.escala_pulso
        x1 = 200 - largura_box / 2
        y1 = 90 - altura_box / 2
        x2 = 200 + largura_box / 2
        y2 = 90 + altura_box / 2

        # Efeito "Marching Ants" (Formigas Marchantes)
        self.offset_pontilhado = (self.offset_pontilhado + 1) % 8

        # Fundo da seleção (Branco)
        self.canvas.create_rectangle(
            x1,
            y1,
            x2,
            y2,
            outline="#ffffff",
            width=1,
            dash=(4, 4),
            dashoffset=self.offset_pontilhado,
        )
        # Frente da seleção (Preto) para criar o contraste clássico piscante do Photoshop
        self.canvas.create_rectangle(
            x1,
            y1,
            x2,
            y2,
            outline="#000000",
            width=1,
            dash=(4, 4),
            dashoffset=(self.offset_pontilhado + 4) % 8,
        )

        # 2. ALÇAS DE CONTROLE (Pequenos quadradinhos azuis de transformação Ctrl+T nos cantos)
        tamanho_alca = 5
        pontos_alca = [
            (x1, y1),
            (x2, y1),
            (x1, y2),
            (x2, y2),  # Cantos
            (200, y1),
            (200, y2),
            (x1, 90),
            (x2, 90),  # Pontos médios
        ]

        for px, py in pontos_alca:
            self.canvas.create_rectangle(
                px - tamanho_alca,
                py - tamanho_alca,
                px + tamanho_alca,
                py + tamanho_alca,
                fill="#ffffff",
                outline=self.accent_color,
                width=1.5,
            )

        # 3. RODA DE CARREGAMENTO DO CURSOR (Vetor Giratório)
        centro_x, centro_y = 200, 90
        raio = 30
        num_pontos = 8

        for i in range(num_pontos):
            rad = math.radians(self.angulo_rotacao + (i * (360 / num_pontos)))
            px = centro_x + raio * math.cos(rad)
            py = centro_y + raio * math.sin(rad)

            # Efeito de rastro/fade
            tamanho_ponto = 2.0 + (i * 0.7)
            cor_ponto = self.accent_color if i == num_pontos - 1 else "#4facfe"
            if i < 4:
                cor_ponto = "#555555" if self.accent_color == "#007acc" else "#aaaaaa"

            self.canvas.create_oval(
                px - tamanho_ponto,
                py - tamanho_ponto,
                px + tamanho_ponto,
                py + tamanho_ponto,
                fill=cor_ponto,
                outline="",
            )

        # 4. ÍCONE DE VETOR CENTRAL (Simbolizando o eixo de centralização do PSD)
        self.canvas.create_oval(
            centro_x - 6,
            centro_y - 6,
            centro_x + 6,
            centro_y + 6,
            outline=self.accent_color,
            width=1.5,
        )
        self.canvas.create_line(
            centro_x - 10,
            centro_y,
            centro_x + 10,
            centro_y,
            fill=self.accent_color,
            width=1.2,
        )
        self.canvas.create_line(
            centro_x,
            centro_y - 10,
            centro_x,
            centro_y + 10,
            fill=self.accent_color,
            width=1.2,
        )

        # 5. ATUALIZAÇÃO DOS PARÂMETROS PARA O PRÓXIMO FRAME
        self.angulo_rotacao = (self.angulo_rotacao + 6) % 360

        # Pulsação suave do tamanho da caixa de transformação
        self.escala_pulso += 0.003 * self.direcao_pulso
        if self.escala_pulso >= 1.04:
            self.direcao_pulso = -1
        elif self.escala_pulso <= 0.96:
            self.direcao_pulso = 1

        self.top.after(25, self._loop_animacao)
