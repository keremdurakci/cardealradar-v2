"""
CarDealRadar - Bayi seviyesi scraper (mevcut Next.js projesinin data/offers.json şemasına uyumlu)
-----------------------------------------------------------------------------------------------------
ÇIKTI FORMATI (senin mevcut offers.json'unla birebir aynı):
{
  "id": "maple-toyota-2025-rav4-le-awd",
  "year": 2025, "make": "Toyota", "model": "RAV4", "trim": "LE AWD",
  "offerType": "Lease",
  "payment": { "amount": 105, "currency": "CAD", "frequency": "weekly" },
  "apr": 5.89, "termMonths": 40, "downPayment": 2300, "kmPerYear": 20000,
  "expiry": "2025-10-31",
  "dealer": { "name": "Maple Toyota", "city": "Vaughan", "province": "ON" },
  "image": "/offers/maple-toyota-rav4-2025-le-awd.png",
  "offerUrl": "https://www.mapletoyota.com/promotion-details/..."
}

DÜRÜST NOTLAR:
1. Her bayi CMS'i farklı yazıyor tekliflerini (bazıları "$105/week", bazıları
   "$105 bi-weekly", bazıları hiç haftalık göstermiyor sadece aylık). Bu yüzden
   PARSE_PATTERNS bölümünü ilk çalıştırmadan sonra, gerçek çıktıyı görüp
   ince ayar yapman gerekecek - tek seferlik bir iş.
2. "image" alanını otomatik dolduramıyorum (bayi sitelerindeki görseller
   senin /public/offers/ klasöründeki isimlendirmene uymayabilir) - bu alanı
   boş bırakıyorum, istersen elle tamamlarsın ya da placeholder gösterirsin.
3. GTA Toyota bayileriyle başlıyoruz (kanıt niteliğinde); onaylarsan aynı
   şablonu Honda/Ford/Hyundai GTA bayilerine de genişletirim.
"""

import json
import re
import hashlib
from datetime import datetime, timezone
from playwright.sync_api import sync_playwright

# GTA Toyota bayileri - promosyon/current-offers sayfaları
DEALERS = [
    {"name": "Maple Toyota",        "city": "Vaughan",     "province": "ON", "url": "https://www.mapletoyota.com/promotions"},
    {"name": "Don Valley North Toyota", "city": "Markham",  "province": "ON", "url": "https://www.donvalleynorthtoyota.com/specials/new-specials/"},
    {"name": "Downtown Toyota",     "city": "Toronto",     "province": "ON", "url": "https://www.downtowntoyota.ca/specials/new-specials/"},
    {"name": "Toyota On The Park",  "city": "Toronto",     "province": "ON", "url": "https://www.toyotaonthepark.ca/specials/new-specials/"},
    {"name": "Ken Shaw Toyota",     "city": "Toronto",     "province": "ON", "url": "https://www.kenshawtoyota.ca/specials/new-specials/"},
    {"name": "Scarborough Toyota",  "city": "Toronto",     "province": "ON", "url": "https://www.scarboroughtoyota.ca/specials/new-specials/"},
    {"name": "Erin Park Toyota",    "city": "Mississauga", "province": "ON", "url": "https://www.erinparktoyota.com/en/specials/new-specials"},
    {"name": "Yorkdale Toyota",     "city": "Toronto",     "province": "ON", "url": "https://www.yorkdaletoyota.com/our-promotions.html"},
]

MODELS = ["Corolla","Camry","RAV4","Highlander","Tacoma","Tundra","Sienna","Prius",
          "bZ","C-HR","4Runner","Crown","GR86","Supra","Sequoia","Venza","Corolla Cross"]

TODAY = datetime.now(timezone.utc)


def make_id(dealer_name: str, year, make, model, trim) -> str:
    slug = re.sub(r'[^a-z0-9]+', '-', f"{dealer_name}-{year}-{make}-{model}-{trim}".lower()).strip('-')
    return slug


