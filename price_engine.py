import os
import json
import re
import time
import html as html_lib
from urllib.parse import urljoin, urlparse

import requests
import firebase_admin
from firebase_admin import credentials, firestore


# ============================================================
# UCUZA - OTOMATİK FİYAT MOTORU
# FINAL v3
#
# A101 YOK
#
# ŞOK
# BİM
# MİGROS
# CARREFOURSA
# TARIM KREDİ
# HAKMAR
# FİLE
#
# Bir market hata verirse diğer marketler devam eder.
# ============================================================

print("=" * 75)
print("UCUZA OTOMATİK FİYAT MOTORU")
print("ŞOK + BİM + MİGROS + CARREFOURSA + TARIM KREDİ + HAKMAR + FİLE")
print("=" * 75)


# ============================================================
# FIREBASE
# ============================================================

service_account = os.environ.get("FIREBASE_SERVICE_ACCOUNT")

if not service_account:
    raise RuntimeError(
        "FIREBASE_SERVICE_ACCOUNT bulunamadı."
    )

try:
    cred = credentials.Certificate(
        json.loads(service_account)
    )
except Exception as e:
    raise RuntimeError(
        "FIREBASE_SERVICE_ACCOUNT JSON okunamadı: "
        + str(e)
    )

if not firebase_admin._apps:
    firebase_admin.initialize_app(cred)

db = firestore.client()


# ============================================================
# HTTP
# ============================================================

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
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
}

session = requests.Session()
session.headers.update(HEADERS)


# ============================================================
# MARKETLER
# ============================================================

MARKETS = {

    "SOK": {
        "name": "ŞOK",
        "display": "ŞOK",
        "urls": [
            "https://www.sokmarket.com.tr/"
        ],
    },

    "BIM": {
        "name": "BİM",
        "display": "BİM",
        "urls": [
            "https://www.bim.com.tr/"
        ],
    },

    "MIGROS": {
        "name": "Migros",
        "display": "MİGROS",
        "urls": [
            "https://www.migros.com.tr/"
        ],
    },

    "CARREFOURSA": {
        "name": "CarrefourSA",
        "display": "CARREFOURSA",
        "urls": [
            "https://www.carrefoursa.com/"
        ],
    },

    "TARIM_KREDI": {
        "name": "Tarım Kredi",
        "display": "TARIM KREDİ",
        "urls": [
            "https://www.tkkoop.com.tr/"
        ],
    },

    "HAKMAR": {
        "name": "Hakmar",
        "display": "HAKMAR",
        "urls": [
            "https://www.hakmarexpress.com.tr/"
        ],
    },

    "FILE": {
        "name": "File",
        "display": "FİLE",
        "urls": [
            "https://www.file.com.tr/"
        ],
    },
}


# ============================================================
# GENEL AYARLAR
# ============================================================

REQUEST_TIMEOUT = 30

# Her market için aşırı sayfa taramamak için sınır.
MAX_PAGES_PER_MARKET = 12

REQUEST_DELAY = 1.5


# ============================================================
# NORMALIZE
# ============================================================

def normalize(text):

    if text is None:
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


# ============================================================
# TEMİZ İSİM
# ============================================================

def clean_name(name):

    if not name:
        return ""

    name = html_lib.unescape(
        str(name)
    )

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

    name = name.strip()

    return name


# ============================================================
# FİYAT
# ============================================================

def parse_price(value):

    if value is None:
        return None

    value = str(value).strip()

    if not value:
        return None

    value = (
        value
        .replace("₺", "")
        .replace("TL", "")
        .replace("tl", "")
        .strip()
    )

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

        # Aşırı büyük hatalı değerleri engelle
        if price > 1000000:
            return None

        return price

    except Exception:

        return None


# ============================================================
# ÜRÜN ID
# ============================================================

def product_id(barcode, name):

    if barcode:

        barcode = str(
            barcode
        ).strip()

        if barcode:
            return barcode

    normalized = normalize(
        name
    )

    if not normalized:
        return ""

    return normalized.replace(
        " ",
        "-"
    )


# ============================================================
# UNIQUE
# ============================================================

