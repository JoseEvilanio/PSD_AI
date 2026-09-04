#!/usr/bin/env python3
"""
PhotoshopLoadingOverlay Preview
Permite visualizar e testar o overlay temático do Photoshop de forma interativa.
"""

import sys
import tkinter as tk
from tkinter import ttk

from ui.loading_overlay import PhotoshopLoadingOverlay


def main():
    root = tk.Tk()
    root.title("Preview: Photoshop Loading Overlay")
    root.geometry("600x400")
    root.configure(bg="#2d2d2d")

    # Centraliza janela de teste na tela
    root.eval("tk::PlaceWindow . center")

    style = ttk.Style(root)
    style.theme_use("clam")

    titulo = tk.Label(
        root,
        text="Preview do Overlay de Loading (Estilo Photoshop)",
        font=("Segoe UI", 13, "bold"),
        fg="#ffffff",
        bg="#2d2d2d",
    )
    titulo.pack(pady=(40, 10))

    descricao = tk.Label(
        root,
        text=(
            "Clique no botão abaixo para disparar o overlay simulando a ferramenta\n"
            "de Transformação Livre (Ctrl + T) com formigas marchantes e vetor giratório."
        ),
        font=("Segoe UI", 9),
        fg="#aaaaaa",
        bg="#2d2d2d",
        justify="center",
    )
    descricao.pack(pady=(0, 30))

    overlay = PhotoshopLoadingOverlay(root, tema_escuro=True)

    def abrir_demo():
        overlay.iniciar("Simulando automação no Photoshop...")
        # Fecha automaticamente após 9 segundos se o usuário não fechar
        root.after(9000, lambda: overlay.fechar() if overlay.active else None)

    btn_abrir = tk.Button(
        root,
        text="▶ Iniciar Animação de Loading",
        command=abrir_demo,
        font=("Segoe UI", 11, "bold"),
        bg="#007acc",
        fg="#ffffff",
        activebackground="#005999",
        activeforeground="#ffffff",
        bd=0,
        padx=20,
        pady=10,
        cursor="hand2",
    )
    btn_abrir.pack()

    btn_fechar = tk.Button(
        root,
        text="Fechar Janela Principal",
        command=root.destroy,
        font=("Segoe UI", 9),
        bg="#3e3e42",
        fg="#cccccc",
        bd=0,
        padx=15,
        pady=6,
        cursor="hand2",
    )
    btn_fechar.pack(pady=20)

    root.mainloop()


if __name__ == "__main__":
    main()
