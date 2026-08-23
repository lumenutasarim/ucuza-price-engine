import os
import json
import re
import time
import requests

import firebase_admin
from firebase_admin import credentials, firestore


# ============================================================
# UCUZA - OTOMATİK FİYAT MOTORU
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
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 "
        "(KHTML, like Gecko) "
        "Chrome/139.0 Safari/537.36"
    ),
    "Accept-Language": "tr-TR,tr;q=0.9,en;q=0.8",
    "Accept": (
        "text/html,application/xhtml+xml,"
        "application/xml;q=0.9,*/*;q=0.8"
    ),
    "Cache-Control": "no-cache",
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

    text = re.sub(
        r"[^a-z0-9 ]",
        " ",
        text
    )

    text = re.sub(
        r"\s+",
        " ",
        text
    )

    return text.strip()


def clean_name(name):

    if not name:
        return ""

    name = re.sub(
        r"<[^>]+>",
        " ",
        str(name)
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

    value = value.replace("₺", "")
    value = value.replace("TL", "")
    value = value.replace("tl", "")
    value = value.replace("TRY", "")

    value = value.strip()

    # 1.299,90
    if "," in value:

        value = value.replace(
            ".",
            ""
        )

        value = value.replace(
            ",",
            "."
        )

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


def make_product_id(
    name,
    barcode=""
):

    if barcode:
        return str(barcode)

    normalized = normalize(name)

    if not normalized:
        return None

    return normalized.replace(
        " ",
        "-"
    )


# ============================================================
# FIRESTORE PRODUCT
# ============================================================

def save_product(
    barcode,
    name,
    brand="",
    quantity="",
    source=""
):

    name = clean_name(name)

    if not name:
        return None

    product_id = make_product_id(
        name,
        barcode
    )

    if not product_id:
        return None

    ref = (
        db
        .collection("products")
        .document(product_id)
    )

    data = {
        "barcode": str(product_id),
        "name": name,
        "brand": clean_name(brand),
        "quantity": clean_name(quantity),
        "source": source,
        "updatedAt": firestore.SERVER_TIMESTAMP,
    }

    ref.set(
        data,
        merge=True
    )

    return {
        "barcode": str(product_id),
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
        db
        .collection("prices")
        .document(str(barcode))
        .collection("stores")
        .document(store)
    )

    ref.set(
        {
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
        },
        merge=True
    )

    print(
        f"[FIYAT] {store} | "
        f"{product['name']} | "
        f"{price:.2f} TL"
    )

    return True


# ============================================================
# JSON-LD OKU
# ============================================================

def extract_jsonld(html):

    results = []

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

            data = json.loads(
                block
            )

            if isinstance(
                data,
                list
            ):

                results.extend(
                    data
                )

            elif isinstance(
                data,
                dict
            ):

                results.append(
                    data
                )

        except Exception:
            continue

    return results


# ============================================================
# A101 ÜRÜN ÇIKAR
# ============================================================

def parse_a101_jsonld(
    html,
    source_url
):

    products = []

    objects = extract_jsonld(
        html
    )

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

        # @type bazen liste olabilir
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
                item_type
                == "Product"
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

        elif isinstance(
            brand_data,
            str
        ):

            brand = brand_data

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
                or offers.get(
                    "lowPrice"
                )
            )

        product = save_product(
            barcode=sku,
            name=name,
            brand=brand,
            source="A101"
        )

        if product and price:

            products.append(
                (
                    product,
                    price,
                    source_url
                )
            )

    return products


# ============================================================
# A101 METİN FİYAT ÇIKARMA
# ============================================================

