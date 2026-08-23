import os
import json
import re
import time
import html as html_lib
from urllib.parse import urljoin

import requests
import firebase_admin
from firebase_admin import credentials, firestore


# ============================================================
# UCUZA - ÇOKLU MARKET OTOMATİK FİYAT MOTORU
# FINAL MULTI-MARKET VERSION
#
# MARKETLER:
# BİM
# ŞOK
# MİGROS
# CARREFOURSA
# HAKMAR
# KOOP MARKET
# FİLE
#
# A101 YOK
# ============================================================

print("=" * 75)
print("UCUZA - ÇOKLU MARKET OTOMATİK FİYAT MOTORU")
print("=" * 75)
print("BİM + ŞOK + MİGROS + CARREFOURSA + HAKMAR + KOOP + FİLE")
print("=" * 75)


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
        "application/xml;q=0.9,"
        "image/avif,image/webp,*/*;q=0.8"
    ),

    "Accept-Language": (
        "tr-TR,tr;q=0.9,"
        "en-US;q=0.8,en;q=0.7"
    ),

    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "Upgrade-Insecure-Requests": "1",
}


session = requests.Session()
session.headers.update(HEADERS)


# ============================================================
# MARKETLER
# ============================================================

MARKETS = [

    {
        "key": "BİM",
        "source": "BIM",
        "urls": [
            "https://www.bim.com.tr/"
        ],
    },

    {
        "key": "ŞOK",
        "source": "SOK",
        "urls": [
            "https://www.sokmarket.com.tr/"
        ],
    },

    {
        "key": "MİGROS",
        "source": "MIGROS",
        "urls": [
            "https://www.migros.com.tr/"
        ],
    },

    {
        "key": "CARREFOURSA",
        "source": "CARREFOURSA",
        "urls": [
            "https://www.carrefoursa.com/",
            "https://www.carrefoursa.com/online-alisverisi-tum-urunler/c/9577",
        ],
    },

    {
        "key": "HAKMAR",
        "source": "HAKMAR",
        "urls": [
            "https://hakmar.com.tr/"
        ],
    },

    {
        "key": "KOOP",
        "source": "KOOP",
        "urls": [
            "https://www.tkkoop.com.tr/"
        ],
    },

    {
        "key": "FİLE",
        "source": "FILE",
        "urls": [
            "https://www.file.com.tr/"
        ],
    },

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

    return name.strip()


def parse_price(value):

    if value is None:
        return None

    value = str(value).strip()

    if not value:
        return None

    value = value.replace(
        "₺",
        ""
    )

    value = re.sub(
        r"\bTL\b",
        "",
        value,
        flags=re.I
    )

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

    else:

        # 1299.90
        value = re.sub(
            r"[^0-9.]",
            "",
            value
        )

    value = re.sub(
        r"[^0-9.]",
        "",
        value
    )

    try:

        price = float(
            value
        )

        if price <= 0:
            return None

        if price > 100000:
            return None

        return price

    except Exception:

        return None


def product_id(
    barcode,
    name
):

    if barcode:

        value = str(
            barcode
        ).strip()

        if value:
            return value

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
# ÜRÜN FİLTRESİ
# ============================================================

BAD_WORDS = [

    "filtre",

    "sırala",

    "sirala",

    "sepete ekle",

    "ürün bulundu",

    "urun bulundu",

    "fiyat aralığı",

    "fiyat araligi",

    "tümünü gör",

    "tumunu gor",

    "önerilen",

    "onerilen",

    "ana sayfa",

    "giriş yap",

    "giris yap",

    "kategoriler",

    "kampanyalar",

    "iletişim",

    "iletisim",

    "hakkımızda",

    "hakkimizda",

    "çerez",

    "cerez",

    "gizlilik",

    "kişisel veriler",

    "kullanım koşulları",

    "kullanim kosullari",

]


def looks_like_product_name(
    name
):

    name = clean_name(
        name
    )

    if len(name) < 3:
        return False

    if len(name) > 180:
        return False

    normalized = normalize(
        name
    )

    for bad in BAD_WORDS:

        if normalize(bad) in normalized:
            return False

    # Çok fazla URL / kod varsa ürün değildir
    if "http://" in normalized:
        return False

    if "https://" in normalized:
        return False

    # Sadece sayı
    if re.fullmatch(
        r"[0-9 .,-]+",
        name
    ):
        return False

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

            if not looks_like_product_name(
                name
            ):
                continue

            sku = item.get(
                "sku",
                ""
            )

            if not sku:
                sku = item.get(
                    "gtin",
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
            offer_url = ""

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

                offer_url = (
                    offers.get(
                        "url"
                    )
                    or
                    ""
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

                    candidate = (
                        offer.get(
                            "price"
                        )
                    )

                    if candidate:

                        price = candidate

                        offer_url = (
                            offer.get(
                                "url"
                            )
                            or
                            ""
                        )

                        break

            products.append(
                {
                    "barcode": str(
                        sku
                        or ""
                    ),

                    "name": name,

                    "brand": clean_name(
                        brand
                    ),

                    "quantity": quantity,

                    "source": source,

                    "price": parse_price(
                        price
                    ),

                    "url": offer_url,
                }
            )

    return products


# ============================================================
# HTML METADATA
# ============================================================

def extract_meta_products(
    html,
    source_url,
    source
):

    products = []

    # product:name
    names = re.findall(
        r'<meta[^>]+(?:property|name)=["\']product:name["\'][^>]+content=["\']([^"\']+)',
        html,
        re.I
    )

    prices = re.findall(
        r'<meta[^>]+(?:property|name)=["\']product:price:amount["\'][^>]+content=["\']([^"\']+)',
        html,
        re.I
    )

    count = min(
        len(names),
        len(prices)
    )

    for i in range(
        count
    ):

        name = clean_name(
            names[i]
        )

        price = parse_price(
            prices[i]
        )

        if not looks_like_product_name(
            name
        ):
            continue

        if not price:
            continue

        products.append(
            {
                "barcode": "",
                "name": name,
                "brand": "",
                "quantity": "",
                "source": source,
                "price": price,
                "url": source_url,
            }
        )

    return products


# ============================================================
# GÖRÜNÜR HTML METNİ
# ============================================================

def html_to_text(
    html
):

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
        r"<svg.*?</svg>",
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

    return text.strip()


# ============================================================
# GENEL ÜRÜN / FİYAT TARAYICI
# ============================================================

def extract_visible_products(
    html,
    source_url,
    source
):

    products = []

    text = html_to_text(
        html
    )

    # --------------------------------------------------------
    # TL SONRASI / ÖNCESİ
    # --------------------------------------------------------

    patterns = [

        # Ürün 129,90 TL
        re.compile(
            r"(.{3,160}?)"
            r"\s+"
            r"([0-9]{1,6}"
            r"(?:[.,][0-9]{1,2})?)"
            r"\s*(?:₺|TL)\b",
            re.I
        ),

        # Ürün ₺129,90
        re.compile(
            r"(.{3,160}?)"
            r"\s*"
            r"(?:₺|TL)"
            r"\s*"
            r"([0-9]{1,6}"
            r"(?:[.,][0-9]{1,2})?)",
            re.I
        ),

        # BİM formatı
        re.compile(
            r"(.{3,140}?)"
            r"\s+"
            r"([0-9]{1,6}"
            r"(?:[.,][0-9]{1,2})?)"
            r"\s*₺",
            re.I
        ),

    ]

    for pattern in patterns:

        try:

            matches = pattern.findall(
                text
            )

        except Exception:

            continue

        for name,
            price in matches:

            name = clean_name(
                name
            )

            price = parse_price(
                price
            )

            if not price:
                continue

            # Son 180 karakter
            if len(name) > 180:

                name = name[-180:]

            # Ürün adından gereksiz şeyleri temizle
            name = re.sub(
                r"^(?:image|ürün|urun)\s*",
                "",
                name,
                flags=re.I
            )

            name = clean_name(
                name
            )

            if not looks_like_product_name(
                name
            ):
                continue

            products.append(
                {
                    "barcode": "",
                    "name": name,
                    "brand": "",
                    "quantity": "",
                    "source": source,
                    "price": price,
                    "url": source_url,
                }
            )

    return products


# ============================================================
# MARKET ÖZEL TEMİZLEME
# ============================================================

def clean_market_product(
    item,
    market
):

    if not item:
        return None

    name = clean_name(
        item.get(
            "name",
            ""
        )
    )

    price = parse_price(
        item.get(
            "price"
        )
    )

    if not name:
        return None

    if not price:
        return None

    # Çok uzun ürün adı
    if len(name) > 180:
        name = name[-180:]

    # Market başlıklarını temizle
    prefixes = [

        "carrefour",

        "carrefoursa",

        "bim",

        "şok",

        "sok",

        "migros",

    ]

    # Burada ürün adını komple silmiyoruz.
    # Çünkü Carrefour markalı ürünlerde marka önemli.

    if not looks_like_product_name(
        name
    ):
        return None

    item["name"] = name
    item["price"] = price

    return item


# ============================================================
# AYNI MARKETTE DUPLICATE TEMİZLEME
# ============================================================

def unique_market_products(
    products
):

    result = {}

    for item in products:

        item = clean_market_product(
            item,
            item.get(
                "source",
                ""
            )
        )

        if not item:
            continue

        barcode = str(
            item.get(
                "barcode",
                ""
            )
        ).strip()

        name = item.get(
            "name",
            ""
        )

        pid = product_id(
            barcode,
            name
        )

        if not pid:
            continue

        # Aynı markette aynı ürünün
        # daha iyi fiyat kaydını koru.
        existing = result.get(
            pid
        )

        if existing:

            old_price = parse_price(
                existing.get(
                    "price"
                )
            )

            new_price = parse_price(
                item.get(
                    "price"
                )
            )

            if (
                old_price is None
                or
                (
                    new_price is not None
                    and
                    new_price < old_price
                )
            ):

                result[pid] = item

        else:

            result[pid] = item

    return list(
        result.values()
    )


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
        db.collection(
            "products"
        )
        .document(
            str(barcode)
        )
    )

    data = {

        "barcode": str(
            barcode
        ),

        "name": name,

        "brand": clean_name(
            brand
        ),

        "quantity": clean_name(
            quantity
        ),

        "source": source,

        "url": url,

        "updatedAt":
            firestore.SERVER_TIMESTAMP,
    }

    ref.set(
        data,
        merge=True
    )

    return {
        "barcode": str(
            barcode
        ),

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
        db.collection(
            "prices"
        )
        .document(
            str(barcode)
        )
        .collection(
            "stores"
        )
        .document(
            store
        )
    )

    data = {

        "barcode": str(
            barcode
        ),

        "productName":
            product["name"],

        "brand":
            product.get(
                "brand",
                ""
            ),

        "quantity":
            product.get(
                "quantity",
                ""
            ),

        "store": store,

        "price": price,

        "currency": "TRY",

        "url": url,

        "updatedAt":
            firestore.SERVER_TIMESTAMP,
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
# MARKET SONUÇLARINI FIRESTORE'A YAZ
# ============================================================

def save_market_products(
    products,
    store
):

    saved_products = 0
    saved_prices = 0

    for item in products:

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

            source=item.get(
                "source",
                ""
            ),

            url=item.get(
                "url",
                ""
            ),
        )

        if not product:
            continue

        saved_products += 1

        if save_price(

            product,

            store,

            item.get(
                "price"
            ),

            item.get(
                "url",
                ""
            ),

        ):

            saved_prices += 1

    return (
        saved_products,
        saved_prices
    )


# ============================================================
# TEK MARKET TARAMA
# ============================================================

def scan_market(
    market
):

    market_name = market[
        "key"
    ]

    source = market[
        "source"
    ]

    urls = market[
        "urls"
    ]

    print("")
    print("=" * 75)
    print(
        f"{market_name} ÜRÜNLERİ OTOMATİK KEŞFEDİLİYOR"
    )
    print("=" * 75)

    discovered = []

    for url in urls:

        try:

            print("")
            print(
                f"[{market_name}] Taranıyor: {url}"
            )

            response = session.get(
                url,
                timeout=45,
                allow_redirects=True
            )

            print(
                f"[{market_name}] HTTP:",
                response.status_code
            )

            print(
                f"[{market_name}] HTML:",
                len(
                    response.text
                ),
                "karakter"
            )

            # ------------------------------------------------
            # 403
            # ------------------------------------------------

            if response.status_code == 403:

                print(
                    f"[{market_name}] 403 erişim engeli."
                )

                print(
                    f"[{market_name}] Bu kaynak atlanıyor."
                )

                continue

            # ------------------------------------------------
            # 429
            # ------------------------------------------------

            if response.status_code == 429:

                print(
                    f"[{market_name}] 429 rate limit."
                )

                print(
                    f"[{market_name}] Bekleniyor..."
                )

                time.sleep(
                    8
                )

                continue

            # ------------------------------------------------
            # Diğer hatalar
            # ------------------------------------------------

            if response.status_code != 200:

                print(
                    f"[{market_name}] Sayfa alınamadı."
                )

                continue

            html = response.text

            # ------------------------------------------------
            # JSON-LD
            # ------------------------------------------------

            jsonld = extract_jsonld_products(
                html,
                source
            )

            for item in jsonld:

                item["url"] = (
                    item.get(
                        "url"
                    )
                    or
                    response.url
                )

                discovered.append(
                    item
                )

            print(
                f"[{market_name}] JSON-LD ürün:",
                len(jsonld)
            )

            # ------------------------------------------------
            # META
            # ------------------------------------------------

            meta_products = extract_meta_products(
                html,
                response.url,
                source
            )

            discovered.extend(
                meta_products
            )

            print(
                f"[{market_name}] META ürün:",
                len(
                    meta_products
                )
            )

            # ------------------------------------------------
            # VISIBLE HTML
            # ------------------------------------------------

            visible_products = extract_visible_products(
                html,
                response.url,
                source
            )

            discovered.extend(
                visible_products
            )

            print(
                f"[{market_name}] HTML ürün:",
                len(
                    visible_products
                )
            )

            time.sleep(
                2
            )

        except requests.exceptions.Timeout:

            print(
                f"[{market_name}] Zaman aşımı."
            )

        except requests.exceptions.RequestException as e:

            print(
                f"[{market_name}] HTTP HATASI:",
                str(e)
            )

        except Exception as e:

            print(
                f"[{market_name}] HATA:",
                str(e)
            )

    # --------------------------------------------------------
    # Duplicate
    # --------------------------------------------------------

    discovered = unique_market_products(
        discovered
    )

    print("")
    print(
        f"[{market_name}] Toplam keşfedilen:",
        len(discovered)
    )

    # --------------------------------------------------------
    # Firestore
    # --------------------------------------------------------

    if discovered:

        saved_products, saved_prices = (
            save_market_products(
                discovered,
                market_name
            )
        )

    else:

        saved_products = 0
        saved_prices = 0

        print(
            f"[{market_name}] Kaydedilecek ürün bulunamadı."
        )

    print("")
    print(
        f"[{market_name}] Kaydedilen ürün:",
        saved_products
    )

    print(
        f"[{market_name}] Kaydedilen fiyat:",
        saved_prices
    )

    print(
        f"[{market_name}] TAMAMLANDI."
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
                    "barcode":
                        data.get(
                            "barcode",
                            doc.id
                        ),

                    "name":
                        name,

                    "brand":
                        data.get(
                            "brand",
                            ""
                        ),

                    "quantity":
                        data.get(
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
# MARKET ÖZETİ
# ============================================================

def print_summary(
    results
):

    print("")
    print("=" * 75)
    print("MARKET SONUÇLARI")
    print("=" * 75)

    total_products = 0
    total_prices = 0

    for market, data in results.items():

        products = data.get(
            "products",
            0
        )

        prices = data.get(
            "prices",
            0
        )

        total_products += products
        total_prices += prices

        print(
            f"{market:<18} "
            f"Ürün: {products:<6} "
            f"Fiyat: {prices}"
        )

    print("-" * 75)

    print(
        f"TOPLAM ÜRÜN KAYDI: {total_products}"
    )

    print(
        f"TOPLAM FİYAT KAYDI: {total_prices}"
    )

    print("=" * 75)


# ============================================================
# ANA MOTOR
# ============================================================

def update_products():

    print("")
    print("=" * 75)
    print(
        "UCUZA ÇOKLU MARKET FİYAT MOTORU BAŞLADI"
    )
    print("=" * 75)

    results = {}

    # ========================================================
    # TÜM MARKETLER
    # ========================================================

    for market in MARKETS:

        market_name = market[
            "key"
        ]

        try:

            products = scan_market(
                market
            )

            # ------------------------------------------------
            # Bu noktada gerçek Firestore kayıtlarını saymak
            # için ürün sayısını kullanıyoruz.
            # ------------------------------------------------

            prices = 0

            for item in products:

                if parse_price(
                    item.get(
                        "price"
                    )
                ):

                    prices += 1

            results[
                market_name
            ] = {

                "products":
                    len(products),

                "prices":
                    prices,
            }

        except Exception as e:

            print("")
            print(
                f"[{market_name}] MOTOR HATASI:"
            )

            print(
                str(e)
            )

            print(
                f"[{market_name}] ATLANIYOR."
            )

            results[
                market_name
            ] = {

                "products": 0,

                "prices": 0,
            }

            continue

    # ========================================================
    # FIRESTORE
    # ========================================================

    products = get_firestore_products()

    # ========================================================
    # ÖZET
    # ========================================================

    print_summary(
        results
    )

    print("")
    print("=" * 75)
    print("FIRESTORE GENEL DURUM")
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
            "Firestore'da henüz ürün bulunamadı."
        )

    print("")
    print("=" * 75)
    print(
        "UCUZA ÇOKLU MARKET FİYAT MOTORU TAMAMLANDI"
    )
    print("=" * 75)


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":

    try:

        update_products()

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
