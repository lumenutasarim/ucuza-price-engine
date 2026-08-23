import os
import json
import re
import time
import hashlib
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup

import firebase_admin
from firebase_admin import credentials, firestore


# =========================================================
# UCUZA - FINAL PRICE ENGINE
# =========================================================
#
# Barkod:
#   YOK
#
# Manuel PRODUCTS listesi:
#   YOK
#
# Sahte fiyat:
#   YOK
#
# Sistem:
#   Market kataloglarını tarar
#   Ürünleri otomatik çıkarır
#   Fiyatları gerçek sayfadan almaya çalışır
#   Firestore'a kaydeder
#
# Firebase:
#   FIREBASE_SERVICE_ACCOUNT GitHub Secret kullanılır.
# =========================================================


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
except json.JSONDecodeError as e:
    raise RuntimeError(
        "FIREBASE_SERVICE_ACCOUNT geçerli JSON değil."
    ) from e


if not firebase_admin._apps:

    cred = credentials.Certificate(
        service_account_data
    )

    firebase_admin.initialize_app(
        cred
    )


db = firestore.client()


# =========================================================
# AYARLAR
# =========================================================

REQUEST_TIMEOUT = 30

REQUEST_DELAY = 1.0

MIN_PRICE = 0.50

MAX_PRICE = 100000.0

MAX_PRODUCTS_PER_STORE = 5000


# =========================================================
# MARKETLER
# =========================================================

MARKETS = {

    "ŞOK": {
        "url": "https://www.sokmarket.com.tr/market-c-10"
    },

    "A101": {
        "url": "https://www.a101.com.tr/market"
    }

}


# =========================================================
# HTTP
# =========================================================

HEADERS = {

    "User-Agent": (
        "Mozilla/5.0 "
        "(Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 "
        "(KHTML, like Gecko) "
        "Chrome/139.0.0.0 Safari/537.36"
    ),

    "Accept": (
        "text/html,"
        "application/xhtml+xml,"
        "application/xml;q=0.9,"
        "image/avif,"
        "image/webp,"
        "*/*;q=0.8"
    ),

    "Accept-Language":
        "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7",

    "Connection":
        "keep-alive"

}


session = requests.Session()

session.headers.update(
    HEADERS
)


# =========================================================
# NORMALIZE
# =========================================================

def normalize(text):

    if text is None:
        return ""

    text = str(text)

    text = text.lower()

    replacements = {

        "ç": "c",
        "ğ": "g",
        "ı": "i",
        "ö": "o",
        "ş": "s",
        "ü": "u",

        "â": "a",
        "î": "i",
        "û": "u"

    }

    for old, new in replacements.items():

        text = text.replace(
            old,
            new
        )

    text = re.sub(
        r"[^a-z0-9.,%/'\- ]",
        " ",
        text
    )

    text = re.sub(
        r"\s+",
        " ",
        text
    )

    return text.strip()


# =========================================================
# SLUG
# =========================================================

def make_slug(text):

    normalized = normalize(
        text
    )

    normalized = normalized.replace(
        "%",
        " yuzde "
    )

    normalized = re.sub(
        r"[^a-z0-9]+",
        "-",
        normalized
    )

    normalized = normalized.strip(
        "-"
    )

    if not normalized:

        normalized = "urun"

    return normalized[:120]


# =========================================================
# ÜRÜN ID
# =========================================================

def make_product_id(
    name,
    brand,
    quantity
):

    raw = "|".join(
        [
            normalize(name),
            normalize(brand),
            normalize(quantity)
        ]
    )

    return hashlib.sha256(
        raw.encode("utf-8")
    ).hexdigest()[:24]


# =========================================================
# FİYAT PARSE
# =========================================================

