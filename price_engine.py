import os
import json
import re
import time
import html as html_lib
from urllib.parse import quote

import requests
import firebase_admin
from firebase_admin import credentials, firestore


# ============================================================
# UCUZA - OTOMATİK FİYAT MOTORU
# FINAL v2
# A101 + ŞOK
# ============================================================

print("=" * 70)
print("UCUZA OTOMATİK FİYAT MOTORU")
print("A101 + ŞOK")
print("=" * 70)


# ============================================================
# FIREBASE
# ============================================================

service_account = os.environ.get("FIREBASE_SERVICE_ACCOUNT")

if not service_account:
    raise RuntimeError(
        "FIREBASE_SERVICE_ACCOUNT bulunamadı."
    )

cred = credentials.Certificate(
    json.loads(service_account)
)

if not firebase_admin._apps:
    firebase_admin.initialize_app(cred)

db = firestore.client()


# ============================================================
# HTTP
# ============================================================

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 "
        "(KHTML, like Gecko) "
        "Chrome/139.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,"
        "application/xml;q=0.9,image/avif,"
        "image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "Upgrade-Insecure-Requests": "1",
}

session = requests.Session()
session.headers.update(HEADERS)


# ============================================================
# AYARLAR
# ============================================================

A101_BASE = "https://www.a101.com.tr"
SOK_BASE = "https://www.sokmarket.com.tr"

A101_URLS = [
    "https://www.a101.com.tr/",
    "https://www.a101.com.tr/market",
    "https://www.a101.com.tr/liste/ekstraya-ozel-urunler",
]

SOK_URLS = [
    "https://www.sokmarket.com.tr/",
]


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


def clean_name(name):

    if not name:
        return ""

    name = html_lib.unescape(str(name))

    name = re.sub(
        r"<[^>]+>",
        " ",
        name
    )

    name = re.sub(
        r"\s+",
        " ",
        name
    )

    return name.strip()


def parse_price(value):

    if value is None:
        return None

    value = str(value).strip()

    if not value:
        return None

    value = value.replace("₺", "")
    value = value.replace("TL", "")
    value = value.replace("tl", "")
    value = value.strip()

    # Türkçe fiyat:
    # 1.299,90
    if "," in value:
        value = value.replace(".", "")
        value = value.replace(",", ".")

    value = re.sub(
        r"[^0-9.]",
        "",
        value
    )

    try:

        price = float(value)

        if price <= 0:
            return None

        return price

    except Exception:
        return None


def product_id(barcode, name):

    if barcode:
        value = str(barcode).strip()

        if value:
            return value

    normalized = normalize(name)

    if not normalized:
        return ""

    return normalized.replace(
        " ",
        "-"
    )


def unique_products(products):

    result = {}

    for item in products:

        if not item:
            continue

        name = clean_name(
            item.get("name", "")
        )

        if not name:
            continue

        barcode = item.get(
            "barcode",
            ""
        )

        pid = product_id(
            barcode,
            name
        )

        if not pid:
            continue

        item["barcode"] = pid
        item["name"] = name

        # Aynı ürünü tekrar ekleme
        result[pid] = item

    return list(result.values())


# ============================================================
# FIRESTORE PRODUCT
# ============================================================

def save_product(
    barcode,
    name,
    brand="",
    quantity="",
    source="",
    url=""
):

    name = clean_name(name)

    if not name:
        return None

    barcode = product_id(
        barcode,
        name
    )

    if not barcode:
        return None

    ref = (
        db.collection("products")
        .document(str(barcode))
    )

    data = {
        "barcode": str(barcode),
        "name": name,
        "brand": clean_name(brand),
        "quantity": clean_name(quantity),
        "source": source,
        "url": url,
        "updatedAt": firestore.SERVER_TIMESTAMP,
    }

    ref.set(
        data,
        merge=True
    )

    return {
        "barcode": str(barcode),
        "name": name,
        "brand": clean_name(brand),
        "quantity": clean_name(quantity),
    }


# ============================================================
# FIRESTORE PRICE
# ============================================================

def save_price(
    product,
    store,
    price,
    url=""
):

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

    data = {
        "barcode": str(barcode),
        "productName": product["name"],
        "brand": product.get(
            "brand",
            ""
        ),
        "quantity": product.get(
            "quantity",
            ""
        ),
        "store": store,
        "price": price,
        "currency": "TRY",
        "url": url,
        "updatedAt": firestore.SERVER_TIMESTAMP,
    }

    ref.set(
        data,
        merge=True
    )

    print(
        f"[FIYAT] {store} | "
        f"{product['name']} | "
        f"{price:.2f} TL"
    )

    return True


