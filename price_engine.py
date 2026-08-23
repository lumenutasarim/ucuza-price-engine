import os
import json
import re
import requests
from bs4 import BeautifulSoup

import firebase_admin
from firebase_admin import credentials, firestore


# =========================================================
# FIREBASE
# =========================================================

service_account = os.environ.get("FIREBASE_SERVICE_ACCOUNT")

if not service_account:
    raise RuntimeError("FIREBASE_SERVICE_ACCOUNT bulunamadı.")

cred = credentials.Certificate(json.loads(service_account))

if not firebase_admin._apps:
    firebase_admin.initialize_app(cred)

db = firestore.client()


# =========================================================
# ÜRÜNLER
# =========================================================
#
# Mevcut ürününü koruyoruz.
# Daha sonra burayı Firestore'dan otomatik okuyacağız.
#

PRODUCTS = [
    {
        "barcode": "8690504010011",
        "name": "Yumurta",
        "brand": "Bili Bili",
        "quantity": "30'lu",
        "unit": "1 adet"
    }
]


# =========================================================
# HTTP
# =========================================================

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/139.0 Safari/537.36"
    ),
    "Accept-Language": "tr-TR,tr;q=0.9,en;q=0.8"
}


def get_page(url):
    try:
        response = requests.get(
            url,
            headers=HEADERS,
            timeout=25
        )

        response.raise_for_status()

        return response.text

    except Exception as e:
        print(f"Sayfa alınamadı: {url}")
        print(e)
        return None


# =========================================================
# FİYAT TEMİZLEME
# =========================================================

def parse_price(value):

    if value is None:
        return None

    value = str(value)

    value = value.replace("₺", "")
    value = value.replace("TL", "")
    value = value.replace("tl", "")
    value = value.strip()

    # 1.299,90 -> 1299.90
    if "," in value:
        value = value.replace(".", "")
        value = value.replace(",", ".")

    # sadece sayı
    value = re.sub(r"[^0-9.]", "", value)

    try:
        price = float(value)

        if price <= 0:
            return None

        return price

    except:
        return None


# =========================================================
# FIRESTORE'A FİYAT KAYDET
# =========================================================

def save_price(product, store, price):

    price = parse_price(price)

    if price is None:
        return False

    ref = (
        db.collection("prices")
        .document(product["barcode"])
        .collection("stores")
        .document(store)
    )

    ref.set(
        {
            "barcode": product["barcode"],
            "productName": product["name"],
            "brand": product["brand"],
            "quantity": product["quantity"],
            "unit": product["unit"],
            "store": store,
            "price": price,
            "currency": "TRY",
            "updatedAt": firestore.SERVER_TIMESTAMP
        },
        merge=True
    )

    print(
        f"[FIRESTORE] {store} | "
        f"{product['name']} | "
        f"{price:.2f} TL"
    )

    return True


# =========================================================
# GENEL ÜRÜN EŞLEŞTİRME
# =========================================================

def normalize(text):

    if not text:
        return ""

    text = text.lower()

    replacements = {
        "ç": "c",
        "ğ": "g",
        "ı": "i",
        "ö": "o",
        "ş": "s",
        "ü": "u"
    }

    for old, new in replacements.items():
        text = text.replace(old, new)

    text = re.sub(r"[^a-z0-9 ]", " ", text)

    text = re.sub(r"\s+", " ", text)

    return text.strip()


def product_matches(product, text):

    text = normalize(text)

    name = normalize(product["name"])
    brand = normalize(product["brand"])
    quantity = normalize(product["quantity"])

    score = 0

    if name and name in text:
        score += 3

    if brand and brand in text:
        score += 3

    if quantity and quantity in text:
        score += 2

    return score >= 5


# =========================================================
# ŞOK
# =========================================================

def scan_sok(product):

    print("ŞOK kontrol ediliyor...")

    url = "https://www.sokmarket.com.tr/market-c-10"

    html = get_page(url)

    if not html:
        return

    soup = BeautifulSoup(html, "html.parser")

    found = []

    # Sayfadaki tüm metinleri kontrol ediyoruz.
    texts = soup.stripped_strings

    for text in texts:

        text = str(text).strip()

        if product_matches(product, text):

            found.append(text)

    # Sayfadaki ürün bloklarından fiyat yakalamaya çalış
    page_text = soup.get_text(" ", strip=True)

    if product_matches(product, page_text):

        prices = re.findall(
            r"(\d{1,5}(?:[.,]\d{1,2})?)\s*₺",
            page_text
        )

        for price in prices:

            parsed = parse_price(price)

            if parsed:

                save_price(
                    product,
                    "ŞOK",
                    parsed
                )

                return

    print("ŞOK: uygun fiyat bulunamadı.")


# =========================================================
# A101
# =========================================================

def scan_a101(product):

    print("A101 kontrol ediliyor...")

    url = "https://www.a101.com.tr/market"

    html = get_page(url)

    if not html:
        return

    soup = BeautifulSoup(html, "html.parser")

    page_text = soup.get_text(" ", strip=True)

    if not product_matches(product, page_text):

        print("A101: ürün sayfada bulunamadı.")

        return

    prices = re.findall(
        r"₺\s*([0-9.]+(?:,[0-9]{1,2})?)",
        page_text
    )

    if not prices:

        prices = re.findall(
            r"([0-9.]+(?:,[0-9]{1,2})?)\s*₺",
            page_text
        )

    for price in prices:

        parsed = parse_price(price)

        if parsed:

            save_price(
                product,
                "A101",
                parsed
            )

            return

    print("A101: fiyat bulunamadı.")


# =========================================================
# ÜRÜN GÜNCELLEME
# =========================================================

def update_products():

    print("")
    print("======================================")
    print("UCUZA FİYAT MOTORU")
    print("======================================")
    print("")

    for product in PRODUCTS:

        print("")
        print(
            "Ürün:",
            product["name"],
            "|",
            product["brand"],
            "|",
            product["quantity"]
        )

        print(
            "Barkod:",
            product["barcode"]
        )

        print("--------------------------------------")

        scan_sok(product)

        scan_a101(product)

    print("")
    print("Fiyat kontrolü tamamlandı.")
    print("")


# =========================================================
# MAIN
# =========================================================

if __name__ == "__main__":
    update_products()
