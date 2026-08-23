import os
import json
import re
import time
import requests
from urllib.parse import urljoin

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

service_account = os.environ.get(
    "FIREBASE_SERVICE_ACCOUNT"
)

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
    "Accept-Language": (
        "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,"
        "application/xml;q=0.9,image/avif,image/webp,"
        "*/*;q=0.8"
    ),
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
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

    name = name.replace(
        "&nbsp;",
        " "
    )

    name = name.replace(
        "&amp;",
        "&"
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

    value = value.replace(
        "₺",
        ""
    )

    value = value.replace(
        "TL",
        ""
    )

    value = value.replace(
        "tl",
        ""
    )

    value = value.replace(
        "TRY",
        ""
    )

    value = value.strip()

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

    normalized = normalize(
        name
    )

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

    name = clean_name(
        name
    )

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
        "brand": clean_name(
            brand
        ),
        "quantity": clean_name(
            quantity
        ),
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
        "brand": clean_name(
            brand
        ),
        "quantity": clean_name(
            quantity
        ),
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

    price = parse_price(
        price
    )

    if price is None:
        return False

    barcode = product[
        "barcode"
    ]

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
            "productName": product[
                "name"
            ],
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
# JSON-LD
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

        try:

            data = json.loads(
                block.strip()
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
# A101 - ÜRÜN LINKLERİNİ BUL
# ============================================================

def find_a101_product_links(
    html
):

    links = []

    # A101 ürün URL yapısı:
    # /kategori/urun-adi_p-12345678

    pattern = re.compile(
        r'href=["\']([^"\']*_p-\d+[^"\']*)["\']',
        re.I
    )

    matches = pattern.findall(
        html
    )

    for link in matches:

        link = link.strip()

        if not link:
            continue

        if link.startswith(
            "//"
        ):

            link = (
                "https:"
                + link
            )

        elif link.startswith(
            "/"
        ):

            link = urljoin(
                "https://www.a101.com.tr/",
                link
            )

        elif not link.startswith(
            "http"
        ):

            link = urljoin(
                "https://www.a101.com.tr/",
                link
            )

        if (
            "a101.com.tr"
            not in link
        ):
            continue

        if "_p-" not in link:
            continue

        if link not in links:

            links.append(
                link
            )

    return links


# ============================================================
# A101 - ÜRÜN SAYFASI OKU
# ============================================================

def parse_a101_product_page(
    html,
    url
):

    name = ""
    brand = ""
    barcode = ""
    quantity = ""
    price = None

    # --------------------------------------------------------
    # JSON-LD
    # --------------------------------------------------------

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

        if not name:

            name = clean_name(
                item.get(
                    "name",
                    ""
                )
            )

        if not barcode:

            barcode = str(
                item.get(
                    "sku",
                    ""
                )
                or item.get(
                    "mpn",
                    ""
                )
            )

        brand_data = item.get(
            "brand",
            ""
        )

        if not brand:

            if isinstance(
                brand_data,
                dict
            ):

                brand = clean_name(
                    brand_data.get(
                        "name",
                        ""
                    )
                )

            elif isinstance(
                brand_data,
                str
            ):

                brand = clean_name(
                    brand_data
                )

        offers = item.get(
            "offers",
            {}
        )

        if isinstance(
            offers,
            dict
        ):

            if price is None:

                price = parse_price(
                    offers.get(
                        "price"
                    )
                    or offers.get(
                        "lowPrice"
                    )
                )

    # --------------------------------------------------------
    # Ürün kodu
    # --------------------------------------------------------

    if not barcode:

        code_match = re.search(
            r"Ürün\s*Kodu\s*:\s*"
            r"([0-9]{5,20})",
            html,
            re.I
        )

        if code_match:

            barcode = (
                code_match.group(1)
            )

    # --------------------------------------------------------
    # HTML'den görünen metin
    # --------------------------------------------------------

    text = re.sub(
        r"<script.*?</script>",
        " ",
        html,
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
    # Ürün adı
    # --------------------------------------------------------

    if not name:

        match = re.search(
            r"(?:#\s*)?"
            r"([A-Za-zÇĞİÖŞÜçğıöşü0-9"
            r"&'’.,+\-/() ]{4,180}?)"
            r"\s+Ürün\s*Kodu\s*:",
            text,
            re.I
        )

        if match:

            name = clean_name(
                match.group(1)
            )

    # --------------------------------------------------------
    # Ürün kodu
    # --------------------------------------------------------

    if not barcode:

        match = re.search(
            r"Ürün\s*Kodu\s*:\s*"
            r"([0-9]{5,20})",
            text,
            re.I
        )

        if match:

            barcode = (
                match.group(1)
            )

    # --------------------------------------------------------
    # Marka
    # --------------------------------------------------------

    if not brand:

        match = re.search(
            r"Marka\s*:\s*"
            r"([A-Za-zÇĞİÖŞÜçğıöşü0-9"
            r"&'’.\- ]{2,100})",
            text,
            re.I
        )

        if match:

            brand = clean_name(
                match.group(1)
            )

    # --------------------------------------------------------
    # FİYAT
    # --------------------------------------------------------

    if price is None:

        # Örnek:
        # ₺22.990,00
        match = re.search(
            r"₺\s*"
            r"([0-9]{1,7}"
            r"(?:[.,][0-9]{1,2})?)",
            text,
            re.I
        )

        if match:

            price = parse_price(
                match.group(1)
            )

    # Bazı sayfalarda fiyat
    # rakam + ₺ şeklinde olabilir.

    if price is None:

        match = re.search(
            r"([0-9]{1,7}"
            r"(?:[.,][0-9]{1,2})?)"
            r"\s*₺",
            text,
            re.I
        )

        if match:

            price = parse_price(
                match.group(1)
            )

    if not name:
        return None

    if price is None:
        return None

    product = save_product(
        barcode=barcode,
        name=name,
        brand=brand,
        quantity=quantity,
        source="A101"
    )

    if not product:
        return None

    return (
        product,
        price,
        url
    )


# ============================================================
# A101 - ANA SAYFA / MARKET SAYFASI
# ============================================================

def parse_a101_listing(
    html,
    url
):

    results = []

    # --------------------------------------------------------
    # 1. JSON-LD
    # --------------------------------------------------------

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

        offers = item.get(
            "offers",
            {}
        )

        price = None

        if isinstance(
            offers,
            dict
        ):

            price = parse_price(
                offers.get(
                    "price"
                )
                or offers.get(
                    "lowPrice"
                )
            )

        if price is None:
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

        product = save_product(
            barcode=item.get(
                "sku",
                ""
            ),
            name=name,
            brand=brand,
            source="A101"
        )

        if product:

            results.append(
                (
                    product,
                    price,
                    url
                )
            )

    # --------------------------------------------------------
    # 2. Normal HTML metni
    # --------------------------------------------------------

    text = re.sub(
        r"<script.*?</script>",
        " ",
        html,
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
    # A101 sayfalarında:
    #
    # Ürün Adı ₺119,00
    #
    # veya
    #
    # Ürün Adı 119,00₺
    # --------------------------------------------------------

    patterns = [

        re.compile(
            r"([A-Za-zÇĞİÖŞÜçğıöşü0-9"
            r"&'’.,+\-/()%* ]{4,160}?)"
            r"\s*₺\s*"
            r"([0-9]{1,7}"
            r"(?:[.,][0-9]{1,2})?)",
            re.I
        ),

        re.compile(
            r"([A-Za-zÇĞİÖŞÜçğıöşü0-9"
            r"&'’.,+\-/()%* ]{4,160}?)"
            r"\s+"
            r"([0-9]{1,7}"
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

            if price is None:
                continue

            if len(name) < 3:
                continue

            if len(name) > 160:
                continue

            # Gereksiz başlıkları at
            bad = [
                "tümünü gör",
                "ana sayfa",
                "alışveriş",
                "kategori",
                "kampanya",
                "filtrele",
                "sırala",
                "ürün bulundu",
                "fiyat aralığı",
            ]

            normalized = normalize(
                name
            )

            if any(
                x in normalized
                for x in bad
            ):
                continue

            product = save_product(
                barcode="",
                name=name,
                source="A101"
            )

            if product:

                results.append(
                    (
                        product,
                        price,
                        url
                    )
                )

    return results


# ============================================================
# A101 - ANA KEŞİF
# ============================================================

def discover_a101():

    print("")
    print("=" * 70)
    print("A101 ÜRÜNLERİ OTOMATİK KEŞFEDİLİYOR")
    print("=" * 70)

    urls = [
        "https://www.a101.com.tr/",
        "https://www.a101.com.tr/market",
    ]

    all_results = []
    seen_products = set()
    product_links = set()

    # --------------------------------------------------------
    # 1. LİSTE SAYFALARI
    # --------------------------------------------------------

    for url in urls:

        try:

            print("")
            print(
                "[A101] Taranıyor:",
                url
            )

            response = session.get(
                url,
                timeout=45
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

            if response.status_code != 200:
                continue

            html = response.text

            # ------------------------------------------------
            # Ürün linklerini topla
            # ------------------------------------------------

            links = find_a101_product_links(
                html
            )

            print(
                "[A101] Ürün linki:",
                len(links)
            )

            for link in links:

                product_links.add(
                    link
                )

            # ------------------------------------------------
            # Liste ürünleri
            # ------------------------------------------------

            listing_results = (
                parse_a101_listing(
                    html,
                    url
                )
            )

            for result in listing_results:

                product, price, source_url = result

                key = (
                    product["barcode"],
                    "A101"
                )

                if key in seen_products:
                    continue

                seen_products.add(
                    key
                )

                all_results.append(
                    result
                )

            time.sleep(2)

        except Exception as e:

            print(
                "[A101] Liste hata:",
                str(e)
            )

    # --------------------------------------------------------
    # 2. ÜRÜN SAYFALARINI OKU
    # --------------------------------------------------------

    # Çok fazla sayfa istemiyoruz.
    # İlk 100 ürün sayfasını tarıyoruz.

    product_links = list(
        product_links
    )[:100]

    print("")
    print(
        "[A101] Tekil ürün sayfası taranacak:",
        len(product_links)
    )

    for index, url in enumerate(
        product_links,
        start=1
    ):

        try:

            print(
                f"[A101] Ürün {index}/"
                f"{len(product_links)}"
            )

            response = session.get(
                url,
                timeout=30
            )

            if response.status_code != 200:
                continue

            result = (
                parse_a101_product_page(
                    response.text,
                    url
                )
            )

            if result:

                product, price, source_url = result

                key = (
                    product["barcode"],
                    "A101"
                )

                if key not in seen_products:

                    seen_products.add(
                        key
                    )

                    all_results.append(
                        result
                    )

                    print(
                        "[A101 BULUNDU]",
                        product["name"],
                        "|",
                        f"{price:.2f} TL"
                    )

            time.sleep(
                0.4
            )

        except Exception as e:

            print(
                "[A101] Ürün hata:",
                str(e)
            )

    # --------------------------------------------------------
    # 3. FIRESTORE'A YAZ
    # --------------------------------------------------------

    saved = 0

    for product, price, url in all_results:

        if save_price(
            product,
            "A101",
            price,
            url
        ):
            saved += 1

    print("")
    print("=" * 70)
    print(
        "A101 keşfedilen:",
        len(all_results)
    )
    print(
        "A101 kaydedilen fiyat:",
        saved
    )
    print("=" * 70)

    return all_results


# ============================================================
# ŞOK - JSON-LD
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

            brand = clean_name(
                brand_data.get(
                    "name",
                    ""
                )
            )

        elif isinstance(
            brand_data,
            str
        ):

            brand = clean_name(
                brand_data
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

            price = parse_price(
                offers.get(
                    "price"
                )
                or offers.get(
                    "lowPrice"
                )
            )

        if price is None:
            continue

        product = save_product(
            barcode=item.get(
                "sku",
                ""
            ),
            name=name,
            brand=brand,
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
# ŞOK - METİN
# ============================================================

def parse_sok_text(
    html,
    source_url
):

    products = []

    text = re.sub(
        r"<script.*?</script>",
        " ",
        html,
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
        r"([A-Za-zÇĞİÖŞÜçğıöşü0-9"
        r"%&'’+\-\/().,\" ]{4,160}?)"
        r"\s+"
        r"([0-9]{1,7}"
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

        if price is None:
            continue

        if len(name) < 3:
            continue

        if len(name) > 160:
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
# ŞOK - KEŞİF
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
            timeout=45
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
            return products

        html = response.text

        json_products = (
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
            json_products
            + text_products
        )

        seen = set()

        for result in combined:

            product, price, source_url = result

            key = (
                product["barcode"],
                "ŞOK"
            )

            if key in seen:
                continue

            seen.add(
                key
            )

            products.append(
                result
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
            "ŞOK keşfedilen:",
            len(products)
        )

        print(
            "ŞOK kaydedilen:",
            saved
        )

    except Exception as e:

        print(
            "[ŞOK] Hata:",
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
    print("UCUZA FİYAT MOTORU ÖZET")
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

    # A101
    discover_a101()

    # ŞOK
    discover_sok()

    # Özet
    print_summary()


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":

    update_products()