# ============================================================
# HTML'DEN JSON-LD ÜRÜNLERİ
# ============================================================

def extract_jsonld_products(
    html,
    source
):

    products = []

    blocks = re.findall(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>'
        r'(.*?)'
        r'</script>',
        html,
        re.S | re.I
    )

    for block in blocks:

        block = block.strip()

        if not block:
            continue

        try:

            data = json.loads(block)

        except Exception:

            continue

        objects = []

        if isinstance(data, dict):

            objects.append(data)

            # @graph
            graph = data.get(
                "@graph"
            )

            if isinstance(
                graph,
                list
            ):
                objects.extend(graph)

        elif isinstance(data, list):

            objects.extend(data)

        for item in objects:

            if not isinstance(
                item,
                dict
            ):
                continue

            item_type = item.get(
                "@type",
                ""
            )

            if isinstance(
                item_type,
                list
            ):
                is_product = (
                    "Product"
                    in item_type
                )
            else:
                is_product = (
                    str(item_type).lower()
                    == "product"
                )

            if not is_product:
                continue

            name = clean_name(
                item.get(
                    "name",
                    ""
                )
            )

            if not name:
                continue

            sku = item.get(
                "sku",
                ""
            )

            brand = ""

            brand_data = item.get(
                "brand",
                ""
            )

            if isinstance(
                brand_data,
                dict
            ):
                brand = brand_data.get(
                    "name",
                    ""
                )
            else:
                brand = brand_data

            quantity = ""

            offers = item.get(
                "offers",
                {}
            )

            price = None

            if isinstance(
                offers,
                dict
            ):

                price = (
                    offers.get(
                        "price"
                    )
                    or
                    offers.get(
                        "lowPrice"
                    )
                )

            product = {
                "barcode": sku,
                "name": name,
                "brand": brand,
                "quantity": quantity,
                "source": source,
                "price": price,
            }

            products.append(
                product
            )

    return products


# ============================================================
# A101 METİN ÜRÜN/FİYAT ÇIKARMA
# ============================================================

def extract_a101_products(
    html,
    source_url
):

    products = []

    # --------------------------------------------------------
    # 1. JSON-LD
    # --------------------------------------------------------

    jsonld = extract_jsonld_products(
        html,
        "A101"
    )

    for item in jsonld:

        item["url"] = source_url

        products.append(
            item
        )

    # --------------------------------------------------------
    # 2. HTML'i okunabilir metne çevir
    # --------------------------------------------------------

    text = html_lib.unescape(
        html
    )

    text = re.sub(
        r"<script.*?</script>",
        " ",
        text,
        flags=re.S | re.I
    )

    text = re.sub(
        r"<style.*?</style>",
        " ",
        text,
        flags=re.S | re.I
    )

    text = re.sub(
        r"<[^>]+>",
        " ",
        text
    )

    text = re.sub(
        r"\s+",
        " ",
        text
    )

    # --------------------------------------------------------
    # 3. A101 fiyat formatları
    # --------------------------------------------------------

    patterns = [

        # Ürün ... ₺1.299,00
        re.compile(
            r"(.{3,180}?)"
            r"\s*₺\s*"
            r"([0-9]{1,6}"
            r"(?:[.,][0-9]{1,2})?)",
            re.I
        ),

        # Ürün ... 1.299,00 ₺
        re.compile(
            r"(.{3,180}?)"
            r"\s+"
            r"([0-9]{1,6}"
            r"(?:[.,][0-9]{1,2})?)"
            r"\s*₺",
            re.I
        ),
    ]

    for pattern in patterns:

        matches = pattern.findall(
            text
        )

        for name, price in matches:

            name = clean_name(
                name
            )

            price = parse_price(
                price
            )

            if not name:
                continue

            if not price:
                continue

            # Çok uzun / anlamsız satırları ele
            if len(name) > 180:
                name = name[-180:]

            # Menü/filtre gibi şeyleri at
            bad_words = [
                "filtre",
                "sırala",
                "sepete ekle",
                "ürün bulundu",
                "fiyat aralığı",
                "tümünü gör",
                "önerilen",
            ]

            normalized_name = normalize(
                name
            )

            if any(
                normalize(word)
                in normalized_name
                for word in bad_words
            ):
                continue

            # Başlangıçta gereksiz ifadeleri temizle
            prefixes = [
                "peşin fiyatına",
                "hadi kredi ile",
            ]

            for prefix in prefixes:

                if normalized_name.startswith(
                    normalize(prefix)
                ):

                    parts = re.split(
                        r"\s+",
                        name,
                        maxsplit=4
                    )

                    if len(parts) >= 2:
                        name = " ".join(
                            parts[2:]
                        )

            name = clean_name(
                name
            )

            if len(name) < 3:
                continue

            products.append(
                {
                    "barcode": "",
                    "name": name,
                    "brand": "",
                    "quantity": "",
                    "source": "A101",
                    "price": price,
                    "url": source_url,
                }
            )

    return unique_products(
        products
    )


