import os
import firebase_admin
from firebase_admin import credentials, firestore

# Firebase bağlantısı
# GitHub Actions içinde FIREBASE_SERVICE_ACCOUNT değişkeninden okunur.
service_account = os.environ.get("FIREBASE_SERVICE_ACCOUNT")

if not service_account:
    raise RuntimeError("FIREBASE_SERVICE_ACCOUNT bulunamadı.")

import json

cred = credentials.Certificate(json.loads(service_account))

if not firebase_admin._apps:
    firebase_admin.initialize_app(cred)

db = firestore.client()


# --------------------------------------------------
# ÜRÜN VERİLERİ
# --------------------------------------------------

PRODUCTS = [
    {
        "barcode": "8690504010011",
        "name": "Yumurta",
        "brand": "Bili Bili",
        "quantity": "30'lu",
        "unit": "1 adet"
    }
]


# --------------------------------------------------
# FİYAT KAYDETME
# --------------------------------------------------

def save_price(product, store, price):

    if price is None:
        return

    price = float(price)

    ref = (
        db.collection("prices")
        .document(product["barcode"])
        .collection("stores")
        .document(store)
    )

    ref.set(
        {
            "barcode": product["barcode"],
            "productName": product["name"],
            "brand": product["brand"],
            "quantity": product["quantity"],
            "unit": product["unit"],
            "store": store,
            "price": price,
            "currency": "TRY",
            "updatedAt": firestore.SERVER_TIMESTAMP
        },
        merge=True
    )

    print(
        f"{store} | "
        f"{product['name']} | "
        f"{price:.2f} TL"
    )


# --------------------------------------------------
# MAĞAZA FİYATLARI
# --------------------------------------------------
#
# Buraya gerçek mağaza veri kaynaklarını bağlayacağız.
# Şimdilik sistem altyapısı hazır.
#
# Örnek:
#
# save_price(
#     PRODUCTS[0],
#     "A101",
#     199.90
# )
#
# --------------------------------------------------


def update_products():

    print("UCUZA fiyat motoru başlatıldı.")

    for product in PRODUCTS:

        print(
            f"Ürün kontrol ediliyor: "
            f"{product['name']} "
            f"({product['barcode']})"
        )

        # Gerçek mağaza veri kaynakları
        # burada çalıştırılacak.


if __name__ == "__main__":
    update_products()
