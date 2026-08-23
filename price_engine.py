import os
import json
import re
import requests
from bs4 import BeautifulSoup

import firebase_admin
from firebase_admin import credentials, firestore


# =========================================================
# UCUZA FİYAT MOTORU — FINAL
# =========================================================

print("")
print("======================================")
print("UCUZA FİYAT MOTORU")
print("======================================")
print("")


# =========================================================
# FIREBASE
# =========================================================

service_account = os.environ.get("FIREBASE_SERVICE_ACCOUNT")

if not service_account:
    raise RuntimeError(
        "FIREBASE_SERVICE_ACCOUNT GitHub Secret bulunamadı."
    )

try:
    service_account_data = json.loads(service_account)
except Exception as e:
    raise RuntimeError(
        f"FIREBASE_SERVICE_ACCOUNT JSON okunamadı: {e}"
    )

if not firebase_admin._apps:
    cred = credentials.Certificate(service_account_data)
    firebase_admin.initialize_app(cred)

db = firestore.client()


# =========================================================
# HTTP
# =========================================================

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/139.0 Safari/537.36"
    ),
    "Accept-Language": "tr-TR,tr;q=0.9,en;q=0.8",
}


def get_page(url):
    try:
        response = requests.get(
            url,
            headers=HEADERS,
            timeout=25,
        )

        response.raise_for_status()

        return response.text

    except Exception as e:
        print(f"Sayfa alınamadı: {url}")
        print(f"Hata: {e}")
        return None


# =========================================================
# METİN NORMALİZE
# =========================================================

def normalize(text):

    if not text:
        return ""

    text = str(text).lower()

    replacements = {
        "ç": "c",
        "ğ": "g",
        "ı": "i",
        "ö": "o",
        "ş": "s",
        "ü": "u",
    }

    for old, new in replacements.items():
        text = text.replace(old, new)

    text = re.sub(r"[^a-z0-9 ]", " ", text)
    text = re.sub(r"\s+", " ", text)

    return text.strip()


# =========================================================
# FİYAT TEMİZLEME
# =========================================================

def parse_price(value):

    if value is None:
        return None

    value = str(value).strip()

    value = value.replace("₺", "")
    value = value.replace("TL", "")
    value = value.replace("tl", "")
    value = value.strip()

    if not value:
        return None

    # Türkçe fiyat:
    # 1.299,90 -> 1299.90
    if "," in value:
        value = value.replace(".", "")
        value = value.replace(",", ".")

    value = re.sub(r"[^0-9.]", "", value)

    try:
        price = float(value)

        if price <= 0:
            return None

        return price

    except Exception:
        return None


# =========================================================
# FIRESTORE ÜRÜNLERİNİ OTOMATİK AL
# =========================================================

def get_products():

    print("Firestore ürünleri kontrol ediliyor...")
    print("")

    products = []

    try:

        docs = db.collection("products").stream()

        for doc in docs:

            data = doc.to_dict() or {}

            barcode = str(
                data.get("barcode")
                or data.get("barkod")
                or ""
            ).strip()

            name = str(
                data.get("name")
                or data.get("productName")
                or data.get("urunAdi")
                or data.get("urun")
                or ""
            ).strip()

            brand = str(
                data.get("brand")
                or data.get("marka")
                or ""
            ).strip()

            quantity = str(
                data.get("quantity")
                or data.get("miktar")
                or ""
            ).strip()

            unit = str(
                data.get("unit")
                or data.get("birim")
                or "1 adet"
            ).strip()

            if not barcode and not name:
                continue

            product = {
                "barcode": barcode,
                "name": name,
                "brand": brand,
                "quantity": quantity,
                "unit": unit,
            }

            products.append(product)

        print(
            f"Firestore'dan {len(products)} ürün bulundu."
        )

        return products

    except Exception as e:

        print("Firestore ürünleri okunamadı.")
        print(f"Hata: {e}")

        return []


# =========================================================
# ÜRÜN EŞLEŞTİRME
# =========================================================

def product_matches(product, text):

    text = normalize(text)

    name = normalize(product.get("name"))
    brand = normalize(product.get("brand"))
    quantity = normalize(product.get("quantity"))

    score = 0

    if name and name in text:
        score += 3

    if brand and brand in text:
        score += 3

    if quantity and quantity in text:
        score += 2

    # Ürün adı tek başına yeterli olabilir
    if name and name in text:
        return True

    return score >= 5


# =========================================================
# FIRESTORE FİYAT KAYDET
# =========================================================