def parse_price(value):

    if value is None:
        return None

    value = str(value)

    value = (
        value
        .replace("₺", "")
        .replace("TL", "")
        .replace("tl", "")
        .replace("TRY", "")
        .strip()
    )

    value = re.sub(
        r"[^0-9,.\-]",
        "",
        value
    )

    if not value:

        return None

    try:

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

        # 1299.90
        elif value.count(".") == 1:

            parts = value.split(".")

            if (
                len(parts[-1]) == 3
                and len(parts[0]) <= 3
            ):

                value = value.replace(
                    ".",
                    ""
                )

        # 1.299.900
        elif value.count(".") > 1:

            value = value.replace(
                ".",
                ""
            )

        price = float(
            value
        )

        if price < MIN_PRICE:
            return None

        if price > MAX_PRICE:
            return None

        return round(
            price,
            2
        )

    except (ValueError, TypeError):

        return None


# =========================================================
# SAYFA AL
# =========================================================

def get_page(url):

    try:

        response = session.get(
            url,
            timeout=REQUEST_TIMEOUT
        )

        print(
            f"[HTTP] {response.status_code} "
            f"{url}"
        )

        if response.status_code != 200:

            print(
                f"[HTTP] Sayfa alınamadı: "
                f"{response.status_code}"
            )

            return None

        return response.text

    except requests.RequestException as e:

        print(
            f"[HTTP] Hata: {e}"
        )

        return None


# =========================================================
# JSON-LD ÜRÜNLERİ
# =========================================================