# ============================================================
# A101 KEŞİF
# ============================================================

def discover_a101():

    print("")
    print("=" * 70)
    print("A101 ÜRÜNLERİ OTOMATİK KEŞFEDİLİYOR")
    print("=" * 70)

    discovered = []

    for url in A101_URLS:

        try:

            print("")
            print(
                "[A101] Taranıyor:",
                url
            )

            response = session.get(
                url,
                timeout=40,
                allow_redirects=True
            )

            print(
                "[A101] HTTP:",
                response.status_code
            )

            print(
                "[A101] HTML:",
                len(response.text),
                "karakter"
            )

            if response.status_code == 403:

                print(
                    "[A101] 403 engeli."
                )

                print(
                    "[A101] Bu sayfa atlanıyor."
                )

                continue

            if response.status_code != 200:

                print(
                    "[A101] Sayfa alınamadı."
                )

                continue

            products = extract_a101_products(
                response.text,
                response.url
            )

            print(
                "[A101] Bu sayfada ürün:",
                len(products)
            )

            discovered.extend(
                products
            )

            time.sleep(2)

        except Exception as e:

            print(
                "[A101] HATA:",
                str(e)
            )

    discovered = unique_products(
        discovered
    )

    saved_products = 0
    saved_prices = 0

    for item in discovered:

        product = save_product(
            barcode=item.get(
                "barcode",
                ""
            ),
            name=item.get(
                "name",
                ""
            ),
            brand=item.get(
                "brand",
                ""
            ),
            quantity=item.get(
                "quantity",
                ""
            ),
            source="A101",
            url=item.get(
                "url",
                ""
            )
        )

        if not product:
            continue

        saved_products += 1

        price = item.get(
            "price"
        )

        if price:

            if save_price(
                product,
                "A101",
                price,
                item.get(
                    "url",
                    ""
                )
            ):

                saved_prices += 1

    print("")
    print(
        "[A101] Keşfedilen ürün:",
        len(discovered)
    )

    print(
        "[A101] Kaydedilen ürün:",
        saved_products
    )

    print(
        "[A101] Kaydedilen fiyat:",
        saved_prices
    )

    return discovered


# ============================================================
# ŞOK ÜRÜN KEŞFİ
# ============================================================

