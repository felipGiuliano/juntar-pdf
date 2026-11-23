# -*- coding: utf-8 -*-
r"""Juntar PDF (vertical) — app local que roda só na sua máquina (127.0.0.1).

Dois modos:
  * Único:   cola todos os PDFs um ABAIXO do outro, numa composição contínua.
  * Repetir: repete o 1º documento colado com cada um dos outros e gera um PDF
             por par (1+2, 1+3, 1+4...), baixados num ZIP.

Nada sai do computador nem é gravado em disco pelo servidor: tudo em memória.

    python app.py            abre o navegador na ferramenta
"""
from __future__ import annotations

import io
import os
import socket
import sys
import threading
import webbrowser
import zipfile

from flask import Flask, jsonify, render_template, request, send_file

import juntar_pdf

# Quando empacotado com o PyInstaller (.exe), os arquivos ficam numa pasta
# temporária em sys._MEIPASS; fora dele, é a pasta deste arquivo.
_BASE = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
app = Flask(__name__, template_folder=os.path.join(_BASE, "templates"))
app.config["MAX_CONTENT_LENGTH"] = 800 * 1024 * 1024   # 800 MB no total do envio

# Último resultado (só nesta sessão do processo, nunca em disco): o arquivo para
# baixar (PDF ou ZIP) e um PDF para a pré-visualização na tela.
_ultimo = {"dados": None, "nome": "documentos-juntados.pdf", "tipo": "application/pdf"}
_previa = {"dados": None}


@app.route("/")
def inicio():
    return render_template("index.html")


def _ler_enviados():
    enviados = request.files.getlist("arquivos")
    if not enviados:
        raise juntar_pdf.ErroJuntarPDF("Nenhum arquivo foi anexado.")
    arquivos = []
    for fs in enviados:
        nome = fs.filename or "arquivo.pdf"
        dados = fs.read()
        if not dados:
            raise juntar_pdf.ErroJuntarPDF(f"O arquivo “{nome}” chegou vazio.")
        arquivos.append((nome, dados))
    return arquivos


@app.route("/juntar", methods=["POST"])
def juntar():
    modo = request.form.get("modo", "unico")
    try:
        arquivos = _ler_enviados()
        if modo == "repetir":
            saidas = juntar_pdf.juntar_repetindo_primeiro(arquivos)   # lista de (nome, pdf)
            info = juntar_pdf.resumo_repetindo(arquivos)
            _previa["dados"] = saidas[0][1]                            # mostra o 1º par
            if len(saidas) == 1:
                _ultimo.update(dados=saidas[0][1], nome=saidas[0][0], tipo="application/pdf")
                resposta = {"tipo": "pdf", "nome": saidas[0][0],
                            "base": info["base"], "pares": 1, "itens": info["itens"]}
            else:
                nome_zip = _nome_zip(arquivos[0][0], len(saidas))
                _ultimo.update(dados=_zipar(saidas), nome=nome_zip, tipo="application/zip")
                resposta = {"tipo": "zip", "nome": nome_zip, "arquivos_no_zip": len(saidas),
                            "base": info["base"], "pares": len(saidas), "itens": info["itens"]}
        else:
            pdf = juntar_pdf.juntar_vertical(arquivos)
            info = juntar_pdf.resumo(arquivos)
            _previa["dados"] = pdf
            nome = _nome_saida(arquivos)
            _ultimo.update(dados=pdf, nome=nome, tipo="application/pdf")
            resposta = {"tipo": "pdf", "nome": nome, **info}
    except juntar_pdf.ErroJuntarPDF as e:
        return jsonify(erro=str(e)), 400
    except Exception as e:   # rede de segurança: nunca devolve 500 cru
        return jsonify(erro=f"Falha inesperada ao juntar: {type(e).__name__}: {e}"), 400
    return jsonify(ok=True, **resposta)


@app.route("/previa")
def previa():
    if not _previa["dados"]:
        return "Sem prévia.", 404
    return send_file(io.BytesIO(_previa["dados"]), mimetype="application/pdf",
                     as_attachment=False, download_name="previa.pdf")


@app.route("/baixar")
def baixar():
    if not _ultimo["dados"]:
        return "Nada gerado ainda.", 404
    return send_file(io.BytesIO(_ultimo["dados"]), mimetype=_ultimo["tipo"],
                     as_attachment=True, download_name=_ultimo["nome"])


def _zipar(saidas):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        usados = {}
        for nome, dados in saidas:
            # evita nomes repetidos dentro do ZIP
            final = nome
            if final in usados:
                usados[final] += 1
                raiz, ext = os.path.splitext(nome)
                final = f"{raiz} ({usados[nome]}){ext}"
            else:
                usados[final] = 1
            z.writestr(final, dados)
    return buf.getvalue()


def _nome_saida(arquivos):
    base = os.path.splitext(os.path.basename(arquivos[0][0]))[0]
    return f"{base} + outros ({len(arquivos)}).pdf" if len(arquivos) > 1 else f"{base}.pdf"


def _nome_zip(base_nome, n):
    base = os.path.splitext(os.path.basename(base_nome))[0]
    return f"{base} - juntado com {n} documento(s).zip"


def _porta_livre(preferida=5058):
    for p in [preferida] + list(range(5059, 5090)):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", p)) != 0:
                return p
    return 0


def main():
    porta = _porta_livre()
    url = f"http://127.0.0.1:{porta}/"
    threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    print(f"Juntar PDF rodando em {url}  (feche esta janela para encerrar)")
    app.run(host="127.0.0.1", port=porta, debug=False, threaded=True)


if __name__ == "__main__":
    main()
