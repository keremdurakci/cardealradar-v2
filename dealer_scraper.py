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
    {"name": "Maple Toyota",        "city": "Vaughan",     "province": "ON", "url": "https://www.mapletoyota.com/our-promotions.html"},
    {"name": "Don Valley North Toyota", "city": "Markham",  "province": "ON", "url": "https://www.donvalleynorthtoyota.com/specials/new-specials/"},
    {"name": "Downtown Toyota",     "city": "Toronto",     "province": "ON", "url": "https://www.downtowntoyota.ca/new-vehicle-offers/"},
    {"name": "Toyota On The Park",  "city": "Toronto",     "province": "ON", "url": "https://www.toyotaonthepark.ca/our-promotions.html"},
    {"name": "Ken Shaw Toyota",     "city": "Toronto",     "province": "ON", "url": "https://www.kenshawtoyota.ca/our-promotions.html"},
    {"name": "Scarborough Toyota",  "city": "Toronto",     "province": "ON", "url": "https://www.scarboroughtoyota.ca/our-promotions.html"},
    {"name": "Erin Park Toyota",    "city": "Mississauga", "province": "ON", "url": "https://www.erinparktoyota.com/our-promotions.html"},
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
        # "networkidle" bazı sitelerde hiç tetiklenmiyor (sürekli arka plan
        # trafiği - chat widget, analytics vb.) - bu yüzden "load" + sabit
        # bekleme kullanıyoruz, daha güvenilir.
        page.goto(url, timeout=45000, wait_until="load")
        page.wait_for_timeout(4000)  # JS ile geç yüklenen fiyat bloklarının oturması için
        text = page.inner_text("body")
        browser.close()
        return text


def parse_dealer_offers(dealer: dict, raw_text: str) -> list[dict]:
    """
    Farklı bayiler farklı CMS kullanıyor, farklı kelimelerle yazıyor:
      - Maple Toyota (PBS):    "Lease for $109 + HST weekly 60 Months @ 5.39% APR"
      - Downtown Toyota (eDealer): "Lease For Only: $84* Weekly at 6.99% APR With: $1,500 Down* For 48 Months"

    Bu yüzden tek, esnek bir çekirdek kalıp kullanıyoruz: "$TUTAR ... Weekly ... X.XX% APR"
    - bağlayıcı kelimeler (for, only, at, +, HST, with) ne olursa olsun yakalar.
    "Down" ve "Months" bilgisini ayrıca, eşleşmenin yakın çevresinde (±120 karakter) arıyoruz.
    """
    flat = re.sub(r"\s+", " ", raw_text)  # tüm satır sonları/çoklu boşluklar -> tek boşluk

    # Çekirdek desen: $tutar + (Weekly bağlamı) + X.XX% APR - bağlayıcı kelimelerden bağımsız
    core_pattern = re.compile(
        r"\$(\d{2,4})\*?\s*(?:\+\s*HST\s*)?(?:Weekly|weekly)\b.{0,60}?(\d+\.\d{1,2})\s*%\s*APR",
        re.I
    )
    down_pattern = re.compile(r"\$?(\d{1,3}(?:,\d{3})?)\s*Down", re.I)
    term_pattern = re.compile(r"(?:For\s*)?(\d{2,3})\s*Months?", re.I)
    kms_pattern = re.compile(r"(\d{4,6})\s*kms?\s*/?\s*(?:yr|year)?", re.I)

    def find_nearest_model(pos: int) -> str | None:
        window = flat[max(0, pos - 150):pos]
        found = [m for m in MODELS if m.lower() in window.lower()]
        return found[-1] if found else None  # metinde en sona (fiyata) en yakın olanı al

    results = []
    for match in core_pattern.finditer(flat):
        model = find_nearest_model(match.start())
        if not model:
            continue

        amount, apr = match.groups()
        # Bazı bayilerde (Maple gibi) "60 Months" eşleşmenin İÇİNDE (weekly-APR arası),
        # bazılarında (Downtown gibi) eşleşmeden SONRA geçiyor - ikisini de tara.
        search_area = match.group(0) + " " + flat[match.end():match.end() + 120]
        down_match = down_pattern.search(search_area)
        term_match = term_pattern.search(search_area)
        kms_match = kms_pattern.search(search_area)

        results.append({
            "id": make_id(dealer["name"], TODAY.year, "toyota", model, "base"),
            "year": TODAY.year,
            "make": "Toyota",
            "model": model,
            "trim": "",
            "offerType": "Lease",
            "payment": {"amount": int(amount), "currency": "CAD", "frequency": "weekly"},
            "apr": float(apr),
            "termMonths": int(term_match.group(1)) if term_match else None,
            "downPayment": int(down_match.group(1).replace(",", "")) if down_match else 0,
            "kmPerYear": int(kms_match.group(1)) if kms_match else None,
            "expiry": None,
            "dealer": {"name": dealer["name"], "city": dealer["city"], "province": dealer["province"]},
            "image": "",
            "offerUrl": dealer["url"],
        })

    dedup = {}
    for r in results:
        key = (r["model"], r["offerType"])
        if key not in dedup:
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
