import os
import json
import re
import time
import requests

import firebase_admin
from firebase_admin import credentials, firestore


# ============================================================
# UCUZA - OTOMATİK FİYAT MOTORU
# FINAL
# ============================================================

print("=" * 60)
print("UCUZA OTOMATİK FİYAT MOTORU")
print("=" * 60)


# ============================================================
# FIREBASE
# ============================================================

service_account = os.environ.get("FIREBASE_SERVICE_ACCOUNT")

if not service_account:
    raise RuntimeError("FIREBASE_SERVICE_ACCOUNT bulunamadı.")

cred = credentials.Certificate(json.loads(service_account))

if not firebase_admin._apps:
    firebase_admin.initialize_app(cred)

db = firestore.client()


# ============================================================
# HTTP
# ============================================================

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 "
        "(KHTML, like Gecko) "
        "Chrome/139.0 Safari/537.36"
    ),
    "Accept-Language": "tr-TR,tr;q=0.9,en;q=0.8",
    "Accept": "text/html,application/json,application/xhtml+xml",
}


session = requests.Session()
session.headers.update(HEADERS)


# ============================================================
# YARDIMCI
# ============================================================

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


def parse_price(value):

    if value is None:
        return None

    value = str(value).strip()

    value = value.replace("₺", "")
    value = value.replace("TL", "")
    value = value.replace("tl", "")
    value = value.strip()

    # 1.299,90
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


def clean_name(name):

    if not name:
        return ""

    name = re.sub(r"\s+", " ", str(name))

    return name.strip()


# ============================================================
# FIRESTORE ÜRÜN KAYDET
# ============================================================

def save_product(
    barcode,
    name,
    brand="",
    quantity="",
    source=""
):

    if not name:
        return None

    if not barcode:
        # Barkod yoksa ürün adına göre stabil ID
        barcode = normalize(name).replace(" ", "-")

    ref = db.collection("products").document(str(barcode))

    data = {
        "barcode": str(barcode),
        "name": clean_name(name),
        "brand": clean_name(brand),
        "quantity": clean_name(quantity),
        "source": source,
        "updatedAt": firestore.SERVER_TIMESTAMP,
    }

    ref.set(data, merge=True)

    return {
        "barcode": str(barcode),
        "name": clean_name(name),
        "brand": clean_name(brand),
        "quantity": clean_name(quantity),
    }


# ============================================================
# FIRESTORE FİYAT KAYDET
# ============================================================

def save_price(product, store, price, url=""):

    price = parse_price(price)

    if price is None:
        return False

    barcode = product["barcode"]

    ref = (
        db.collection("prices")
        .document(str(barcode))
        .collection("stores")
        .document(store)
    )

    ref.set(
        {
            "barcode": str(barcode),
            "productName": product["name"],
            "brand": product.get("brand", ""),
            "quantity": product.get("quantity", ""),
            "store": store,
            "price": price,
            "currency": "TRY",
            "url": url,
            "updatedAt": firestore.SERVER_TIMESTAMP,
        },
        merge=True,
    )

    print(
        f"[FIYAT] {store} | "
        f"{product['name']} | "
        f"{price:.2f} TL"
    )

    return True


# ============================================================
# OTOMATİK ÜRÜN KEŞFİ
# ============================================================

def discover_a101():

    print("")
    print("=" * 60)
    print("A101 ÜRÜNLERİ OTOMATİK KEŞFEDİLİYOR")
    print("=" * 60)

    products = []

    urls = [
        "https://www.a101.com.tr/",
        "https://www.a101.com.tr/market",
    ]

    for url in urls:

        try:

            print("Taraniyor:", url)

            response = session.get(
                url,
                timeout=30
            )

            if response.status_code != 200:
                print(
                    "A101 HTTP:",
                    response.status_code
                )
                continue

            html = response.text

            # JSON-LD
            json_blocks = re.findall(
                r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
                html,
                re.S | re.I
            )

            for block in json_blocks:

                try:

                    data = json.loads(block)

                    objects = []

                    if isinstance(data, dict):
                        objects.append(data)

                    elif isinstance(data, list):
                        objects.extend(data)

                    for item in objects:

                        if not isinstance(item, dict):
                            continue

                        if item.get("@type") == "Product":

                            name = item.get("name", "")

                            offers = item.get(
                                "offers",
                                {}
                            )

                            price = None

                            if isinstance(
                                offers,
                                dict
                            ):
                                price = offers.get(
                                    "price"
                                )

                            product = save_product(
                                barcode=item.get(
                                    "sku",
                                    ""
                                ),
                                name=name,
                                brand=(
                                    item.get(
                                        "brand",
                                        {}
                                    ).get(
                                        "name",
                                        ""
                                    )
                                    if isinstance(
                                        item.get(
                                            "brand",
                                            {}
                                        ),
                                        dict
                                    )
                                    else ""
                                ),
                                source="A101",
                            )

                            if product:

                                products.append(
                                    (
                                        product,
                                        price,
                                        url
                                    )
                                )

                except Exception:
                    continue

            # Genel ürün adı + fiyat yakalama
            pattern = re.compile(
                r'([A-ZÇĞİÖŞÜ][^<]{3,100}?)'
                r'\s*₺\s*'
                r'([0-9]{1,5}(?:[.,][0-9]{1,2})?)',
                re.I
            )

            matches = pattern.findall(html)

            for name, price in matches:

                name = clean_name(
                    re.sub(
                        r"<[^>]+>",
                        " ",
                        name
                    )
                )

                if len(name) < 3:
                    continue

                parsed = parse_price(price)

                if not parsed:
                    continue

                product = save_product(
                    barcode="",
                    name=name,
                    source="A101",
                )

                if product:

                    products.append(
                        (
                            product,
                            parsed,
                            url
                        )
                    )

            time.sleep(2)

        except Exception as e:

            print(
                "A101 hata:",
                str(e)
            )

    # Fiyatları kaydet
    saved = 0

    for product, price, url in products:

        if price:

            if save_price(
                product,
                "A101",
                price,
                url
            ):
                saved += 1

    print(
        "A101 keşfedilen kayıt:",
        len(products)
    )

    print(
        "A101 kaydedilen fiyat:",
        saved
    )

    return products


