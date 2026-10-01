import time
import random
import re
import requests
from bs4 import BeautifulSoup
import pandas as pd
from datetime import datetime

# ==========================================
# 1. PARÂMETROS OPERACIONAIS (FOZ DO IGUAÇU)
# ==========================================
DOLAR_TURISMO = 5.25        # Cotação base de Ciudad del Este
TRAVA_CAMBIAL_PCT = 0.03    # +3% de margem de segurança cambial
CUSTO_MOTO_UNIT = 3.50      # Gasolina diluída por item (R$ 35 tanque / 10 entregas)
CUSTO_EMBALAGEM = 4.50      # Caixa kraft, plástico bolha e etiqueta
CUSTO_MEI_UNIT = 1.50       # DAS MEI mensal diluído
TAXA_SHOPEE_PCT = 0.20      # 20% (14% comissão + 6% frete grátis)
TAXA_SHOPEE_FIXA = 4.00     # R$ 4,00 taxa fixa por item
MARGEM_RMA_PCT = 0.05       # 5% de reserva técnica para garantia/trocas
MARGEM_LUCRO_ALVO = 0.25    # 25% de margem líquida sobre o preço final

TERMOS_BUSCA = [
    {"categoria": "SSD NVMe", "termo": "ssd nvme", "max_pages": 2},
    {"categoria": "SSD SATA", "termo": "ssd sata", "max_pages": 1},
    {"categoria": "Memória RAM", "termo": "memoria ddr4", "max_pages": 2},
    {"categoria": "Memória RAM DDR5", "termo": "memoria ddr5", "max_pages": 1},
    {"categoria": "Processador Ryzen", "termo": "processador ryzen", "max_pages": 2},
    {"categoria": "Smartwatch", "termo": "smartwatch xiaomi", "max_pages": 1},
    {"categoria": "Smartwatch Amazfit", "termo": "smartwatch amazfit", "max_pages": 1}
]

PALAVRAS_IGNORAR = [
    "cabo", "case", "adaptador", "gaveta", "pulseira", "película", "cooler fan", 
    "dissipador", "parafuso", "adesivo", "suporte", "chaveiro"
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8",
    "Referer": "https://www.comprasparaguai.com.br/",
}

def extrair_valor_numerico(texto):
    if not texto:
        return 0.0
    texto_limpo = re.sub(r"[^\d,\.]", "", texto).replace(".", "").replace(",", ".")
    try:
        return float(texto_limpo)
    except ValueError:
        return 0.0

def calcular_economia_unitaria(preco_dolar):
    dolar_efetivo = DOLAR_TURISMO * (1 + TRAVA_CAMBIAL_PCT)
    custo_compra_brl = preco_dolar * dolar_efetivo
    custos_fixos_op = CUSTO_MOTO_UNIT + CUSTO_EMBALAGEM + CUSTO_MEI_UNIT

    denominador = 1.0 - TAXA_SHOPEE_PCT - MARGEM_RMA_PCT - MARGEM_LUCRO_ALVO
    if denominador <= 0:
        denominador = 0.50

    preco_sugerido = (custo_compra_brl + custos_fixos_op + TAXA_SHOPEE_FIXA) / denominador
    taxa_mkt = (preco_sugerido * TAXA_SHOPEE_PCT) + TAXA_SHOPEE_FIXA
    reserva_rma = preco_sugerido * MARGEM_RMA_PCT
    custo_total = custo_compra_brl + custos_fixos_op + taxa_mkt + reserva_rma
    lucro_liquido = preco_sugerido - custo_total
    margem_real = (lucro_liquido / preco_sugerido) * 100 if preco_sugerido > 0 else 0
    roi = (lucro_liquido / (custo_compra_brl + custos_fixos_op)) * 100 if (custo_compra_brl + custos_fixos_op) > 0 else 0

    return {
        "custo_compra_brl": round(custo_compra_brl, 2),
        "custos_operacionais": round(custos_fixos_op, 2),
        "taxas_shopee": round(taxa_mkt, 2),
        "reserva_rma": round(reserva_rma, 2),
        "custo_total": round(custo_total, 2),
        "preco_sugerido": round(preco_sugerido, 2),
        "lucro_liquido": round(lucro_liquido, 2),
        "margem_liquida_pct": round(margem_real, 1),
        "roi_pct": round(roi, 1)
    }