def discover_sok():

    print("")
    print("=" * 70)
    print("ŞOK ÜRÜNLERİ OTOMATİK KEŞFEDİLİYOR")
    print("=" * 70)

    discovered = []

    for url in SOK_URLS:

        try:

            print("")
            print(
                "[ŞOK] Taranıyor:",
                url
            )

            response = session.get(
                url,
                timeout=40
            )

            print(
                "[ŞOK] HTTP:",
                response.status_code
            )

            print(
                "[ŞOK] HTML:",
                len(response.text),
                "karakter"
            )

            if response.status_code != 200:

                print(
                    "[ŞOK] Sayfa alınamadı."
                )

                continue

            html = response.text

            # JSON-LD
            jsonld = extract_jsonld_products(
                html,
                "SOK"
            )

            for item in jsonld:

                item["url"] = response.url

                discovered.append(
                    item
                )

            # Genel metin
            text = html_lib.unescape(
                html
            )

            text = re.sub(
                r"<script.*?</script>",
                " ",
                text,
                flags=re.S | re.I
            )

            text = re.sub(
                r"<style.*?</style>",
                " ",
                text,
                flags=re.S | re.I
            )

            text = re.sub(
                r"<[^>]+>",
                " ",
                text
            )

            text = re.sub(
                r"\s+",
                " ",
                text
            )

            pattern = re.compile(
                r"([A-ZÇĞİÖŞÜ][^₺]{3,150}?)"
                r"\s+"
                r"([0-9]{1,6}"
                r"(?:[.,][0-9]{1,2})?)"
                r"\s*₺",
                re.I
            )

            matches = pattern.findall(
                text
            )

            for name, price in matches:

                name = clean_name(
                    name
                )

                price = parse_price(
                    price
                )

                if not name:
                    continue

                if not price:
                    continue

                if len(name) > 180:
                    name = name[-180:]

                bad_words = [
                    "filtre",
                    "sırala",
                    "sepete ekle",
                    "ürün bulundu",
                    "fiyat aralığı",
                ]

                normalized = normalize(
                    name
                )

                if any(
                    normalize(word)
                    in normalized
                    for word in bad_words
                ):
                    continue

                discovered.append(
                    {
                        "barcode": "",
                        "name": name,
                        "brand": "",
                        "quantity": "",
                        "source": "SOK",
                        "price": price,
                        "url": response.url,
                    }
                )

            time.sleep(2)

        except Exception as e:

            print(
                "[ŞOK] HATA:",
                str(e)
            )

    discovered = unique_products(
        discovered
    )

    saved_products = 0
    saved_prices = 0

    for item in discovered:

        product = save_product(
            barcode=item.get(
                "barcode",
                ""
            ),
            name=item.get(
                "name",
                ""
            ),
            brand=item.get(
                "brand",
                ""
            ),
            quantity=item.get(
                "quantity",
                ""
            ),
            source="SOK",
            url=item.get(
                "url",
                ""
            )
        )

        if not product:
            continue

        saved_products += 1

        price = item.get(
            "price"
        )

        if price:

            if save_price(
                product,
                "ŞOK",
                price,
                item.get(
                    "url",
                    ""
                )
            ):

                saved_prices += 1

    print("")
    print(
        "[ŞOK] Keşfedilen ürün:",
        len(discovered)
    )

    print(
        "[ŞOK] Kaydedilen ürün:",
        saved_products
    )

    print(
        "[ŞOK] Kaydedilen fiyat:",
        saved_prices
    )

    return discovered


# ============================================================
# FIRESTORE ÜRÜNLERİ
# ============================================================

def get_firestore_products():

    print("")
    print(
        "Firestore ürünleri kontrol ediliyor..."
    )

    products = []

    try:

        docs = (
            db.collection(
                "products"
            )
            .stream()
        )

        for doc in docs:

            data = doc.to_dict()

            if not data:
                continue

            name = data.get(
                "name",
                ""
            )

            if not name:
                continue

            products.append(
                {
                    "barcode": data.get(
                        "barcode",
                        doc.id
                    ),
                    "name": name,
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

    except Exception as e:

        print(
            "Firestore okuma hatası:",
            str(e)
        )

    print(
        "Firestore ürün sayısı:",
        len(products)
    )

    return products


# ============================================================
# MOTOR
# ============================================================

def update_products():

    print("")
    print("=" * 70)
    print("UCUZA OTOMATİK FİYAT MOTORU BAŞLADI")
    print("=" * 70)

    # --------------------------------------------------------
    # A101
    # --------------------------------------------------------

    try:

        discover_a101()

    except Exception as e:

        print(
            "[A101] MOTOR HATASI:",
            str(e)
        )

        print(
            "[A101] ŞOK motoruna devam ediliyor."
        )

    # --------------------------------------------------------
    # ŞOK
    # --------------------------------------------------------

    try:

        discover_sok()

    except Exception as e:

        print(
            "[ŞOK] MOTOR HATASI:",
            str(e)
        )

    # --------------------------------------------------------
    # FIRESTORE
    # --------------------------------------------------------

    products = get_firestore_products()

    print("")
    print("=" * 70)
    print("SONUÇ")
    print("=" * 70)

    print(
        "Firestore toplam ürün:",
        len(products)
    )

    if products:

        print(
            "Ürün/fiyat sistemi çalıştı."
        )

    else:

        print(
            "Firestore'da ürün bulunamadı."
        )

    print("=" * 70)
    print("UCUZA FİYAT MOTORU TAMAMLANDI")
    print("=" * 70)


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":

    try:

        update_products()

    except Exception as e:

        print("")
        print("=" * 70)
        print("KRİTİK HATA")
        print("=" * 70)
        print(str(e))
        print("=" * 70)

        raise