# ============================================================
# ŞOK OTOMATİK ÜRÜN KEŞFİ
# ============================================================

def discover_sok():

    print("")
    print("=" * 60)
    print("ŞOK ÜRÜNLERİ OTOMATİK KEŞFEDİLİYOR")
    print("=" * 60)

    products = []

    url = "https://www.sokmarket.com.tr/"

    try:

        response = session.get(
            url,
            timeout=30
        )

        print(
            "ŞOK HTTP:",
            response.status_code
        )

        if response.status_code != 200:
            return products

        html = response.text

        # JSON-LD ürünleri
        json_blocks = re.findall(
            r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
            html,
            re.S | re.I
        )

        for block in json_blocks:

            try:

                data = json.loads(block)

                objects = []

                if isinstance(data, dict):
                    objects.append(data)

                elif isinstance(data, list):
                    objects.extend(data)

                for item in objects:

                    if not isinstance(item, dict):
                        continue

                    if item.get("@type") != "Product":
                        continue

                    name = item.get(
                        "name",
                        ""
                    )

                    offers = item.get(
                        "offers",
                        {}
                    )

                    price = None

                    if isinstance(
                        offers,
                        dict
                    ):
                        price = offers.get(
                            "price"
                        )

                    brand = ""

                    brand_data = item.get(
                        "brand",
                        {}
                    )

                    if isinstance(
                        brand_data,
                        dict
                    ):
                        brand = brand_data.get(
                            "name",
                            ""
                        )

                    product = save_product(
                        barcode=item.get(
                            "sku",
                            ""
                        ),
                        name=name,
                        brand=brand,
                        source="SOK",
                    )

                    if product:

                        products.append(
                            (
                                product,
                                price,
                                url
                            )
                        )

            except Exception:
                continue

        # Genel metin fiyatları
        page_text = re.sub(
            r"\s+",
            " ",
            re.sub(
                r"<[^>]+>",
                " ",
                html
            )
        )

        pattern = re.compile(
            r'([A-ZÇĞİÖŞÜ][A-Za-zÇĞİÖŞÜçğıöşü0-9 %*+\-]{3,100}?)'
            r'\s+'
            r'([0-9]{1,5}(?:[.,][0-9]{1,2})?)\s*₺',
            re.I
        )

        matches = pattern.findall(
            page_text
        )

        for name, price in matches:

            name = clean_name(name)

            if len(name) < 3:
                continue

            parsed = parse_price(price)

            if not parsed:
                continue

            product = save_product(
                barcode="",
                name=name,
                source="SOK",
            )

            if product:

                products.append(
                    (
                        product,
                        parsed,
                        url
                    )
                )

        saved = 0

        for product, price, source_url in products:

            if price:

                if save_price(
                    product,
                    "ŞOK",
                    price,
                    source_url
                ):
                    saved += 1

        print(
            "ŞOK keşfedilen kayıt:",
            len(products)
        )

        print(
            "ŞOK kaydedilen fiyat:",
            saved
        )

    except Exception as e:

        print(
            "ŞOK hata:",
            str(e)
        )

    return products


# ============================================================
# FIRESTORE'DAKİ ÜRÜNLERİ KONTROL
# ============================================================

def get_firestore_products():

    print("")
    print(
        "Firestore ürünleri kontrol ediliyor..."
    )

    products = []

    docs = db.collection(
        "products"
    ).stream()

    for doc in docs:

        data = doc.to_dict()

        if not data:
            continue

        if not data.get("name"):
            continue

        products.append(
            {
                "barcode": data.get(
                    "barcode",
                    doc.id
                ),
                "name": data.get(
                    "name",
                    ""
                ),
                "brand": data.get(
                    "brand",
                    ""
                ),
                "quantity": data.get(
                    "quantity",
                    ""
                ),
            }
        )

    print(
        "Firestore ürün sayısı:",
        len(products)
    )

    return products


# ============================================================
# ANA MOTOR
# ============================================================

def update_products():

    print("")
    print("=" * 60)
    print("UCUZA OTOMATİK FİYAT MOTORU BAŞLADI")
    print("=" * 60)

    # --------------------------------------------------------
    # 1. ÖNCE OTOMATİK ÜRÜN KEŞFİ
    # --------------------------------------------------------

    discover_a101()

    discover_sok()

    # --------------------------------------------------------
    # 2. FIRESTORE ÜRÜNLERİ
    # --------------------------------------------------------

    products = get_firestore_products()

    # --------------------------------------------------------
    # 3. SONUÇ
    # --------------------------------------------------------

    if not products:

        print("")
        print(
            "Henüz otomatik keşfedilebilen ürün bulunamadı."
        )
        print(
            "Fiyat kontrolü yapılmadı."
        )

        return

    print("")
    print(
        "Toplam ürün:",
        len(products)
    )

    print("")
    print(
        "Otomatik ürün/fiyat sistemi tamamlandı."
    )

    print("=" * 60)


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":
    update_products()
