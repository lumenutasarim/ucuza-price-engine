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
# HTTP SESSION
# ============================================================

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 "
        "(KHTML, like Gecko) "
        "Chrome/139.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,"
        "application/xml;q=0.9,image/avif,image/webp,"
        "*/*;q=0.8"
    ),
    "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "Upgrade-Insecure-Requests": "1",
    "Referer": "https://www.a101.com.tr/",
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

    # 2.299,00
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

    name = clean_name(name)

    if not name:
        return None

    # Barkod yoksa ürün adından stabil ID
    if not barcode:

        barcode = normalize(name).replace(
            " ",
            "-"
        )

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
# FIRESTORE FİYAT KAYDET
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
# A101 ÜRÜN KEŞFİ
# ============================================================

def discover_a101():

    print("")
    print("=" * 60)
    print("A101 ÜRÜNLERİ KEŞFEDİLİYOR")
    print("=" * 60)

    products = []

    urls = [
        "https://www.a101.com.tr/",
        "https://www.a101.com.tr/market",
        "https://www.a101.com.tr/arama?k=a",
    ]

    for url in urls:

        try:

            print("")
            print("A101 taranıyor:")
            print(url)

            response = session.get(
                url,
                timeout=30
            )

            print(
                "A101 HTTP:",
                response.status_code
            )

            if response.status_code != 200:

                print(
                    "A101 sayfası alınamadı."
                )

                continue

            html = response.text

            print(
                "A101 HTML:",
                len(html),
                "karakter"
            )


            # =================================================
            # JSON-LD
            # =================================================

            json_blocks = re.findall(
                r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>'
                r'(.*?)'
                r'</script>',
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

                        item_type = item.get(
                            "@type",
                            ""
                        )

                        if item_type != "Product":
                            continue

                        name = clean_name(
                            item.get(
                                "name",
                                ""
                            )
                        )

                        if not name:
                            continue

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
                            source="A101",
                        )

                        if product and price:

                            products.append(
                                (
                                    product,
                                    price,
                                    url
                                )
                            )

                except Exception:
                    continue


            # =================================================
            # SAYFA METNİ
            # =================================================

            page_text = re.sub(
                r"<script.*?</script>",
                " ",
                html,
                flags=re.S | re.I
            )

            page_text = re.sub(
                r"<style.*?</style>",
                " ",
                page_text,
                flags=re.S | re.I
            )

            page_text = re.sub(
                r"<[^>]+>",
                " ",
                page_text
            )

            page_text = re.sub(
                r"\s+",
                " ",
                page_text
            )

            page_text = page_text.strip()


            # =================================================
            # A101 FİYAT FORMATLARI
            #
            # Örnek:
            #
            # Ürün adı ₺119,00
            #
            # Ürün adı ₺249,00 ₺199,00
            # =================================================

            pattern = re.compile(
                r'([A-Za-zÇĞİÖŞÜçğıöşü0-9%'
                r'&\-\+\(\)/,.\'’" ]{4,150}?)'
                r'\s*₺\s*'
                r'([0-9]{1,3}'
                r'(?:\.[0-9]{3})?'
                r'(?:,[0-9]{1,2})?)',
                re.I
            )

            matches = pattern.findall(
                page_text
            )


            print(
                "A101 fiyat eşleşmesi:",
                len(matches)
            )


            for name, price in matches:

                name = clean_name(name)

                if len(name) < 3:
                    continue

                # Menü/başlık gibi gereksiz kayıtları ele
                bad_words = [
                    "tümünü gör",
                    "sepete ekle",
                    "önerilen",
                    "fiyat",
                    "indirim",
                    "market",
                    "ürün bulundu",
                    "peşin fiyatına",
                ]

                normalized_name = normalize(
                    name
                )

                skip = False

                for bad in bad_words:

                    if normalize(bad) in normalized_name:

                        skip = True
                        break

                if skip:
                    continue


                parsed = parse_price(
                    price
                )

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


    # ============================================================
    # FİYATLARI FIRESTORE'A YAZ
    # ============================================================

    saved = 0

    for product, price, url in products:

        if save_price(
            product,
            "A101",
            price,
            url
        ):

            saved += 1


    print("")
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
# ŞOK
# ============================================================

def discover_sok():

    print("")
    print("=" * 60)
    print("ŞOK ÜRÜNLERİ KEŞFEDİLİYOR")
    print("=" * 60)

    products = []

    url = (
        "https://www.sokmarket.com.tr/"
    )

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


        # JSON-LD
        json_blocks = re.findall(
            r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>'
            r'(.*?)'
            r'</script>',
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

                    if item.get(
                        "@type"
                    ) != "Product":
                        continue

                    name = clean_name(
                        item.get(
                            "name",
                            ""
                        )
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

                    if product and price:

                        products.append(
                            (
                                product,
                                price,
                                url
                            )
                        )

            except Exception:
                continue


        # Sayfa metni
        page_text = re.sub(
            r"<[^>]+>",
            " ",
            html
        )

        page_text = re.sub(
            r"\s+",
            " ",
            page_text
        )


        pattern = re.compile(
            r'([A-ZÇĞİÖŞÜ'
            r'a-zçğıöşü0-9%'
            r' \-+*/().,&]{3,150}?)'
            r'\s+'
            r'([0-9]{1,5}'
            r'(?:[.,][0-9]{1,2})?)'
            r'\s*₺',
            re.I
        )

        matches = pattern.findall(
            page_text
        )


        for name, price in matches:

            name = clean_name(name)

            if len(name) < 3:
                continue

            parsed = parse_price(
                price
            )

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
# FIRESTORE ÜRÜNLERİ
# ============================================================

def get_firestore_products():

    print("")
    print(
        "Firestore ürünleri kontrol ediliyor..."
    )

    products = []

    docs = (
        db.collection("products")
        .stream()
    )

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


    # A101
    a101_products = discover_a101()


    # ŞOK
    sok_products = discover_sok()


    # Firestore
    products = get_firestore_products()


    print("")
    print("=" * 60)
    print("SONUÇ")
    print("=" * 60)

    print(
        "A101 kayıtları:",
        len(a101_products)
    )

    print(
        "ŞOK kayıtları:",
        len(sok_products)
    )

    print(
        "Firestore ürünleri:",
        len(products)
    )

    print("=" * 60)


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":

    update_products()