def parse_a101_text(
    html,
    source_url
):

    products = []

    # HTML etiketlerini kaldır
    text = re.sub(
        r"<[^>]+>",
        " ",
        html
    )

    text = re.sub(
        r"\s+",
        " ",
        text
    )

    # --------------------------------------------------------
    # Ürün + ₺ fiyat
    # --------------------------------------------------------

    pattern = re.compile(
        r"([A-Za-zÇĞİÖŞÜçğıöşü0-9"
        r"%&'’+\-\/().,\" ]{4,160}?)"
        r"\s*₺\s*"
        r"([0-9]{1,6}"
        r"(?:[.,][0-9]{1,2})?)",
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

        # Çok uzun / anlamsız kayıtları at
        if len(name) < 3:
            continue

        if len(name) > 180:
            continue

        # Menü / açıklama gibi metinleri at
        bad_words = [
            "tümünü gör",
            "için",
            "alışveriş",
            "kategori",
            "markalar",
            "kampanya",
        ]

        normalized = normalize(
            name
        )

        if any(
            word in normalized
            for word in bad_words
        ):
            continue

        product = save_product(
            barcode="",
            name=name,
            source="A101"
        )

        if product:

            products.append(
                (
                    product,
                    price,
                    source_url
                )
            )

    return products


# ============================================================
# A101 OTOMATİK KEŞİF
# ============================================================

def discover_a101():

    print("")
    print("=" * 70)
    print("A101 ÜRÜNLERİ OTOMATİK KEŞFEDİLİYOR")
    print("=" * 70)

    all_products = []

    urls = [
        "https://www.a101.com.tr/",
        "https://www.a101.com.tr/market",
        "https://www.a101.com.tr/market?ind=True&page=2",
    ]

    seen = set()

    for url in urls:

        try:

            print("")
            print(
                "A101 taranıyor:",
                url
            )

            response = session.get(
                url,
                timeout=40
            )

            print(
                "A101 HTTP:",
                response.status_code
            )

            if response.status_code != 200:
                continue

            html = response.text

            # ------------------------------------------------
            # JSON-LD
            # ------------------------------------------------

            jsonld_products = (
                parse_a101_jsonld(
                    html,
                    url
                )
            )

            # ------------------------------------------------
            # Normal HTML
            # ------------------------------------------------

            text_products = (
                parse_a101_text(
                    html,
                    url
                )
            )

            combined = (
                jsonld_products
                + text_products
            )

            for product, price, source_url in combined:

                key = (
                    product["barcode"],
                    "A101"
                )

                if key in seen:
                    continue

                seen.add(key)

                all_products.append(
                    (
                        product,
                        price,
                        source_url
                    )
                )

            print(
                "A101 bu sayfadan bulunan:",
                len(combined)
            )

            time.sleep(2)

        except Exception as e:

            print(
                "A101 hata:",
                str(e)
            )

    # --------------------------------------------------------
    # FIRESTORE
    # --------------------------------------------------------

    saved = 0

    for product, price, url in all_products:

        if save_price(
            product,
            "A101",
            price,
            url
        ):
            saved += 1

    print("")
    print(
        "A101 toplam keşfedilen:",
        len(all_products)
    )

    print(
        "A101 toplam kaydedilen fiyat:",
        saved
    )

    return all_products


# ============================================================
# ŞOK JSON-LD
# ============================================================

def parse_sok_jsonld(
    html,
    source_url
):

    products = []

    objects = extract_jsonld(
        html
    )

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
                item_type
                == "Product"
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

        elif isinstance(
            brand_data,
            str
        ):

            brand = brand_data

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
                or offers.get(
                    "lowPrice"
                )
            )

        product = save_product(
            barcode=item.get(
                "sku",
                ""
            ),
            name=name,
            brand=brand,
            source="SOK"
        )

        if product and price:

            products.append(
                (
                    product,
                    price,
                    source_url
                )
            )

    return products


# ============================================================
# ŞOK METİN
# ============================================================

def parse_sok_text(
    html,
    source_url
):

    products = []

    text = re.sub(
        r"<[^>]+>",
        " ",
        html
    )

    text = re.sub(
        r"\s+",
        " ",
        text
    )

    pattern = re.compile(
        r"([A-Za-zÇĞİÖŞÜçğıöşü0-9"
        r"%&'’+\-\/().,\" ]{4,160}?)"
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

        if not name or not price:
            continue

        if len(name) < 3:
            continue

        if len(name) > 180:
            continue

        product = save_product(
            barcode="",
            name=name,
            source="SOK"
        )

        if product:

            products.append(
                (
                    product,
                    price,
                    source_url
                )
            )

    return products


# ============================================================
# ŞOK OTOMATİK KEŞİF
# ============================================================

def discover_sok():

    print("")
    print("=" * 70)
    print("ŞOK ÜRÜNLERİ OTOMATİK KEŞFEDİLİYOR")
    print("=" * 70)

    products = []

    url = (
        "https://www.sokmarket.com.tr/"
    )

    try:

        response = session.get(
            url,
            timeout=40
        )

        print(
            "ŞOK HTTP:",
            response.status_code
        )

        if response.status_code != 200:
            return products

        html = response.text

        jsonld_products = (
            parse_sok_jsonld(
                html,
                url
            )
        )

        text_products = (
            parse_sok_text(
                html,
                url
            )
        )

        combined = (
            jsonld_products
            + text_products
        )

        seen = set()

        for product, price, source_url in combined:

            key = (
                product["barcode"],
                "ŞOK"
            )

            if key in seen:
                continue

            seen.add(key)

            products.append(
                (
                    product,
                    price,
                    source_url
                )
            )

        saved = 0

        for product, price, source_url in products:

            if save_price(
                product,
                "ŞOK",
                price,
                source_url
            ):
                saved += 1

        print("")
        print(
            "ŞOK toplam keşfedilen:",
            len(products)
        )

        print(
            "ŞOK toplam kaydedilen:",
            saved
        )

    except Exception as e:

        print(
            "ŞOK hata:",
            str(e)
        )

    return products


# ============================================================
# FIRESTORE ÜRÜNLER
# ============================================================

def get_firestore_products():

    print("")
    print(
        "Firestore ürünleri kontrol ediliyor..."
    )

    products = []

    docs = (
        db
        .collection("products")
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

    print(
        "Firestore ürün sayısı:",
        len(products)
    )

    return products


# ============================================================
# ÖZET
# ============================================================

def print_summary():

    print("")
    print("=" * 70)
    print("FİYAT MOTORU ÖZET")
    print("=" * 70)

    products = get_firestore_products()

    print(
        "Toplam ürün:",
        len(products)
    )

    print("")
    print(
        "A101 + ŞOK fiyat motoru tamamlandı."
    )

    print("=" * 70)


# ============================================================
# ANA MOTOR
# ============================================================

def update_products():

    print("")
    print("=" * 70)
    print("UCUZA OTOMATİK FİYAT MOTORU BAŞLADI")
    print("=" * 70)

    # --------------------------------------------------------
    # A101
    # --------------------------------------------------------

    discover_a101()

    # --------------------------------------------------------
    # ŞOK
    # --------------------------------------------------------

    discover_sok()

    # --------------------------------------------------------
    # ÖZET
    # --------------------------------------------------------

    print_summary()


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":

    update_products()