def unique_products(products):

    result = {}

    for item in products:

        if not item:
            continue

        name = clean_name(
            item.get(
                "name",
                ""
            )
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

        result[pid] = item

    return list(
        result.values()
    )


# ============================================================
# URL NORMALİZASYONU
# ============================================================

def normalize_url(url):

    if not url:
        return ""

    url = url.split("#")[0]

    return url.rstrip("/")


# ============================================================
# AYNI DOMAIN Mİ?
# ============================================================

def same_domain(base_url, target_url):

    try:

        base_host = urlparse(
            base_url
        ).netloc.lower()

        target_host = urlparse(
            target_url
        ).netloc.lower()

        if target_host.startswith(
            "www."
        ):
            target_host = target_host[4:]

        if base_host.startswith(
            "www."
        ):
            base_host = base_host[4:]

        return (
            target_host == base_host
            or target_host.endswith(
                "." + base_host
            )
        )

    except Exception:

        return False


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

    name = clean_name(
        name
    )

    if not name:
        return None

    barcode = product_id(
        barcode,
        name
    )

    if not barcode:
        return None

    ref = (
        db
        .collection("products")
        .document(str(barcode))
    )

    data = {
        "barcode": str(barcode),
        "name": name,
        "brand": clean_name(
            brand
        ),
        "quantity": clean_name(
            quantity
        ),
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

    data = {
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
    }

    ref.set(
        data,
        merge=True
    )

    print(
        "[FIYAT] "
        + store
        + " | "
        + product["name"]
        + " | "
        + f"{price:.2f} TL"
    )

    return True


# ============================================================
# JSON-LD
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

        # Bazı sitelerde JSON bozuk olabilir.
        try:

            data = json.loads(
                block
            )

        except Exception:

            continue

        objects = []

        if isinstance(
            data,
            dict
        ):

            objects.append(
                data
            )

            graph = data.get(
                "@graph"
            )

            if isinstance(
                graph,
                list
            ):

                objects.extend(
                    graph
                )

        elif isinstance(
            data,
            list
        ):

            objects.extend(
                data
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

                is_product = any(
                    str(x).lower()
                    == "product"
                    for x in item_type
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

            sku = (
                item.get("sku")
                or item.get("gtin")
                or item.get("gtin13")
                or item.get("gtin12")
                or ""
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

            elif isinstance(
                offers,
                list
            ):

                for offer in offers:

                    if not isinstance(
                        offer,
                        dict
                    ):
                        continue

                    price = (
                        offer.get(
                            "price"
                        )
                        or
                        offer.get(
                            "lowPrice"
                        )
                    )

                    if price:
                        break

            products.append(
                {
                    "barcode": sku,
                    "name": name,
                    "brand": brand,
                    "quantity": quantity,
                    "source": source,
                    "price": price,
                }
            )

    return products


# ============================================================
# META / OPEN GRAPH ÜRÜN BİLGİLERİ
# ============================================================

def extract_meta_products(
    html,
    source
):

    products = []

    title_match = re.search(
        r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\'](.*?)["\']',
        html,
        re.I | re.S
    )

    price_match = re.search(
        r'<meta[^>]+property=["\']product:price:amount["\'][^>]+content=["\'](.*?)["\']',
        html,
        re.I | re.S
    )

    if not title_match:
        return products

    name = clean_name(
        title_match.group(1)
    )

    price = None

    if price_match:

        price = parse_price(
            price_match.group(1)
        )

    if name:

        products.append(
            {
                "barcode": "",
                "name": name,
                "brand": "",
                "quantity": "",
                "source": source,
                "price": price,
            }
        )

    return products


# ============================================================
# GENEL HTML ÜRÜN/FİYAT ÇIKARICI
# ============================================================

def extract_text_products(
    html,
    source
):

    products = []

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
        r"<noscript.*?</noscript>",
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

    patterns = [

        # Ürün 99,90 ₺
        re.compile(
            r"([A-ZÇĞİÖŞÜ0-9][^₺]{3,180}?)"
            r"\s+"
            r"([0-9]{1,7}"
            r"(?:[.,][0-9]{1,2})?)"
            r"\s*₺",
            re.I
        ),

        # Ürün ₺99,90
        re.compile(
            r"([A-ZÇĞİÖŞÜ0-9][^₺]{3,180}?)"
            r"\s*₺"
            r"\s*"
            r"([0-9]{1,7}"
            r"(?:[.,][0-9]{1,2})?)",
            re.I
        ),

        # Ürün 99,90 TL
        re.compile(
            r"([A-ZÇĞİÖŞÜ0-9][^T₺]{3,180}?)"
            r"\s+"
            r"([0-9]{1,7}"
            r"(?:[.,][0-9]{1,2})?)"
            r"\s*(?:TL|tl)",
            re.I
        ),
    ]

    bad_words = [
        "filtre",
        "sırala",
        "sepete ekle",
        "ürün bulundu",
        "ürünler",
        "fiyat aralığı",
        "tümünü gör",
        "önerilen",
        "kampanyalar",
        "giriş yap",
        "üye ol",
        "ana sayfa",
        "kategori",
        "kategoriler",
        "alışveriş sepeti",
    ]

    for pattern in patterns:

        try:
            matches = pattern.findall(
                text
            )
        except Exception:
            continue

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

            if len(name) > 180:

                name = name[-180:]

            normalized = normalize(
                name
            )

            if any(
                normalize(word)
                in normalized
                for word in bad_words
            ):
                continue

            # Çok kısa ürün adlarını alma.
            if len(name) < 3:
                continue

            # URL veya HTML kalıntısı
            if "http://" in name.lower():
                continue

            if "https://" in name.lower():
                continue

            products.append(
                {
                    "barcode": "",
                    "name": name,
                    "brand": "",
                    "quantity": "",
                    "source": source,
                    "price": price,
                }
            )

    return products


# ============================================================
# SAYFADAN ÜRÜN ÇIKAR
# ============================================================

def extract_products(
    html,
    source
):

    products = []

    try:

        products.extend(
            extract_jsonld_products(
                html,
                source
            )
        )

    except Exception as e:

        print(
            "[JSON-LD] HATA:",
            str(e)
        )

    try:

        products.extend(
            extract_meta_products(
                html,
                source
            )
        )

    except Exception as e:

        print(
            "[META] HATA:",
            str(e)
        )

    try:

        products.extend(
            extract_text_products(
                html,
                source
            )
        )

    except Exception as e:

        print(
            "[TEXT] HATA:",
            str(e)
        )

    return unique_products(
        products
    )


# ============================================================
# LINKLERİ ÇIKAR
# ============================================================

def extract_links(
    html,
    base_url
):

    links = []

    matches = re.findall(
        r'<a[^>]+href=["\']([^"\']+)["\']',
        html,
        re.I
    )

    for href in matches:

        href = html_lib.unescape(
            href
        ).strip()

        if not href:
            continue

        if href.startswith(
            "javascript:"
        ):
            continue

        if href.startswith(
            "mailto:"
        ):
            continue

        if href.startswith(
            "tel:"
        ):
            continue

        full_url = normalize_url(
            urljoin(
                base_url,
                href
            )
        )

        if not full_url:
            continue

        if not same_domain(
            base_url,
            full_url
        ):
            continue

        lower = full_url.lower()

        # Statik dosyaları atla
        bad_extensions = (
            ".jpg",
            ".jpeg",
            ".png",
            ".gif",
            ".svg",
            ".webp",
            ".css",
            ".js",
            ".pdf",
            ".zip",
        )

        if lower.endswith(
            bad_extensions
        ):
            continue

        links.append(
            full_url
        )

    # Tekilleştir
    return list(
        dict.fromkeys(
            links
        )
    )


# ============================================================
# MARKETİ TEK TEK TARA
# ============================================================

def crawl_market(
    market_code,
    config
):

    display = config[
        "display"
    ]

    print("")
    print("=" * 75)
    print(display + " ÜRÜNLERİ OTOMATİK KEŞFEDİLİYOR")
    print("=" * 75)

    discovered = []

    queue = []

    visited = set()

    for url in config[
        "urls"
    ]:

        queue.append(
            normalize_url(
                url
            )
        )

    page_count = 0

    while queue and page_count < MAX_PAGES_PER_MARKET:

        url = queue.pop(0)

        if not url:
            continue

        if url in visited:
            continue

        visited.add(
            url
        )

        page_count += 1

        try:

            print("")
            print(
                "["
                + display
                + "] Taranıyor:",
                url
            )

            response = session.get(
                url,
                timeout=REQUEST_TIMEOUT,
                allow_redirects=True
            )

            print(
                "["
                + display
                + "] HTTP:",
                response.status_code
            )

            print(
                "["
                + display
                + "] HTML:",
                len(response.text),
                "karakter"
            )

            # ------------------------------------------------
            # 403 / 401
            # ------------------------------------------------

            if response.status_code in (
                401,
                403,
                429
            ):

                print(
                    "["
                    + display
                    + "] Site erişimi engelledi."
                )

                print(
                    "["
                    + display
                    + "] Bu market atlanıyor."
                )

                continue

            if response.status_code != 200:

                print(
                    "["
                    + display
                    + "] Sayfa alınamadı."
                )

                continue

            final_url = normalize_url(
                response.url
            )

            products = extract_products(
                response.text,
                market_code
            )

            for item in products:

                item["url"] = final_url

                discovered.append(
                    item
                )

            print(
                "["
                + display
                + "] Bu sayfada ürün:",
                len(products)
            )

            # ------------------------------------------------
            # Yeni linkler
            # ------------------------------------------------

            links = extract_links(
                response.text,
                final_url
            )

            for link in links:

                if link in visited:
                    continue

                if link in queue:
                    continue

                # Ürün/kategori olma ihtimali yüksek linkler
                lower = link.lower()

                interesting_words = [
                    "urun",
                    "ürün",
                    "product",
                    "kategori",
                    "category",
                    "market",
                    "kampanya",
                    "aktuel",
                    "aktüel",
                    "gida",
                    "gıda",
                    "icecek",
                    "içecek",
                    "atistirmalik",
                    "atıştırmalık",
                    "sutu",
                    "süt",
                ]

                if any(
                    word in lower
                    for word in interesting_words
                ):

                    queue.append(
                        link
                    )

            time.sleep(
                REQUEST_DELAY
            )

        except requests.exceptions.RequestException as e:

            print(
                "["
                + display
                + "] HTTP HATASI:",
                str(e)
            )

            continue

        except Exception as e:

            print(
                "["
                + display
                + "] HATA:",
                str(e)
            )

            continue

    discovered = unique_products(
        discovered
    )

    # ========================================================
    # FIRESTORE
    # ========================================================

    saved_products = 0
    saved_prices = 0

    for item in discovered:

        try:

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
                source=market_code,
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

                success = save_price(
                    product,
                    market_code,
                    price,
                    item.get(
                        "url",
                        ""
                    )
                )

                if success:
                    saved_prices += 1

        except Exception as e:

            print(
                "["
                + display
                + "] Firestore ürün hatası:",
                str(e)
            )

            continue

    print("")
    print(
        "["
        + display
        + "] Sayfa sayısı:",
        page_count
    )

    print(
        "["
        + display
        + "] Keşfedilen ürün:",
        len(discovered)
    )

    print(
        "["
        + display
        + "] Kaydedilen ürün:",
        saved_products
    )

    print(
        "["
        + display
        + "] Kaydedilen fiyat:",
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
# MARKETLERİN ÖZETİ
# ============================================================

def print_market_summary(
    results
):

    print("")
    print("=" * 75)
    print("MARKET SONUÇLARI")
    print("=" * 75)

    for code, data in results.items():

        print(
            data["display"]
            + " -> "
            + str(
                data["count"]
            )
            + " ürün"
        )

    print("=" * 75)


# ============================================================
# ANA MOTOR
# ============================================================

def update_products():

    print("")
    print("=" * 75)
    print("UCUZA OTOMATİK FİYAT MOTORU BAŞLADI")
    print("=" * 75)

    print("")
    print(
        "A101 devre dışı."
    )

    print(
        "Aktif market sayısı:",
        len(MARKETS)
    )

    print("")

    results = {}

    # ========================================================
    # TÜM MARKETLER
    # ========================================================

    for market_code, config in MARKETS.items():

        try:

            products = crawl_market(
                market_code,
                config
            )

            results[
                market_code
            ] = {
                "display": config[
                    "display"
                ],
                "count": len(
                    products
                ),
            }

        except Exception as e:

            print("")
            print(
                "["
                + config["display"]
                + "] MOTOR HATASI:"
            )

            print(
                str(e)
            )

            print(
                "["
                + config["display"]
                + "] ATLANIYOR."
            )

            results[
                market_code
            ] = {
                "display": config[
                    "display"
                ],
                "count": 0,
            }

            continue

    # ========================================================
    # ÖZET
    # ========================================================

    print_market_summary(
        results
    )

    # ========================================================
    # FIRESTORE
    # ========================================================

    products = get_firestore_products()

    print("")
    print("=" * 75)
    print("SONUÇ")
    print("=" * 75)

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

    print("")
    print(
        "Not: Bir market 403/429 veya başka bir hata verirse"
    )

    print(
        "diğer marketler çalışmaya devam eder."
    )

    print("=" * 75)
    print("UCUZA FİYAT MOTORU TAMAMLANDI")
    print("=" * 75)


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":

    try:

        update_products()

    except KeyboardInterrupt:

        print("")
        print(
            "Motor kullanıcı tarafından durduruldu."
        )

    except Exception as e:

        print("")
        print("=" * 75)
        print("KRİTİK HATA")
        print("=" * 75)
        print(
            str(e)
        )
        print("=" * 75)

        raise
