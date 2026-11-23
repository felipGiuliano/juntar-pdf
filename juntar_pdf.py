# -*- coding: utf-8 -*-
r"""Motor da junção VERTICAL de PDFs — cola os documentos um abaixo do outro
numa página só (de dimensões ampliadas), na ordem em que foram passados, SEM
perder nada.

Princípios (por que é fiel aos originais):
  * Cada página de origem entra como OBJETO VETORIAL no PDF final
    (merge_transformed_page). Texto continua texto pesquisável, imagem fica na
    resolução original. Nada é rasterizado nem "fotografado", então número
    pequeno e assinatura não borram.
  * Tamanho original respeitado: cada página é colada no seu tamanho real, sem
    esticar nem encolher. Se um documento é mais estreito que o mais largo, ele
    fica CENTRALIZADO e sobra branco nas laterais (nunca corta).
  * Páginas giradas (digitalização em pé/deitado) são endireitadas antes de
    colar (transfer_rotation_to_content), senão entrariam deitadas/cortadas.
  * Limite físico do formato PDF: uma página não pode passar de 200 polegadas
    (14400 pt) de altura. Enquanto a pilha couber, é UMA página alta só. Quando
    não couber (ex.: um contrato com muitas páginas), a composição continua na
    próxima página alta — nunca cortando nem reduzindo para forçar o encaixe.

Uso como biblioteca:
    from juntar_pdf import juntar_vertical
    pdf_bytes = juntar_vertical([("contrato.pdf", dados1), ("planilha.pdf", dados2)])

Uso pela linha de comando (teste rápido):
    python juntar_pdf.py saida.pdf a.pdf b.pdf c.pdf
"""
from __future__ import annotations

import io
import sys
from dataclasses import dataclass

from pypdf import PdfReader, PdfWriter, Transformation

# Altura máxima de uma página PDF: 14400 pt = 200 polegadas (limite do formato,
# respeitado pelo Acrobat e pela maioria dos leitores). Deixo uma folga mínima.
ALTURA_MAX_PT = 14400.0
# Margem de segurança para o branco não encostar exatamente na borda.
FOLGA_PT = 0.0


class ErroJuntarPDF(Exception):
    """Erro tratado da junção, com mensagem pronta para mostrar ao usuário."""


@dataclass
class _Pag:
    pagina: object          # PageObject já endireitado
    larg: float
    alt: float
    origem: str             # nome do arquivo de onde veio
    indice_no_arquivo: int  # 1 = primeira página daquele arquivo


def _mediabox(p):
    mb = p.mediabox
    return (float(mb.left), float(mb.bottom), float(mb.width), float(mb.height))


def _coletar_paginas(arquivos: list[tuple[str, bytes]]) -> list[_Pag]:
    """Lê cada arquivo e devolve TODAS as páginas, na ordem de inserção."""
    if not arquivos:
        raise ErroJuntarPDF("Nenhum arquivo foi anexado.")
    pags: list[_Pag] = []
    for nome, dados in arquivos:
        try:
            r = PdfReader(io.BytesIO(dados))
        except Exception as e:
            raise ErroJuntarPDF(f"Não consegui abrir “{nome}”: parece não ser um PDF válido ({type(e).__name__}).")
        if getattr(r, "is_encrypted", False):
            # Tenta abrir com senha vazia (PDF só "protegido" sem senha de fato).
            try:
                if r.decrypt("") == 0:
                    raise ErroJuntarPDF(f"“{nome}” está protegido por senha. Remova a senha antes de juntar.")
            except ErroJuntarPDF:
                raise
            except Exception:
                raise ErroJuntarPDF(f"“{nome}” está protegido por senha. Remova a senha antes de juntar.")
        n = len(r.pages)
        if n == 0:
            raise ErroJuntarPDF(f"“{nome}” não tem páginas.")
        for i in range(n):
            p = r.pages[i]
            # Endireita páginas giradas para não colar deitado/cortado.
            try:
                p.transfer_rotation_to_content()
            except Exception:
                pass
            _, _, w, h = _mediabox(p)
            if w <= 0 or h <= 0:
                raise ErroJuntarPDF(f"“{nome}”, página {i + 1}: tamanho inválido ({w:.0f}x{h:.0f}).")
            if h > ALTURA_MAX_PT:
                raise ErroJuntarPDF(
                    f"“{nome}”, página {i + 1} tem {h / 72:.1f} polegadas de altura, acima do "
                    f"limite de 200 do formato PDF. Essa página sozinha não cabe numa composição vertical."
                )
            pags.append(_Pag(p, w, h, nome, i + 1))
    return pags


def _agrupar_por_altura(pags: list[_Pag], altura_max: float) -> list[list[_Pag]]:
    """Divide a pilha em blocos que cabem na altura máxima de uma página PDF.
    Em uso normal (contrato + planilha) devolve um único bloco."""
    grupos: list[list[_Pag]] = []
    atual: list[_Pag] = []
    soma = 0.0
    for p in pags:
        if atual and soma + p.alt > altura_max:
            grupos.append(atual)
            atual, soma = [], 0.0
        atual.append(p)
        soma += p.alt
    if atual:
        grupos.append(atual)
    return grupos


