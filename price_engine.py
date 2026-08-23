import os
import json
import re
import time
import hashlib
from difflib import SequenceMatcher

import requests
from bs4 import BeautifulSoup

import firebase_admin
from firebase_admin import credentials, firestore


# ============================================================
# UCUZA - OTOMATİK FİYAT MOTORU
# TEK FİNAL SÜRÜM
# ============================================================

print("=" * 70)
print("UCUZA OTOMATİK FİYAT MOTORU")
print("ÜRÜN KEŞFİ + FİYAT KEŞFİ + FIRESTORE")
print("=" * 70)


# ============================================================
# FIREBASE
# ============================================================

service_account = os.environ.get("FIREBASE_SERVICE_ACCOUNT")

if not service_account:
    raise RuntimeError(
        "FIREBASE_SERVICE_ACCOUNT bulunamadı."
    )

try:
    credentials_data = json.loads(service_account)

    cred = credentials.Certificate(
        credentials_data
    )

    if not firebase_admin._apps:
        firebase_admin.initialize_app(cred)

except Exception as e:
    raise RuntimeError(
        f"Firebase başlatılamadı: {e}"
    )


db = firestore.client()


# ============================================================
# HTTP
# ============================================================

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/139.0 Safari/537.36"
    ),
    "Accept-Language": "tr-TR,tr;q=0.9,en;q=0.8",
    "Accept": (
        "text/html,application/xhtml+xml,"
        "application/xml;q=0.9,image/avif,image/webp,"
        "*/*;q=0.8"
    ),
    "Connection": "keep-alive",
}


session = requests.Session()
session.headers.update(HEADERS)


# ============================================================
# MAĞAZALAR
# ============================================================

STORE_URLS = {
    "A101": [
        "https://www.a101.com.tr/",
        "https://www.a101.com.tr/market",
    ],
    "SOK": [
        "https://www.sokmarket.com.tr/",
    ],
}


# ============================================================
# YARDIMCI FONKSİYONLAR
# ============================================================

def normalize(text):
    """
    Türkçe karakterleri sadeleştirir.
    Ürün eşleştirmede kullanılır.
    """

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
        r"[^a-z0-9\s]",
        " ",
        text
    )

    text = re.sub(
        r"\s+",
        " ",
        text
    )

    return text.strip()


def clean_name(text):
    if not text:
        return ""

    text = re.sub(
        r"\s+",
        " ",
        str(text)
    )

    return text.strip()


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

    value = re.sub(
        r"[^0-9.]",
        "",
        value
    )

    if not value:
        return None

    try:
        price = float(value)

        if price <= 0:
            return None

        # Aşırı büyük / anlamsız değerleri engelle
        if price > 100000:
            return None

        return round(price, 2)

    except Exception:
        return None


def slugify(text):

    text = normalize(text)

    text = text.replace(
        " ",
        "-"
    )

    text = re.sub(
        r"-+",
        "-",
        text
    )

    return text[:120]


def make_product_id(
    name,
    brand="",
    quantity=""
):

    combined = " ".join(
        x for x in [
            brand,
            name,
            quantity
        ]
        if x
    )

    slug = slugify(combined)

    if slug:
        return slug

    return hashlib.sha1(
        combined.encode("utf-8")
    ).hexdigest()[:24]


def get_page(url):

    try:

        print(
            f"[HTTP] {url}"
        )

        response = session.get(
            url,
            timeout=30,
            allow_redirects=True
        )

        print(
            f"[HTTP] {response.status_code} | {url}"
        )

        if response.status_code != 200:

            print(
                f"[UYARI] Sayfa alınamadı: "
                f"HTTP {response.status_code}"
            )

            return None

        return response.text

    except Exception as e:

        print(
            f"[HTTP HATA] {url} | {e}"
        )

        return None


# ============================================================
# FIRESTORE ÜRÜN KAYDET
# ============================================================