def save_price(product, store, price):

    price = parse_price(price)

    if price is None:
        return False

    barcode = product.get("barcode")

    if not barcode:
        barcode = normalize(
            product.get("name", "")
        ).replace(" ", "-")

    try:

        ref = (
            db.collection("prices")
            .document(barcode)
            .collection("stores")
            .document(
                normalize(store).replace(" ", "-")
            )
        )

        ref.set(
            {
                "barcode": product.get("barcode", ""),
                "productName": product.get("name", ""),
                "brand": product.get("brand", ""),
                "quantity": product.get("quantity", ""),
                "unit": product.get("unit", ""),
                "store": store,
                "price": price,
                "currency": "TRY",
                "updatedAt": firestore.SERVER_TIMESTAMP,
            },
            merge=True,
        )

        print(
            f"[FIRESTORE] {store} | "
            f"{product.get('name')} | "
            f"{price:.2f} TL"
        )

        return True

    except Exception as e:

        print(
            f"[FIRESTORE HATA] {store}: {e}"
        )

        return False


# =========================================================
# FİYAT BUL
# =========================================================

def extract_prices(text):

    if not text:
        return []

    results = []

    patterns = [
        r"₺\s*([0-9]{1,5}(?:[.,][0-9]{1,2})?)",
        r"([0-9]{1,5}(?:[.,][0-9]{1,2})?)\s*₺",
        r"([0-9]{1,5}(?:[.,][0-9]{1,2})?)\s*TL",
        r"TL\s*([0-9]{1,5}(?:[.,][0-9]{1,2})?)",
    ]

    for pattern in patterns:

        matches = re.findall(
            pattern,
            text,
            flags=re.IGNORECASE,
        )

        for value in matches:

            price = parse_price(value)

            if price is not None:
                results.append(price)

    # Tekrarlanan fiyatları kaldır
    unique_prices = []

    for price in results:

        if price not in unique_prices:
            unique_prices.append(price)

    return unique_prices


# =========================================================
# ŞOK
# =========================================================

def scan_sok(product):

    print("")
    print("ŞOK kontrol ediliyor...")

    url = "https://www.sokmarket.com.tr/market-c-10"

    html = get_page(url)

    if not html:
        print("ŞOK: sayfa alınamadı.")
        return False

    soup = BeautifulSoup(
        html,
        "html.parser"
    )

    page_text = soup.get_text(
        " ",
        strip=True
    )

    if not product_matches(
        product,
        page_text
    ):

        print(
            "ŞOK: ürün bulunamadı."
        )

        return False

    prices = extract_prices(page_text)

    if not prices:

        print(
            "ŞOK: ürün bulundu fakat fiyat bulunamadı."
        )

        return False

    # En uygun fiyatı kullan
    price = min(prices)

    print(
        f"ŞOK fiyatı: {price:.2f} TL"
    )

    return save_price(
        product,
        "SOK",
        price
    )


# =========================================================
# A101
# =========================================================

def scan_a101(product):

    print("")
    print("A101 kontrol ediliyor...")

    url = "https://www.a101.com.tr/market"

    html = get_page(url)

    if not html:

        print(
            "A101: sayfa alınamadı."
        )

        return False

    soup = BeautifulSoup(
        html,
        "html.parser"
    )

    page_text = soup.get_text(
        " ",
        strip=True
    )

    if not product_matches(
        product,
        page_text
    ):

        print(
            "A101: ürün bulunamadı."
        )

        return False

    prices = extract_prices(page_text)

    if not prices:

        print(
            "A101: ürün bulundu fakat fiyat bulunamadı."
        )

        return False

    price = min(prices)

    print(
        f"A101 fiyatı: {price:.2f} TL"
    )

    return save_price(
        product,
        "A101",
        price
    )


# =========================================================
# FİYAT KONTROLÜ
# =========================================================

def update_product(product):

    print("")
    print("--------------------------------------")

    print(
        "Ürün:",
        product.get("name", "")
    )

    print(
        "Marka:",
        product.get("brand", "")
    )

    print(
        "Miktar:",
        product.get("quantity", "")
    )

    print(
        "Barkod:",
        product.get("barcode", "")
    )

    print("--------------------------------------")

    sok_ok = scan_sok(product)

    a101_ok = scan_a101(product)

    print("")

    if sok_ok or a101_ok:

        print(
            "Ürün için en az bir fiyat kaydedildi."
        )

    else:

        print(
            "Bu ürün için fiyat bulunamadı."
        )


# =========================================================
# TÜM ÜRÜNLERİ GÜNCELLE
# =========================================================

def update_products():

    print("")
    print("======================================")
    print("UCUZA OTOMATİK FİYAT MOTORU")
    print("======================================")
    print("")

    products = get_products()

    if not products:

        print(
            "Firestore'da products koleksiyonunda ürün bulunamadı."
        )

        print("")
        print(
            "Fiyat kontrolü yapılmadı."
        )

        return

    print("")

    for product in products:

        try:

            update_product(product)

        except Exception as e:

            print("")
            print(
                f"Ürün işlenirken hata oluştu: {e}"
            )
            print("")

    print("")
    print("======================================")
    print("FİYAT KONTROLÜ TAMAMLANDI")
    print("======================================")
    print("")


# =========================================================
# MAIN
# =========================================================

if __name__ == "__main__":

    update_products()