def fetch_page_text(url: str) -> str:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(locale="en-CA")
        page.goto(url, timeout=30000, wait_until="networkidle")
        text = page.inner_text("body")
        browser.close()
        return text


def parse_dealer_offers(dealer: dict, raw_text: str) -> list[dict]:
    """
    Bayi sayfasındaki her 'model + haftalık ödeme + APR + vade' bloğunu
    yakalamaya çalışır. Gerçek sayfa yapıları farklılık gösterebileceği
    için bu regex'ler ilk çalıştırmadan sonra ayarlanmalı.
    """
    results = []
    chunks = re.split(r'(?<=[.\n])', raw_text)

    for chunk in chunks:
        model_found = next((m for m in MODELS if m.lower() in chunk.lower()), None)
        if not model_found:
            continue

        # Örnek: "$105 * / wk" veya "$105/week" veya "$105 Weekly"
        payment_match = re.search(r"\$(\d{2,4})\s*\*?\s*/?\s*(wk|week|weekly|bi-weekly)", chunk, re.I)
        apr_match = re.search(r"(\d\.\d{1,2})\s*%", chunk)
        term_match = re.search(r"(\d{2,3})\s*month", chunk, re.I)
        down_match = re.search(r"\$([\d,]{3,6})\s*(down|due at signing)", chunk, re.I)
        year_match = re.search(r"20(2[4-9]|3[0-1])", chunk)  # 2024-2031 arası model yılı

        if not payment_match:
            continue  # ödeme bilgisi yoksa güvenilir bir teklif sayılmaz, atla

        year = int(year_match.group()) if year_match else TODAY.year
        offer_id = make_id(dealer["name"], year, "toyota", model_found, "base")

        results.append({
            "id": offer_id,
            "year": year,
            "make": "Toyota",
            "model": model_found,
            "trim": "",  # bayi sayfasından trim çıkarımı güvenilir değil, elle tamamlanabilir
            "offerType": "Lease" if "lease" in chunk.lower() else "Finance",
            "payment": {
                "amount": int(payment_match.group(1)),
                "currency": "CAD",
                "frequency": "weekly" if "wk" in payment_match.group(2).lower() or "week" in payment_match.group(2).lower() else "bi-weekly",
            },
            "apr": float(apr_match.group(1)) if apr_match else None,
            "termMonths": int(term_match.group(1)) if term_match else None,
            "downPayment": int(down_match.group(1).replace(",", "")) if down_match else None,
            "kmPerYear": None,  # sayfa yapısına göre elle eklenmesi gerekebilir
            "expiry": None,     # çoğu bayi "ay sonu" der, kesin tarih nadiren yazılı olur
            "dealer": {"name": dealer["name"], "city": dealer["city"], "province": dealer["province"]},
            "image": "",  # elle doldurulacak / placeholder gösterilecek
            "offerUrl": dealer["url"],
        })

    # Aynı model için birden fazla eşleşme varsa, en yüksek bilgiye sahip olanı tut
    dedup = {}
    for r in results:
        key = (r["dealer"]["name"], r["model"])
        if key not in dedup or (r["apr"] and not dedup[key]["apr"]):
            dedup[key] = r
    return list(dedup.values())


def main():
    all_offers = []
    log = []
    for dealer in DEALERS:
        try:
            text = fetch_page_text(dealer["url"])
            offers = parse_dealer_offers(dealer, text)
            all_offers.extend(offers)
            log.append(f"[OK] {dealer['name']}: {len(offers)} teklif")
        except Exception as e:
            log.append(f"[HATA] {dealer['name']}: {e}")

    with open("offers.json", "w", encoding="utf-8") as f:
        json.dump(all_offers, f, ensure_ascii=False, indent=2)

    with open("scrape_log.txt", "w", encoding="utf-8") as f:
        f.write("\n".join(log))

    print("\n".join(log))
    print(f"\nToplam {len(all_offers)} teklif, {len(DEALERS)} bayiden tarandı.")


if __name__ == "__main__":
    main()