def save_product(
    name,
    brand="",
    quantity="",
    barcode="",
    source=""
):

    name = clean_name(name)
    brand = clean_name(brand)
    quantity = clean_name(quantity)

    if not name:
        return None

    if barcode:
        product_id = str(barcode)
    else:
        product_id = make_product_id(
            name,
            brand,
            quantity
        )

    ref = (
        db.collection("products")
        .document(product_id)
    )

    data = {
        "barcode": str(barcode or ""),
        "name": name,
        "brand": brand,
        "quantity": quantity,
        "source": source,
        "updatedAt": firestore.SERVER_TIMESTAMP,
    }

    ref.set(
        data,
        merge=True
    )

    return {
        "id": product_id,
        "barcode": str(barcode or ""),
        "name": name,
        "brand": brand,
        "quantity": quantity,
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

    parsed_price = parse_price(price)

    if parsed_price is None:
        return False

    product_id = product["id"]

    ref = (
        db.collection("prices")
        .document(product_id)
        .collection("stores")
        .document(store)
    )

    ref.set(
        {
            "barcode": product.get(
                "barcode",
                ""
            ),
            "productName": product.get(
                "name",
                ""
            ),
            "brand": product.get(
                "brand",
                ""
            ),
            "quantity": product.get(
                "quantity",
                ""
            ),
            "store": store,
            "price": parsed_price,
            "currency": "TRY",
            "url": url,
            "updatedAt": firestore.SERVER_TIMESTAMP,
        },
        merge=True
    )

    print(
        f"[FIYAT] {store} | "
        f"{product.get('name', '')} | "
        f"{parsed_price:.2f} TL"
    )

    return True


# ============================================================
# JSON-LD ÇÖZ
# ============================================================

def extract_json_ld(html):

    results = []

    soup = BeautifulSoup(
        html,
        "html.parser"
    )

    scripts = soup.find_all(
        "script",
        attrs={
            "type": "application/ld+json"
        }
    )

    for script in scripts:

        raw = script.string

        if not raw:
            raw = script.get_text()

        if not raw:
            continue

        raw = raw.strip()

        try:

            data = json.loads(raw)

            if isinstance(data, list):

                results.extend(data)

            elif isinstance(data, dict):

                results.append(data)

        except Exception:

            # Bazı sitelerde JSON bozuk olabilir.
            continue

    return results


# ============================================================
# JSON İÇİNDEN PRODUCT NESNELERİNİ BUL
# ============================================================

def find_product_objects(data):

    found = []

    def walk(obj):

        if isinstance(obj, dict):

            object_type = obj.get(
                "@type",
                ""
            )

            if (
                object_type == "Product"
                or (
                    isinstance(
                        object_type,
                        list
                    )
                    and "Product" in object_type
                )
            ):

                found.append(obj)

            for value in obj.values():

                walk(value)

        elif isinstance(obj, list):

            for item in obj:
                walk(item)

    walk(data)

    return found


# ============================================================
# JSON-LD ÜRÜNLERİNİ İŞLE
# ============================================================

def process_json_products(
    html,
    store,
    source_url
):

    products = []

    blocks = extract_json_ld(
        html
    )

    for block in blocks:

        product_objects = (
            find_product_objects(
                block
            )
        )

        for item in product_objects:

            name = clean_name(
                item.get(
                    "name",
                    ""
                )
            )

            if not name:
                continue

            barcode = (
                item.get("gtin13")
                or item.get("gtin")
                or item.get("sku")
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

            elif isinstance(
                brand_data,
                str
            ):

                brand = brand_data

            quantity = ""

            # Bazı sitelerde ürün boyutu
            # category / description içinde olabilir.
            description = item.get(
                "description",
                ""
            )

            if description:
                quantity = extract_quantity(
                    description
                )

            product = save_product(
                name=name,
                brand=brand,
                quantity=quantity,
                barcode=barcode,
                source=store
            )

            if not product:
                continue

            price = None

            offers = item.get(
                "offers",
                {}
            )

            if isinstance(
                offers,
                dict
            ):

                price = (
                    offers.get("price")
                    or offers.get(
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
                        offer.get("price")
                        or offer.get(
                            "lowPrice"
                        )
                    )

                    if price:
                        break

            if price:

                save_price(
                    product,
                    store,
                    price,
                    source_url
                )

            products.append(
                product
            )

    return products


# ============================================================
# MİKTAR YAKALA
# ============================================================

def extract_quantity(text):

    if not text:
        return ""

    patterns = [
        r"\b\d+(?:[.,]\d+)?\s*(?:kg|g|gr|mg|ml|lt|l)\b",
        r"\b\d+\s*(?:'li|li|adet|paket)\b",
    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            str(text),
            re.I
        )

        if match:
            return match.group(0)

    return ""


# ============================================================
# GENEL HTML ÜRÜN / FİYAT ÇIKARMA
# ============================================================

def extract_html_products(
    html,
    store,
    source_url
):

    soup = BeautifulSoup(
        html,
        "html.parser"
    )

    results = []

    # --------------------------------------------------------
    # Önce ürün kartlarını bulmaya çalış
    # --------------------------------------------------------

    candidates = soup.find_all(
        [
            "article",
            "li",
            "div"
        ]
    )

    for element in candidates:

        text = element.get_text(
            " ",
            strip=True
        )

        if not text:
            continue

        if len(text) < 5:
            continue

        if len(text) > 700:
            continue

        price_match = re.search(
            r"(?:₺\s*)?"
            r"(\d{1,5}(?:[.,]\d{1,2})?)"
            r"\s*(?:₺|TL)\b",
            text,
            re.I
        )

        if not price_match:
            continue

        price = parse_price(
            price_match.group(1)
        )

        if not price:
            continue

        # Fiyatı metinden çıkar
        name_text = re.sub(
            r"(?:₺\s*)?"
            r"\d{1,5}(?:[.,]\d{1,2})?"
            r"\s*(?:₺|TL)\b",
            " ",
            text,
            flags=re.I
        )

        name_text = clean_name(
            name_text
        )

        # Çok uzun / anlamsız blokları alma
        if len(name_text) < 3:
            continue

        if len(name_text) > 180:
            continue

        # Menü / navigasyon gibi metinleri ele
        bad_words = [
            "giriş yap",
            "sepet",
            "kampanya",
            "iletişim",
            "hakkımızda",
            "çerez",
            "gizlilik",
            "üyelik",
            "favoriler",
        ]

        normalized = normalize(
            name_text
        )

        if any(
            word in normalized
            for word in [
                normalize(x)
                for x in bad_words
            ]
        ):
            continue

        results.append(
            (
                name_text,
                price
            )
        )

    # --------------------------------------------------------
    # Tekrarlananları temizle
    # --------------------------------------------------------

    unique = {}

    for name, price in results:

        key = (
            normalize(name),
            round(price, 2)
        )

        unique[key] = (
            name,
            price
        )

    saved_products = []

    for name, price in unique.values():

        product = save_product(
            name=name,
            source=store
        )

        if not product:
            continue

        save_price(
            product,
            store,
            price,
            source_url
        )

        saved_products.append(
            product
        )

    return saved_products


# ============================================================
# A101
# ============================================================

def discover_a101():

    print("")
    print("=" * 70)
    print("A101 OTOMATİK ÜRÜN / FİYAT KEŞFİ")
    print("=" * 70)

    all_products = []

    for url in STORE_URLS["A101"]:

        html = get_page(url)

        if not html:
            continue

        print(
            "[A101] JSON-LD ürünleri aranıyor..."
        )

        try:

            json_products = (
                process_json_products(
                    html,
                    "A101",
                    url
                )
            )

            all_products.extend(
                json_products
            )

        except Exception as e:

            print(
                "[A101 JSON HATA]",
                e
            )

        print(
            "[A101] HTML ürünleri aranıyor..."
        )

        try:

            html_products = (
                extract_html_products(
                    html,
                    "A101",
                    url
                )
            )

            all_products.extend(
                html_products
            )

        except Exception as e:

            print(
                "[A101 HTML HATA]",
                e
            )

        time.sleep(2)

    print(
        f"[A101] Toplam kayıt: "
        f"{len(all_products)}"
    )

    return all_products


# ============================================================
# ŞOK
# ============================================================

def discover_sok():

    print("")
    print("=" * 70)
    print("ŞOK OTOMATİK ÜRÜN / FİYAT KEŞFİ")
    print("=" * 70)

    all_products = []

    for url in STORE_URLS["SOK"]:

        html = get_page(url)

        if not html:
            continue

        print(
            "[ŞOK] JSON-LD ürünleri aranıyor..."
        )

        try:

            json_products = (
                process_json_products(
                    html,
                    "SOK",
                    url
                )
            )

            all_products.extend(
                json_products
            )

        except Exception as e:

            print(
                "[ŞOK JSON HATA]",
                e
            )

        print(
            "[ŞOK] HTML ürünleri aranıyor..."
        )

        try:

            html_products = (
                extract_html_products(
                    html,
                    "SOK",
                    url
                )
            )

            all_products.extend(
                html_products
            )

        except Exception as e:

            print(
                "[ŞOK HTML HATA]",
                e
            )

        time.sleep(2)

    print(
        f"[ŞOK] Toplam kayıt: "
        f"{len(all_products)}"
    )

    return all_products


# ============================================================
# FIRESTORE ÜRÜNLERİNİ OKU
# ============================================================

def get_firestore_products():

    products = []

    try:

        docs = (
            db.collection("products")
            .stream()
        )

        for doc in docs:

            data = doc.to_dict()

            if not data:
                continue

            name = clean_name(
                data.get(
                    "name",
                    ""
                )
            )

            if not name:
                continue

            products.append(
                {
                    "id": doc.id,
                    "barcode": data.get(
                        "barcode",
                        ""
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
            "[FIRESTORE HATA]",
            e
        )

    print(
        f"Firestore ürün sayısı: "
        f"{len(products)}"
    )

    return products


# ============================================================
# ÜRÜN EŞLEŞTİRME
# ============================================================

def product_similarity(
    product_a,
    product_b
):

    name_a = normalize(
        product_a.get(
            "name",
            ""
        )
    )

    name_b = normalize(
        product_b.get(
            "name",
            ""
        )
    )

    if not name_a or not name_b:
        return 0.0

    if name_a == name_b:
        return 1.0

    # Barkod aynıysa kesin eşleşme
    barcode_a = str(
        product_a.get(
            "barcode",
            ""
        )
    ).strip()

    barcode_b = str(
        product_b.get(
            "barcode",
            ""
        )
    ).strip()

    if (
        barcode_a
        and barcode_b
        and barcode_a == barcode_b
    ):
        return 1.0

    ratio = SequenceMatcher(
        None,
        name_a,
        name_b
    ).ratio()

    tokens_a = set(
        name_a.split()
    )

    tokens_b = set(
        name_b.split()
    )

    if tokens_a and tokens_b:

        intersection = (
            len(
                tokens_a & tokens_b
            )
        )

        union = (
            len(
                tokens_a | tokens_b
            )
        )

        jaccard = (
            intersection / union
            if union
            else 0
        )

    else:

        jaccard = 0

    return max(
        ratio,
        jaccard
    )


# ============================================================
# AYNI ÜRÜNÜ BİRLEŞTİR
# ============================================================

def merge_similar_products():

    print("")
    print("=" * 70)
    print("ÜRÜN EŞLEŞTİRME")
    print("=" * 70)

    products = get_firestore_products()

    if len(products) < 2:

        print(
            "Eşleştirilecek yeterli ürün yok."
        )

        return

    checked = 0
    merged = 0

    for i in range(
        len(products)
    ):

        first = products[i]

        for j in range(
            i + 1,
            len(products)
        ):

            second = products[j]

            # Aynı mağazadan gelen aynı ürünü
            # tekrar birleştirme
            if (
                first.get("id")
                == second.get("id")
            ):
                continue

            score = product_similarity(
                first,
                second
            )

            checked += 1

            # Çok yüksek benzerlikte eşleştir.
            if score < 0.92:
                continue

            # İsim kısa ise yanlış eşleşme
            # ihtimalini azalt.
            if (
                len(
                    normalize(
                        first["name"]
                    )
                ) < 6
            ):
                continue

            if (
                len(
                    normalize(
                        second["name"]
                    )
                ) < 6
            ):
                continue

            print(
                "[EŞLEŞME]",
                first["name"],
                "<->",
                second["name"],
                f"| skor={score:.2f}"
            )

            # Eski fiyatları yeni ürün ID'sine
            # kopyalamaya çalış.
            copy_prices(
                second["id"],
                first["id"]
            )

            merged += 1

    print(
        f"Karşılaştırılan: {checked}"
    )

    print(
        f"Eşleşen: {merged}"
    )


# ============================================================
# FİYATLARI KOPYALA
# ============================================================

def copy_prices(
    old_product_id,
    new_product_id
):

    try:

        stores_ref = (
            db.collection("prices")
            .document(
                old_product_id
            )
            .collection("stores")
        )

        docs = stores_ref.stream()

        for doc in docs:

            data = doc.to_dict()

            if not data:
                continue

            new_ref = (
                db.collection("prices")
                .document(
                    new_product_id
                )
                .collection("stores")
                .document(
                    doc.id
                )
            )

            new_ref.set(
                data,
                merge=True
            )

    except Exception as e:

        print(
            "[FIYAT KOPYALAMA HATA]",
            e
        )


# ============================================================
# FİYAT KONTROLÜ
# ============================================================

def print_price_summary():

    print("")
    print("=" * 70)
    print("FİYAT SONUÇLARI")
    print("=" * 70)

    products = get_firestore_products()

    total = 0
    with_prices = 0

    for product in products:

        try:

            stores = (
                db.collection("prices")
                .document(
                    product["id"]
                )
                .collection("stores")
                .stream()
            )

            prices = []

            for doc in stores:

                data = doc.to_dict()

                if not data:
                    continue

                price = parse_price(
                    data.get(
                        "price"
                    )
                )

                if price is None:
                    continue

                prices.append(
                    (
                        data.get(
                            "store",
                            doc.id
                        ),
                        price
                    )
                )

            if not prices:
                continue

            with_prices += 1
            total += len(prices)

            prices.sort(
                key=lambda x: x[1]
            )

            cheapest = prices[0]

            print(
                f"{product['name']} | "
                f"EN UCUZ: "
                f"{cheapest[0]} "
                f"{cheapest[1]:.2f} TL"
            )

        except Exception as e:

            print(
                "[ÖZET HATA]",
                e
            )

    print("")
    print(
        "Fiyat bulunan ürün:",
        with_prices
    )

    print(
        "Toplam fiyat kaydı:",
        total
    )


# ============================================================
# ANA MOTOR
# ============================================================

def update_products():

    start_time = time.time()

    print("")
    print("=" * 70)
    print("UCUZA OTOMATİK MOTOR BAŞLADI")
    print("=" * 70)
    print("")

    # --------------------------------------------------------
    # 1 - A101
    # --------------------------------------------------------

    try:

        discover_a101()

    except Exception as e:

        print(
            "[A101 ANA HATA]",
            e
        )

    # --------------------------------------------------------
    # 2 - ŞOK
    # --------------------------------------------------------

    try:

        discover_sok()

    except Exception as e:

        print(
            "[ŞOK ANA HATA]",
            e
        )

    # --------------------------------------------------------
    # 3 - ÜRÜNLERİ BİRLEŞTİR
    # --------------------------------------------------------

    try:

        merge_similar_products()

    except Exception as e:

        print(
            "[EŞLEŞTİRME ANA HATA]",
            e
        )

    # --------------------------------------------------------
    # 4 - SONUÇ
    # --------------------------------------------------------

    try:

        print_price_summary()

    except Exception as e:

        print(
            "[ÖZET ANA HATA]",
            e
        )

    elapsed = (
        time.time()
        - start_time
    )

    print("")
    print("=" * 70)
    print(
        "UCUZA OTOMATİK FİYAT MOTORU TAMAMLANDI"
    )
    print(
        f"Süre: {elapsed:.1f} saniye"
    )
    print("=" * 70)


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":
    update_products()
