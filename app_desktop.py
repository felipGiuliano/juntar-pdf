# -*- coding: utf-8 -*-
r"""Juntar PDF — aplicativo de JANELA (desktop), sem navegador e sem servidor.

Cola dois ou mais PDFs um ABAIXO do outro, numa página contínua, na ordem em que
você anexar (ver juntar_pdf.py). Tudo acontece na própria máquina.

Dois modos:
  * Normal:  cola todos num documento só.
  * Repetir: o 1º documento (base) é colado com cada um dos outros e gera um PDF
             por par (1+2, 1+3, 1+4...), salvos numa pasta à sua escolha.

Roda com dois cliques (quando empacotado em .exe) ou:  python app_desktop.py
"""
from __future__ import annotations

import base64
import os
import queue
import sys
import threading
import traceback

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

import juntar_pdf

# Arrastar-e-soltar é opcional: se a biblioteca não estiver presente, o app
# continua funcionando pelo botão "Adicionar PDFs".
try:
    from tkinterdnd2 import TkinterDnD, DND_FILES
    _BASE_TK = TkinterDnD.Tk
    _TEM_DND = True
except Exception:
    _BASE_TK = tk.Tk
    _TEM_DND = False

# Prévia é opcional: se o PyMuPDF não estiver presente, mostra só o nome.
try:
    import pymupdf
    _TEM_PREVIA = True
except Exception:
    try:
        import fitz as pymupdf  # nome antigo
        _TEM_PREVIA = True
    except Exception:
        _TEM_PREVIA = False

COR_FUNDO = "#f4f6f9"
COR_CARTAO = "#ffffff"
COR_AZUL = "#1f6feb"
COR_TINTA = "#1b2430"
COR_SUAVE = "#5b6673"


class JuntarPDFApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.itens: list[dict] = []          # {path, nome, tam}
        self._preview_img = None
        self._fila = queue.Queue()

        root.title("Juntar PDF — colagem vertical")
        root.geometry("920x600")
        root.minsize(820, 520)
        root.configure(bg=COR_FUNDO)

        self._estilos()
        self._monta()
        if _TEM_DND:
            try:
                self.tree.drop_target_register(DND_FILES)
                self.tree.dnd_bind("<<Drop>>", self._ao_soltar)
            except Exception:
                pass
        self._atualiza_estado()

    # ---------- layout ----------
    def _estilos(self):
        s = ttk.Style()
        try:
            s.theme_use("clam")
        except Exception:
            pass
        s.configure("TFrame", background=COR_FUNDO)
        s.configure("Card.TFrame", background=COR_CARTAO)
        s.configure("TLabel", background=COR_FUNDO, foreground=COR_TINTA)
        s.configure("Card.TLabel", background=COR_CARTAO, foreground=COR_TINTA)
        s.configure("Suave.TLabel", background=COR_CARTAO, foreground=COR_SUAVE)
        s.configure("Titulo.TLabel", background=COR_FUNDO, foreground=COR_TINTA,
                    font=("Segoe UI", 15, "bold"))
        s.configure("TButton", font=("Segoe UI", 10))
        s.configure("Primario.TButton", font=("Segoe UI", 11, "bold"))
        s.configure("Treeview", rowheight=26, font=("Segoe UI", 10))
        s.configure("Treeview.Heading", font=("Segoe UI", 9, "bold"))

    def _monta(self):
        top = ttk.Frame(self.root, padding=(16, 12))
        top.pack(fill="x")
        ttk.Label(top, text="Juntar PDF — colagem vertical", style="Titulo.TLabel").pack(anchor="w")
        ttk.Label(top, text="Cola os documentos um abaixo do outro, na ordem em que você adicionar. "
                            "Tudo acontece nesta máquina.", style="TLabel").pack(anchor="w")

        corpo = ttk.Frame(self.root, padding=(16, 4, 16, 12))
        corpo.pack(fill="both", expand=True)
        corpo.columnconfigure(0, weight=3)
        corpo.columnconfigure(1, weight=2)
        corpo.rowconfigure(0, weight=1)

        # ----- esquerda: lista + ações -----
        esq = ttk.Frame(corpo, style="Card.TFrame", padding=12)
        esq.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        esq.rowconfigure(2, weight=1)
        esq.columnconfigure(0, weight=1)

        barra = ttk.Frame(esq, style="Card.TFrame")
        barra.grid(row=0, column=0, sticky="ew")
        ttk.Button(barra, text="➕  Adicionar PDFs", command=self.adicionar).pack(side="left")
        ttk.Button(barra, text="Limpar", command=self.limpar).pack(side="left", padx=(8, 0))
        dica = "arraste PDFs para a lista ou use o botão" if _TEM_DND else "use o botão para escolher os PDFs"
        ttk.Label(esq, text=dica, style="Suave.TLabel").grid(row=1, column=0, sticky="w", pady=(8, 4))

        quadro = ttk.Frame(esq, style="Card.TFrame")
        quadro.grid(row=2, column=0, sticky="nsew")
        quadro.rowconfigure(0, weight=1)
        quadro.columnconfigure(0, weight=1)
        self.tree = ttk.Treeview(quadro, columns=("n", "nome", "tam"), show="headings",
                                 selectmode="browse")
        self.tree.heading("n", text="#")
        self.tree.heading("nome", text="Arquivo")
        self.tree.heading("tam", text="Tamanho")
        self.tree.column("n", width=34, anchor="center", stretch=False)
        self.tree.column("nome", width=300, anchor="w")
        self.tree.column("tam", width=80, anchor="e", stretch=False)
        self.tree.grid(row=0, column=0, sticky="nsew")
        sb = ttk.Scrollbar(quadro, orient="vertical", command=self.tree.yview)
        sb.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.bind("<<TreeviewSelect>>", lambda e: self._mostra_previa())

        ordf = ttk.Frame(esq, style="Card.TFrame")
        ordf.grid(row=3, column=0, sticky="ew", pady=(8, 0))
        ttk.Button(ordf, text="▲ Subir", command=lambda: self.mover(-1)).pack(side="left")
        ttk.Button(ordf, text="▼ Descer", command=lambda: self.mover(1)).pack(side="left", padx=(8, 0))
        ttk.Button(ordf, text="Remover", command=self.remover).pack(side="left", padx=(8, 0))

        self.var_repetir = tk.BooleanVar(value=False)
        rep = ttk.Checkbutton(
            esq, variable=self.var_repetir, command=self._render,
            text="Repetir o 1º documento com cada um dos outros (gera um PDF por par)")
        rep.grid(row=4, column=0, sticky="w", pady=(10, 0))

        self.bt_juntar = ttk.Button(esq, text="Juntar PDFs", style="Primario.TButton",
                                    command=self.juntar)
        self.bt_juntar.grid(row=5, column=0, sticky="ew", pady=(10, 2), ipady=4)
        self.lb_status = ttk.Label(esq, text="", style="Suave.TLabel")
        self.lb_status.grid(row=6, column=0, sticky="w")

        # ----- direita: prévia -----
        dir_ = ttk.Frame(corpo, style="Card.TFrame", padding=12)
        dir_.grid(row=0, column=1, sticky="nsew")
        dir_.rowconfigure(1, weight=1)
        dir_.columnconfigure(0, weight=1)
        ttk.Label(dir_, text="PRÉVIA DO ITEM SELECIONADO", style="Suave.TLabel").grid(row=0, column=0, sticky="w")
        self.canvas = tk.Canvas(dir_, bg="#eef1f5", highlightthickness=1,
                                highlightbackground="#e3e8ef")
        self.canvas.grid(row=1, column=0, sticky="nsew", pady=(8, 0))
        self.canvas.bind("<Configure>", lambda e: self._mostra_previa())

    # ---------- dados ----------
    def adicionar(self):
        paths = filedialog.askopenfilenames(
            title="Escolha os PDFs", filetypes=[("Arquivos PDF", "*.pdf"), ("Todos", "*.*")])
        self._incluir(paths)

    def _ao_soltar(self, event):
        try:
            paths = self.root.tk.splitlist(event.data)
        except Exception:
            paths = [event.data]
        self._incluir(paths)

    def _incluir(self, paths):
        ignorados = []
        for p in paths:
            p = os.path.normpath(str(p))
            if not os.path.isfile(p):
                continue
            if not p.lower().endswith(".pdf"):
                ignorados.append(os.path.basename(p))
                continue
            try:
                tam = os.path.getsize(p)
            except OSError:
                tam = 0
            self.itens.append({"path": p, "nome": os.path.basename(p), "tam": tam})
        self._render()
        if ignorados:
            messagebox.showwarning("Ignorados",
                                   "Estes não são PDF e foram ignorados:\n" + "\n".join(ignorados))

    def remover(self):
        i = self._sel()
        if i is not None:
            del self.itens[i]
            self._render()

    def limpar(self):
        self.itens.clear()
        self._render()

    def mover(self, d):
        i = self._sel()
        if i is None:
            return
        j = i + d
        if 0 <= j < len(self.itens):
            self.itens[i], self.itens[j] = self.itens[j], self.itens[i]
            self._render(sel=j)

    def _sel(self):
        s = self.tree.selection()
        if not s:
            return None
        return self.tree.index(s[0])

    def _fmt(self, b):
        if b < 1024:
            return f"{b} B"
        if b < 1048576:
            return f"{b/1024:.0f} KB"
        return f"{b/1048576:.1f} MB"

    def _render(self, sel=None):
        aberto = self.var_repetir.get()
        self.tree.delete(*self.tree.get_children())
        for idx, it in enumerate(self.itens):
            etq = it["nome"] + ("   ◀ base (repete)" if aberto and idx == 0 else "")
            self.tree.insert("", "end", iid=str(idx),
                             values=(idx + 1, etq, self._fmt(it["tam"])))
        if sel is not None and 0 <= sel < len(self.itens):
            self.tree.selection_set(str(sel))
            self.tree.see(str(sel))
        self._atualiza_estado()
        self._mostra_previa()

    def _atualiza_estado(self):
        n = len(self.itens)
        rep = self.var_repetir.get()
        if rep:
            pares = max(n - 1, 0)
            self.bt_juntar.configure(
                text=(f"Gerar {pares} documentos" if pares > 1 else "Gerar documento"),
                state=("normal" if n >= 2 else "disabled"))
        else:
            self.bt_juntar.configure(
                text=(f"Juntar {n} PDFs" if n > 1 else "Juntar PDFs"),
                state=("normal" if n >= 1 else "disabled"))

    # ---------- prévia ----------
    def _mostra_previa(self):
        self.canvas.delete("all")
        i = self._sel()
        if i is None or i >= len(self.itens):
            self._texto_canvas("Selecione um arquivo para ver a prévia.")
            return
        if not _TEM_PREVIA:
            self._texto_canvas(self.itens[i]["nome"] + "\n(prévia indisponível nesta versão)")
            return
        try:
            cw = max(self.canvas.winfo_width(), 60)
            ch = max(self.canvas.winfo_height(), 60)
            doc = pymupdf.open(self.itens[i]["path"])
            page = doc[0]
            zoom = min((cw - 16) / page.rect.width, (ch - 16) / page.rect.height)
            zoom = max(zoom, 0.05)
            pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False)
            png = pix.tobytes("png")
            doc.close()
            self._preview_img = tk.PhotoImage(data=base64.b64encode(png).decode("ascii"))
            self.canvas.create_image(cw // 2, ch // 2, image=self._preview_img)
        except Exception:
            self._texto_canvas("Não consegui abrir a prévia deste arquivo.")

    def _texto_canvas(self, txt):
        cw = max(self.canvas.winfo_width(), 60)
        ch = max(self.canvas.winfo_height(), 60)
        self.canvas.create_text(cw // 2, ch // 2, text=txt, fill=COR_SUAVE,
                                font=("Segoe UI", 10), width=cw - 30, justify="center")

    # ---------- juntar ----------
    def _ler_arquivos(self):
        out = []
        for it in self.itens:
            with open(it["path"], "rb") as f:
                out.append((it["nome"], f.read()))
        return out

    def juntar(self):
        rep = self.var_repetir.get()
        if rep and len(self.itens) < 2:
            messagebox.showwarning("Faltam arquivos",
                                   "No modo repetir, anexe pelo menos 2 arquivos: o 1º é o que se repete.")
            return
        if not rep and len(self.itens) < 1:
            return

        if rep:
            pasta = filedialog.askdirectory(title="Escolha a pasta para salvar os PDFs gerados")
            if not pasta:
                return
            destino = pasta
        else:
            base = os.path.splitext(self.itens[0]["nome"])[0]
            sugestao = f"{base} + outros ({len(self.itens)}).pdf" if len(self.itens) > 1 else f"{base}.pdf"
            destino = filedialog.asksaveasfilename(
                title="Salvar PDF juntado", defaultextension=".pdf",
                initialfile=sugestao, filetypes=[("Arquivo PDF", "*.pdf")])
            if not destino:
                return

        self.bt_juntar.configure(state="disabled")
        self.lb_status.configure(text="Processando…")
        t = threading.Thread(target=self._trabalho, args=(rep, destino), daemon=True)
        t.start()
        self.root.after(120, self._checa_fila)

    def _trabalho(self, rep, destino):
        try:
            arquivos = self._ler_arquivos()
            if rep:
                saidas = juntar_pdf.juntar_repetindo_primeiro(arquivos)
                salvos = []
                usados = set()
                for nome, dados in saidas:
                    caminho = os.path.join(destino, nome)
                    raiz, ext = os.path.splitext(caminho)
                    k = 1
                    while caminho in usados or os.path.exists(caminho):
                        caminho = f"{raiz} ({k}){ext}"
                        k += 1
                    usados.add(caminho)
                    with open(caminho, "wb") as f:
                        f.write(dados)
                    salvos.append(caminho)
                self._fila.put(("ok_rep", destino, len(salvos)))
            else:
                pdf = juntar_pdf.juntar_vertical(arquivos)
                with open(destino, "wb") as f:
                    f.write(pdf)
                info = juntar_pdf.resumo(arquivos)
                self._fila.put(("ok_uni", destino, info))
        except juntar_pdf.ErroJuntarPDF as e:
            self._fila.put(("erro", str(e), None))
        except Exception:
            self._fila.put(("erro", "Falha inesperada:\n" + traceback.format_exc(limit=2), None))

    def _checa_fila(self):
        try:
            tipo, a, b = self._fila.get_nowait()
        except queue.Empty:
            self.root.after(120, self._checa_fila)
            return
        self.bt_juntar.configure(state="normal")
        self._atualiza_estado()
        if tipo == "erro":
            self.lb_status.configure(text="")
            messagebox.showerror("Não foi possível juntar", a)
        elif tipo == "ok_uni":
            self.lb_status.configure(text="Pronto.")
            d = b.get("dimensoes", [{}])[0]
            dim = f"{d.get('larg_cm','?')}×{d.get('alt_cm','?')} cm"
            self._sucesso(f"PDF gerado com sucesso.\n\n{b.get('paginas_origem','?')} página(s) coladas "
                          f"({dim}).\n\nSalvo em:\n{a}", a, pasta=False)
        elif tipo == "ok_rep":
            self.lb_status.configure(text="Pronto.")
            self._sucesso(f"{b} documento(s) gerado(s) — o 1º colado com cada um dos outros.\n\n"
                          f"Salvos na pasta:\n{a}", a, pasta=True)

    def _sucesso(self, msg, caminho, pasta):
        # caminho = o PDF gerado (modo normal) ou a pasta com os PDFs (modo repetir)
        abrir = messagebox.askyesno("Concluído", msg + "\n\nQuer abrir agora?")
        if abrir:
            try:
                os.startfile(caminho)  # type: ignore[attr-defined]  # pasta abre no Explorer; PDF abre no leitor
            except Exception:
                pass


def _diag(saida=None):
    """Autodiagnóstico (usado nos testes do .exe): confirma DnD, prévia e junção.
    Grava o resultado num arquivo (o .exe é --windowed e não tem console)."""
    linhas = [f"tkinterdnd2: {_TEM_DND} | pymupdf: {_TEM_PREVIA}"]
    one = _uma_pagina(300, 400); two = _uma_pagina(200, 500)
    out = juntar_pdf.juntar_vertical([("um.pdf", one), ("dois.pdf", two)])
    linhas.append(f"juncao: PDF valido={out[:5] == b'%PDF-'} bytes={len(out)}")
    if _TEM_PREVIA:
        doc = pymupdf.open(stream=out, filetype="pdf")
        png = doc[0].get_pixmap(matrix=pymupdf.Matrix(0.5, 0.5)).tobytes("png")
        eh_png = png[:4] == bytes([0x89]) + b"PNG"
        linhas.append(f"previa: PNG={eh_png} composicao={int(doc[0].rect.width)}x{int(doc[0].rect.height)}")
    linhas.append("DIAG OK")
    txt = "\n".join(linhas)
    destino = saida or os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])), "_diag_result.txt")
    try:
        with open(destino, "w", encoding="utf-8") as f:
            f.write(txt)
    except Exception:
        pass
    print(txt)


def _uma_pagina(w, h):
    import io
    from pypdf import PdfWriter
    wr = PdfWriter(); wr.add_blank_page(width=w, height=h)
    b = io.BytesIO(); wr.write(b); return b.getvalue()


def main():
    if "--diag" in sys.argv:
        i = sys.argv.index("--diag")
        _diag(sys.argv[i + 1] if i + 1 < len(sys.argv) else None)
        return
    root = _BASE_TK()
    JuntarPDFApp(root)
    if "--autoteste" in sys.argv:
        root.after(700, root.destroy)   # abre e fecha, para testar a construção
    root.mainloop()


if __name__ == "__main__":
    main()