def extract_json_ld_products(
    soup
):

    products = []

    scripts = soup.find_all(
        "script",
        type="application/ld+json"
    )

    for script in scripts:

        raw = script.string

        if not raw:
            continue

        try:

            data = json.loads(
                raw
            )

        except Exception:

            continue

        candidates = []

        if isinstance(data, list):

            candidates.extend(
                data
            )

        elif isinstance(data, dict):

            candidates.append(
                data
            )

            graph = data.get(
                "@graph"
            )

            if isinstance(
                graph,
                list
            ):

                candidates.extend(
                    graph
                )

        for item in candidates:

            if not isinstance(
                item,
                dict
            ):
                continue

            item_type = item.get(
                "@type"
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

            name = item.get(
                "name"
            )

            if not name:
                continue

            offers = item.get(
                "offers"
            )

            price = None

            if isinstance(
                offers,
                dict
            ):

                price = offers.get(
                    "price"
                )

            elif isinstance(
                offers,
                list
            ):

                for offer in offers:

                    if isinstance(
                        offer,
                        dict
                    ):

                        price = offer.get(
                            "price"
                        )

                        if price is not None:
                            break

            price = parse_price(
                price
            )

            if price is None:
                continue

            brand = ""

            brand_data = item.get(
                "brand"
            )

            if isinstance(
                brand_data,
                dict
            ):

                brand = (
                    brand_data.get(
                        "name"
                    )
                    or ""
                )

            elif brand_data:

                brand = str(
                    brand_data
                )

            sku = (
                item.get("sku")
                or item.get("mpn")
                or ""
            )

            products.append(
                {
                    "name": str(name).strip(),
                    "brand": str(brand).strip(),
                    "quantity": "",
                    "price": price,
                    "sku": str(sku).strip()
                }
            )

    return products


# =========================================================
# HTML ÜRÜN KARTLARI
# =========================================================

def extract_html_products(
    soup
):

    products = []

    selectors = [

        "[data-product]",

        "[data-product-id]",

        "[data-testid*='product']",

        ".product",

        ".product-card",

        ".product-item",

        ".productBox",

        ".product-box",

        "article"

    ]

    seen = set()

    elements = []

    for selector in selectors:

        try:

            elements.extend(
                soup.select(
                    selector
                )
            )

        except Exception:

            continue

    for element in elements:

        text = element.get_text(
            " ",
            strip=True
        )

        if not text:
            continue

        if len(text) > 1000:
            continue

        price = None

        # -------------------------------------------------
        # Price attribute
        # -------------------------------------------------

        for attr in [

            "data-price",
            "data-product-price",
            "data-sale-price",
            "data-current-price"

        ]:

            value = element.get(
                attr
            )

            if value:

                price = parse_price(
                    value
                )

                if price is not None:
                    break

        # -------------------------------------------------
        # Fiyat metni
        # -------------------------------------------------

        if price is None:

            patterns = [

                r"₺\s*([0-9]{1,5}(?:[.,][0-9]{1,2})?)",

                r"([0-9]{1,5}(?:[.,][0-9]{1,2})?)\s*₺",

                r"([0-9]{1,5}(?:[.,][0-9]{1,2})?)\s*TL",

                r"TL\s*([0-9]{1,5}(?:[.,][0-9]{1,2})?)"

            ]

            for pattern in patterns:

                match = re.search(
                    pattern,
                    text,
                    re.IGNORECASE
                )

                if match:

                    price = parse_price(
                        match.group(1)
                    )

                    if price is not None:
                        break

        if price is None:
            continue

        # -------------------------------------------------
        # Ürün ismi
        # -------------------------------------------------

        name = ""

        for selector in [

            "[class*='product-name']",

            "[class*='productName']",

            "[class*='name']",

            "[class*='title']",

            "h2",

            "h3",

            "h4"

        ]:

            node = element.select_one(
                selector
            )

            if node:

                candidate = node.get_text(
                    " ",
                    strip=True
                )

                if (
                    candidate
                    and len(candidate) >= 3
                ):

                    name = candidate
                    break

        if not name:

            name = text

        # -------------------------------------------------
        # Temizlik
        # -------------------------------------------------

        name = re.sub(
            r"\s+",
            " ",
            name
        ).strip()

        if len(name) < 3:
            continue

        key = (
            normalize(name),
            price
        )

        if key in seen:
            continue

        seen.add(
            key
        )

        products.append(
            {
                "name": name,
                "brand": "",
                "quantity": "",
                "price": price,
                "sku": ""
            }
        )

        if len(products) >= MAX_PRODUCTS_PER_STORE:
            break

    return products


# =========================================================
# GENEL SAYFA ÜRÜN ÇIKARMA
# =========================================================

def extract_products(
    html
):

    soup = BeautifulSoup(
        html,
        "html.parser"
    )

    products = []

    # Öncelik JSON-LD
    products.extend(
        extract_json_ld_products(
            soup
        )
    )

    # HTML kartları
    products.extend(
        extract_html_products(
            soup
        )
    )

    # Aynı ürünleri temizle
    unique = {}

    for product in products:

        name = product.get(
            "name",
            ""
        )

        price = product.get(
            "price"
        )

        if not name:
            continue

        if price is None:
            continue

        key = (
            normalize(name),
            normalize(
                product.get(
                    "brand",
                    ""
                )
            ),
            price
        )

        unique[key] = product

    return list(
        unique.values()
    )


# =========================================================
# MARKA TAHMİNİ
# =========================================================

KNOWN_BRANDS = [

    "Sütaş",
    "İçim",
    "Pınar",
    "Ülker",
    "Eti",
    "Torku",
    "Filiz",
    "Barilla",
    "Çaykur",
    "Lipton",
    "Ariel",
    "OMO",
    "Persil",
    "Fairy",
    "Finish",
    "Nescafé",
    "Coca Cola",
    "Pepsi",
    "Erikli",
    "Hayat",
    "Saka",
    "Mis",
    "Dost",
    "Birşah",
    "Bili Bili",
    "Lider"

]


def detect_brand(
    name,
    current_brand=""
):

    if current_brand:

        return current_brand.strip()

    normalized_name = normalize(
        name
    )

    for brand in KNOWN_BRANDS:

        if normalize(
            brand
        ) in normalized_name:

            return brand

    return ""


# =========================================================
# MİKTAR TAHMİNİ
# =========================================================

def detect_quantity(
    name,
    current_quantity=""
):

    if current_quantity:

        return current_quantity.strip()

    patterns = [

        r"\b\d+(?:[.,]\d+)?\s*kg\b",

        r"\b\d+(?:[.,]\d+)?\s*g\b",

        r"\b\d+(?:[.,]\d+)?\s*ml\b",

        r"\b\d+(?:[.,]\d+)?\s*l\b",

        r"\b\d+\s*lt\b",

        r"\b\d+\s*li\b",

        r"\b\d+'\s*lu\b",

        r"\b\d+\s*lu\b",

        r"\b\d+\s*'lu\b"

    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            name,
            re.IGNORECASE
        )

        if match:

            return re.sub(
                r"\s+",
                " ",
                match.group(0)
            ).strip()

    return ""


# =========================================================
# ÜRÜN TEMİZLEME
# =========================================================

def clean_product(
    raw,
    store
):

    name = str(
        raw.get(
            "name",
            ""
        )
    ).strip()

    if not name:
        return None

    price = parse_price(
        raw.get(
            "price"
        )
    )

    if price is None:
        return None

    brand = detect_brand(
        name,
        raw.get(
            "brand",
            ""
        )
    )

    quantity = detect_quantity(
        name,
        raw.get(
            "quantity",
            ""
        )
    )

    product_id = make_product_id(
        name,
        brand,
        quantity
    )

    return {

        "productId":
            product_id,

        "name":
            name,

        "brand":
            brand,

        "quantity":
            quantity,

        "price":
            price,

        "store":
            store,

        "sku":
            raw.get(
                "sku",
                ""
            ),

        "normalizedName":
            normalize(name),

        "updatedAt":
            firestore.SERVER_TIMESTAMP,

        "source":
            "automatic_catalog"

    }


# =========================================================
# FIRESTORE - ÜRÜN KATALOĞU
# =========================================================

def save_catalog_product(
    product
):

    product_id = product[
        "productId"
    ]

    store = product[
        "store"
    ]

    # ----------------------------------------------
    # products koleksiyonu
    # ----------------------------------------------

    product_ref = (
        db.collection(
            "products"
        )
        .document(
            product_id
        )
    )

    product_ref.set(
        {
            "productId":
                product_id,

            "name":
                product["name"],

            "brand":
                product["brand"],

            "quantity":
                product["quantity"],

            "normalizedName":
                product["normalizedName"],

            "updatedAt":
                firestore.SERVER_TIMESTAMP,

            "source":
                "automatic_catalog"

        },
        merge=True
    )

    # ----------------------------------------------
    # prices koleksiyonu
    # ----------------------------------------------

    price_ref = (
        db.collection(
            "prices"
        )
        .document(
            product_id
        )
        .collection(
            "stores"
        )
        .document(
            make_slug(store)
        )
    )

    price_ref.set(
        {
            "productId":
                product_id,

            "productName":
                product["name"],

            "brand":
                product["brand"],

            "quantity":
                product["quantity"],

            "store":
                store,

            "price":
                product["price"],

            "currency":
                "TRY",

            "source":
                "automatic_catalog",

            "updatedAt":
                firestore.SERVER_TIMESTAMP

        },
        merge=True
    )


# =========================================================
# FIRESTORE - MARKET DURUMU
# =========================================================

def save_market_status(
    store,
    status,
    product_count=0,
    error=""
):

    ref = (
        db.collection(
            "market_status"
        )
        .document(
            make_slug(store)
        )
    )

    ref.set(
        {

            "store":
                store,

            "status":
                status,

            "productCount":
                product_count,

            "error":
                error,

            "updatedAt":
                firestore.SERVER_TIMESTAMP

        },
        merge=True
    )


# =========================================================
# MARKET TARA
# =========================================================

def scan_market(
    store,
    url
):

    print("")
    print(
        "======================================"
    )

    print(
        f"{store} TARANIYOR"
    )

    print(
        "======================================"
    )

    html = get_page(
        url
    )

    if not html:

        save_market_status(
            store,
            "error",
            0,
            "Market sayfasına erişilemedi."
        )

        return 0

    products = extract_products(
        html
    )

    print(
        f"{store}: "
        f"{len(products)} ürün bulundu."
    )

    if not products:

        save_market_status(
            store,
            "no_data",
            0,
            "Sayfada otomatik ürün verisi bulunamadı."
        )

        return 0

    saved = 0

    for raw in products:

        product = clean_product(
            raw,
            store
        )

        if not product:
            continue

        try:

            save_catalog_product(
                product
            )

            saved += 1

            print(
                f"[OK] {store} | "
                f"{product['name']} | "
                f"{product['price']:.2f} TL"
            )

        except Exception as e:

            print(
                f"[FIRESTORE ERROR] "
                f"{store}: {e}"
            )

        time.sleep(
            0.05
        )

    save_market_status(
        store,
        "success",
        saved,
        ""
    )

    return saved


# =========================================================
# FİYAT KARŞILAŞTIRMA
# =========================================================

def update_cheapest_prices():

    print("")
    print(
        "En ucuz fiyatlar hesaplanıyor..."
    )

    products_ref = (
        db.collection(
            "products"
        )
        .stream()
    )

    count = 0

    for product_doc in products_ref:

        product = product_doc.to_dict()

        product_id = product_doc.id

        price_docs = (
            db.collection(
                "prices"
            )
            .document(
                product_id
            )
            .collection(
                "stores"
            )
            .stream()
        )

        prices = []

        for price_doc in price_docs:

            data = price_doc.to_dict()

            price = parse_price(
                data.get(
                    "price"
                )
            )

            store = data.get(
                "store"
            )

            if (
                price is not None
                and store
            ):

                prices.append(
                    {
                        "store":
                            store,

                        "price":
                            price
                    }
                )

        if not prices:
            continue

        prices.sort(
            key=lambda x:
                x["price"]
        )

        cheapest = prices[0]

        product_doc.reference.set(
            {

                "cheapestStore":
                    cheapest["store"],

                "cheapestPrice":
                    cheapest["price"],

                "storeCount":
                    len(prices),

                "updatedAt":
                    firestore.SERVER_TIMESTAMP

            },
            merge=True
        )

        count += 1

    print(
        f"{count} ürün için en ucuz fiyat güncellendi."
    )


# =========================================================
# TEMİZLİK
# =========================================================

def cleanup_old_prices():

    # Eski fiyatları otomatik silmiyoruz.
    #
    # Bunun nedeni:
    # Bir market geçici olarak erişilemezse
    # eski gerçek fiyatın kaybolmaması.
    #
    # Böylece sistem:
    #
    # güncel veri
    # +
    # son bilinen fiyat
    #
    # mantığında çalışabilir.


# =========================================================
# ANA MOTOR
# =========================================================

def update_products():

    started = datetime.now(
        timezone.utc
    )

    print("")
    print(
        "######################################"
    )
    print(
        "# UCUZA OTOMATİK FİYAT MOTORU"
    )
    print(
        "######################################"
    )

    print(
        f"Başlangıç: {started.isoformat()}"
    )

    total_saved = 0

    for store, config in MARKETS.items():

        try:

            saved = scan_market(
                store,
                config["url"]
            )

            total_saved += saved

        except Exception as e:

            print(
                f"[MARKET ERROR] "
                f"{store}: {e}"
            )

            save_market_status(
                store,
                "error",
                0,
                str(e)
            )

        time.sleep(
            REQUEST_DELAY
        )

    # ----------------------------------------------
    # En ucuz fiyatları hesapla
    # ----------------------------------------------

    try:

        update_cheapest_prices()

    except Exception as e:

        print(
            "[COMPARE ERROR]",
            e
        )

    # ----------------------------------------------
    # Bitti
    # ----------------------------------------------

    finished = datetime.now(
        timezone.utc
    )

    print("")
    print(
        "######################################"
    )

    print(
        "UCUZA FİYAT MOTORU TAMAMLANDI"
    )

    print(
        f"Toplam kaydedilen ürün: "
        f"{total_saved}"
    )

    print(
        f"Bitiş: {finished.isoformat()}"
    )

    print(
        "######################################"
    )


# =========================================================
# MAIN
# =========================================================

if __name__ == "__main__":

    update_products()