def scrape_compras_paraguai():
    print(f"Iniciando coleta Compras Paraguai - {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    produtos_coletados = []
    session = requests.Session()
    session.headers.update(HEADERS)

    for item in TERMOS_BUSCA:
        categoria = item["categoria"]
        termo = item["termo"]
        max_pages = item["max_pages"]

        for page in range(1, max_pages + 1):
            url = f"https://www.comprasparaguai.com.br/busca/?q={termo.replace(' ', '+')}&page={page}"
            try:
                response = session.get(url, timeout=15)
                if response.status_code != 200:
                    break

                soup = BeautifulSoup(response.text, "html.parser")
                cards = soup.find_all("div", class_=lambda x: x and ("item" in x or "product" in x))

                for card in cards:
                    title_elem = card.find(["h2", "h3", "a"], class_=lambda x: x and ("title" in x or "nome" in x or "product" in x))
                    if not title_elem:
                        link_elem = card.find("a", href=lambda h: h and "/produto/" in h)
                        if link_elem:
                            title_elem = link_elem

                    if not title_elem:
                        continue

                    nome_produto = title_elem.get_text(strip=True)
                    if len(nome_produto) < 8 or any(ign in nome_produto.lower() for ign in PALAVRAS_IGNORAR):
                        continue

                    match = re.search(r"US\$\s*([\d\.,]+)", card.get_text())
                    preco_dolar = extrair_valor_numerico(match.group(1)) if match else 0.0

                    if preco_dolar <= 10.0:  # Exclui itens abaixo de US$ 10
                        continue

                    link_tag = card.find("a", href=True)
                    link_href = link_tag["href"] if link_tag else ""
                    if link_href and not link_href.startswith("http"):
                        link_href = f"https://www.comprasparaguai.com.br{link_href}"

                    ofertas_elem = card.find(string=re.compile(r"OFERTA", re.I))
                    qtd_ofertas = ofertas_elem.strip() if ofertas_elem else "1 oferta"

                    fin = calcular_economia_unitaria(preco_dolar)

                    produtos_coletados.append({
                        "Categoria": categoria,
                        "Produto": nome_produto,
                        "Preço PY (US$)": preco_dolar,
                        "Custo Compra (R$)": fin["custo_compra_brl"],
                        "Custos Operacionais": fin["custos_operacionais"],
                        "Taxas Shopee": fin["taxas_shopee"],
                        "Reserva RMA": fin["reserva_rma"],
                        "Custo Total": fin["custo_total"],
                        "Preço Sugerido": fin["preco_sugerido"],
                        "Lucro Líquido": fin["lucro_liquido"],
                        "Margem (%)": fin["margem_liquida_pct"],
                        "ROI (%)": fin["roi_pct"],
                        "Lojas Disponíveis": qtd_ofertas,
                        "Link": link_href,
                        "Perfil": "High-Ticket / Low-Size",
                        "Data": datetime.now().strftime("%d/%m/%Y")
                    })
            except Exception as e:
                print(f"Erro em {url}: {e}")

            time.sleep(random.uniform(1.8, 3.0))

    if not produtos_coletados:
        print("Nenhum item coletado.")
        return

    df = pd.DataFrame(produtos_coletados).drop_duplicates(subset=["Produto"])
    df = df.sort_values(by="Lucro Líquido", ascending=False)

    nome_arquivo = f"oportunidades_{datetime.now().strftime('%Y%m%d')}.xlsx"
    with pd.ExcelWriter(nome_arquivo, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="Todas", index=False)
        df[df["Lucro Líquido"] >= 35.0].to_excel(writer, sheet_name="Top Margem Moto", index=False)

    print(f"Concluído! Arquivo gerado: {nome_arquivo}")

if __name__ == "__main__":
    scrape_compras_paraguai()