def juntar_vertical(
    arquivos: list[tuple[str, bytes]],
    altura_max: float = ALTURA_MAX_PT,
) -> bytes:
    """Junta os PDFs verticalmente e devolve os bytes do PDF final.

    arquivos: lista de (nome, bytes do PDF), NA ORDEM desejada (a ordem é
              respeitada exatamente; a função nunca reordena).
    """
    pags = _coletar_paginas(arquivos)
    grupos = _agrupar_por_altura(pags, altura_max - FOLGA_PT)

    writer = PdfWriter()
    for grupo in grupos:
        altura_total = sum(p.alt for p in grupo)
        larg_max = max(p.larg for p in grupo)
        # Página base em branco (branco = papel, cobre as laterais que sobrarem).
        base = writer.add_blank_page(width=larg_max, height=altura_total)
        y_topo = altura_total
        for p in grupo:
            llx, lly, w, h = _mediabox(p.pagina)
            y_base = y_topo - h                 # canto de baixo desta página
            x = (larg_max - w) / 2.0            # centraliza na horizontal
            t = Transformation().translate(x - llx, y_base - lly)
            base.merge_transformed_page(p.pagina, t, expand=False)
            y_topo -= h
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def resumo(arquivos: list[tuple[str, bytes]], altura_max: float = ALTURA_MAX_PT) -> dict:
    """Prévia do que vai sair, sem gerar o arquivo (para a interface)."""
    pags = _coletar_paginas(arquivos)
    grupos = _agrupar_por_altura(pags, altura_max - FOLGA_PT)
    return {
        "arquivos": len(arquivos),
        "paginas_origem": len(pags),
        "paginas_resultado": len(grupos),
        "dimensoes": [
            {
                "larg_pt": round(max(p.larg for p in g), 1),
                "alt_pt": round(sum(p.alt for p in g), 1),
                "larg_cm": round(max(p.larg for p in g) / 72 * 2.54, 1),
                "alt_cm": round(sum(p.alt for p in g) / 72 * 2.54, 1),
                "paginas": len(g),
            }
            for g in grupos
        ],
    }


def _nome_par(base_nome: str, outro_nome: str) -> str:
    import os
    a = os.path.splitext(os.path.basename(base_nome))[0]
    b = os.path.splitext(os.path.basename(outro_nome))[0]
    return f"{a} + {b}.pdf"


def juntar_repetindo_primeiro(
    arquivos: list[tuple[str, bytes]],
    altura_max: float = ALTURA_MAX_PT,
) -> list[tuple[str, bytes]]:
    """Repete o 1º documento colado com cada um dos outros.

    De [base, a, b, c] gera uma lista de PDFs: (base+a), (base+b), (base+c) —
    um arquivo por par, cada um na colagem vertical (base em cima, o outro
    embaixo). A ordem dos pares segue a ordem dos arquivos. Devolve uma lista de
    (nome do arquivo, bytes do PDF).
    """
    if len(arquivos) < 2:
        raise ErroJuntarPDF(
            "Para repetir o 1º documento, anexe pelo menos 2 arquivos: o 1º é o que se repete, "
            "e ele é colado com cada um dos demais."
        )
    base = arquivos[0]
    saidas: list[tuple[str, bytes]] = []
    for outro in arquivos[1:]:
        pdf = juntar_vertical([base, outro], altura_max=altura_max)
        saidas.append((_nome_par(base[0], outro[0]), pdf))
    return saidas


def resumo_repetindo(arquivos: list[tuple[str, bytes]], altura_max: float = ALTURA_MAX_PT) -> dict:
    """Prévia do modo 'repetir o 1º', sem gerar os arquivos."""
    if len(arquivos) < 2:
        raise ErroJuntarPDF(
            "Para repetir o 1º documento, anexe pelo menos 2 arquivos: o 1º é o que se repete, "
            "e ele é colado com cada um dos demais."
        )
    base = arquivos[0]
    pares = []
    for outro in arquivos[1:]:
        r = resumo([base, outro], altura_max=altura_max)
        pares.append({"nome": _nome_par(base[0], outro[0]), **r})
    return {"base": base[0], "pares": len(pares), "itens": pares}


def _cli() -> int:
    if len(sys.argv) < 3:
        print("uso: python juntar_pdf.py saida.pdf entrada1.pdf entrada2.pdf [...]")
        return 2
    saida, entradas = sys.argv[1], sys.argv[2:]
    arquivos = []
    for e in entradas:
        with open(e, "rb") as f:
            arquivos.append((e, f.read()))
    try:
        dados = juntar_vertical(arquivos)
    except ErroJuntarPDF as err:
        print("ERRO:", err)
        return 1
    with open(saida, "wb") as f:
        f.write(dados)
    r = resumo(arquivos)
    print(f"OK: {r['arquivos']} arquivo(s), {r['paginas_origem']} página(s) de origem "
          f"-> {r['paginas_resultado']} página(s) no resultado.")
    for i, d in enumerate(r["dimensoes"], 1):
        print(f"  página {i}: {d['larg_cm']}x{d['alt_cm']} cm ({d['paginas']} doc/páginas)")
    print("arquivo:", saida)
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
