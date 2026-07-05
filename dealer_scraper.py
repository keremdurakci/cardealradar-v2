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
    {"name": "Downtown Toyota",     "city": "Toronto",     "province": "ON", "url": "https://www.downtowntoyota.ca/our-promotions.html"},
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
        page.goto(url, timeout=30000, wait_until="networkidle")
        text = page.inner_text("body")
        browser.close()
        return text


def parse_dealer_offers(dealer: dict, raw_text: str) -> list[dict]:
    """
    Gerçek bayi sayfası formatı (Maple Toyota'dan doğrulandı, PBS/Dealer.com
    tabanlı çoğu Ontario Toyota bayisinde benzer şablon kullanılıyor):

      "Lease for $109 + HST weekly 60 Months @ 5.39% APR With $0 down
       20000 kms/yr Includes $5,000 Cash Incentive + $2,500 EVAP Rebate*"

    Model adı genelde bu satırın HEMEN ÜSTÜNDE ayrı bir başlık olarak
    geçiyor (fiyat satırıyla aynı cümlede değil) - bu yüzden metni satır
    satır tarayıp "en son görülen model adını" hafızada tutuyoruz.
    """
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    lines = raw_text.split("\n")
    results = []
    current_model = None
    current_year = TODAY.year

    lease_pattern = re.compile(
        r"Lease for \$(\d{2,4}).{0,20}?weekly\s*(\d{2,3})\s*Months?\s*@\s*(\d+\.\d+)%\s*APR"
        r"(?:.{0,20}?\$(\d{1,3}(?:,\d{3})?)\s*down)?"
        r"(?:.{0,20}?(\d{4,6})\s*kms?/yr)?",
        re.I
    )
    finance_pattern = re.compile(
        r"Finance for \$(\d{2,4}).{0,20}?weekly.{0,30}?@\s*(\d+\.\d+)%\s*APR",
        re.I
    )
    cash_incentive_pattern = re.compile(r"\$(\d{1,3}(?:,\d{3})?)\s*(Cash Incentive|EVAP Rebate)", re.I)

    for line in lines:
        # Bu satırda bir model adı geçiyor mu (yıl + model ismi birlikte)?
        year_model_match = re.search(r"(20(2[4-9]|3[0-1]))\s+([A-Za-z][A-Za-z0-9\- ]{2,20})", line)
        model_only_match = next((m for m in MODELS if m.lower() in line.lower()), None)
        if model_only_match:
            current_model = model_only_match
            if year_model_match:
                current_year = int(year_model_match.group(1))

        lease_match = lease_pattern.search(line)
        finance_match = finance_pattern.search(line)

        if lease_match and current_model:
            amount, term, apr, down, kms = lease_match.groups()
            cash = cash_incentive_pattern.findall(line)
            cash_note = "; ".join(f"${c[0]} {c[1]}" for c in cash) if cash else ""
            results.append({
                "id": make_id(dealer["name"], current_year, "toyota", current_model, "base"),
                "year": current_year,
                "make": "Toyota",
                "model": current_model,
                "trim": "",
                "offerType": "Lease",
                "payment": {"amount": int(amount), "currency": "CAD", "frequency": "weekly"},
                "apr": float(apr),
                "termMonths": int(term),
                "downPayment": int(down.replace(",", "")) if down else 0,
                "kmPerYear": int(kms) if kms else None,
                "expiry": None,
                "dealer": {"name": dealer["name"], "city": dealer["city"], "province": dealer["province"]},
                "image": "",
                "offerUrl": dealer["url"],
                "notes": cash_note,
            })
        elif finance_match and current_model:
            amount, apr = finance_match.groups()
            results.append({
                "id": make_id(dealer["name"], current_year, "toyota", current_model, "base"),
                "year": current_year,
                "make": "Toyota",
                "model": current_model,
                "trim": "",
                "offerType": "Finance",
                "payment": {"amount": int(amount), "currency": "CAD", "frequency": "weekly"},
                "apr": float(apr),
                "termMonths": None,
                "downPayment": None,
                "kmPerYear": None,
                "expiry": None,
                "dealer": {"name": dealer["name"], "city": dealer["city"], "province": dealer["province"]},
                "image": "",
                "offerUrl": dealer["url"],
                "notes": "",
            })

    # Aynı model+tip için birden fazla eşleşme varsa ilkini tut (genelde en güncel/üstteki)
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
