from flask import Flask, request, jsonify, send_file #flask para criar rotas, request para requerimento, jsonify mensagens amigaveis, send_file enviar arquivos
import pdfplumber  # abre e extrai PDFs
import csv  # criar csv
import re  # regex, buscar e extrair informações determinadas
import uuid  # gera identificadores únicos
import os  # interagir com arquivos
import io  # armazenar arquivos temporários
import zipfile  # criar e manipular zip
from PyPDF2 import PdfReader, PdfWriter  # lê e grava PDFs

app = Flask(__name__)
TEMP_DIR = "temp_pdfs"
os.makedirs(TEMP_DIR, exist_ok=True)

REGEX_PADRAO = re.compile(
    r'(?P<processo>\d{7}-\d{2}\.\d{4}\.\d{1}\.\d{2}\.\d{4})\s+'
    r'(?P<nat>[OA])\s+'
    r'(?P<data1>\d{2}/\d{2}/\d{4})(?:\s+\d{2}:\d{2}:\d{2}[:\.]\d{3})?(?:\s*-\s*Nº\s*(?P<order>\d+))?\s+'
    r'(?P<periodo>\d+/\d{4})(?:-[A-Za-z])?\s+'
    r'(?P<data2>\d{2}/\d{2}/\d{4})\s+'
    r'(?P<condicao>.+?)\s+'
    r'(?P<valor_pago>[\d\.,\-]+)\s+'
    r'(?P<saldo>[\d\.,\-]+)'
)


def extrair_dados_linha(texto):
    linhas_extraidas = []
    for linha in texto.split("\n"): #analisa linha por linha 
        linha = linha.strip() #retira os espaçamentos antes e depois 
        match = REGEX_PADRAO.search(linha) #procura o padrao especificado
        if match: #se encontrado ele continua
            processo = match.group("processo") #acessa os grupos da regex e add a informação 
            nat = match.group("nat")
            data1 = match.group("data1")
            order = match.group("order")
            periodo = match.group("periodo")
            data2 = match.group("data2")
            condicao = match.group("condicao").strip()
            valor_pago = match.group("valor_pago")
            saldo = match.group("saldo")
            linhas_extraidas.append([ #adicionando uma nova linha com as informações na lista 
                processo,
                nat,
                f"{data1} - Nº {order}" if order else data1, #se order existir é add junto com data1 mas se não existir só aparecerá a data
                periodo,
                data2,
                condicao,
                valor_pago,
                saldo
            ])
    return linhas_extraidas

def quebrar_pdf_em_blocos(caminho_pdf, tamanho_bloco):
    partes = []
    reader = PdfReader(caminho_pdf) #abre e lê o pdf 
    total_paginas = len(reader.pages) #conta quantas pag tem o PDF
    base_nome = os.path.splitext(os.path.basename(caminho_pdf))[0]

    for inicio in range(0, total_paginas, tamanho_bloco):  #loop que começa em 0 e vai até total de pag de tamanho do bloco
        fim = min(inicio + tamanho_bloco, total_paginas)
        writer = PdfWriter()
        for i in range(inicio, fim):
            writer.add_page(reader.pages[i])
        parte_nome = f"{base_nome}_parte_{inicio // tamanho_bloco + 1}.pdf"
        parte_path = os.path.join(TEMP_DIR, parte_nome)
        with open(parte_path, "wb") as f:
            writer.write(f)
        partes.append(parte_path)
    return partes

@app.route("/converter", methods=["POST"])
def converter_em_csv_unico():
    if "arquivo" not in request.files: #validações
        return jsonify({"erro": "Nenhum arquivo enviado."}), 400

    arquivo_pdf = request.files["arquivo"] #validações
    if not arquivo_pdf.filename.lower().endswith(".pdf"):
        return jsonify({"erro": "Formato inválido. Envie um arquivo PDF."}), 400

    try:
        tamanho_bloco = int(request.args.get("bloco", 100))
        nome_temp = f"temp_{uuid.uuid4().hex}.pdf" #criação de pdfs temporarios
        caminho_temp = os.path.join(TEMP_DIR, nome_temp) #onde os PDFs temporarios serao salvos e cria um caminho
        arquivo_pdf.save(caminho_temp)

        partes = quebrar_pdf_em_blocos(caminho_temp, tamanho_bloco) #chama a função 
        os.remove(caminho_temp)

        output_csv = io.StringIO() #cria um arquivo virtual sem gravar nada em disco
        escritor = csv.writer(output_csv, delimiter=";") #instancia um escritor CSV que usará output_csv como destino.
        escritor.writerow([ #cabeçalho
            "Processo", "Nat.", "Data 1 - Nº Pedido", "Periodo",
            "Data 2", "Condicao", "Valor Pago", "Saldo"
        ])

        arquivos_para_apagar = []

        for parte in partes:
            with pdfplumber.open(parte) as pdf:
                for pagina in pdf.pages:
                    texto = pagina.extract_text()
                    if not texto:
                        continue
                    linhas = extrair_dados_linha(texto)
                    escritor.writerows(linhas)
            arquivos_para_apagar.append(parte)

        zip_nome = f"convertido_{uuid.uuid4().hex}.zip"
        zip_buffer = io.BytesIO() #criação do zip
        with zipfile.ZipFile(zip_buffer, "w") as zipfile_obj: 
            zipfile_obj.writestr("todas_as_partes.csv", output_csv.getvalue())  #salvando todas as partes

        for arquivo in arquivos_para_apagar: # apagar os PDFs que foram divididos 
            try:
                os.remove(arquivo)
            except Exception:
                pass

        zip_buffer.seek(0)
        return send_file( #Com o flask envia zip para download
            zip_buffer,
            mimetype="application/zip",
            as_attachment=True,
            download_name=zip_nome
        )

    except Exception as e:
        return jsonify({"erro": f"Falha ao converter PDF: {str(e)}"}), 500

if __name__ == "__main__": #permite executar diretamente com o python 
    app.run(debug=False)

#TENTEI