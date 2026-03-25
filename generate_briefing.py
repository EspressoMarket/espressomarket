import os, requests, json, re, xml.etree.ElementTree as ET
from datetime import datetime, date
import anthropic

# === API-NYCKLAR ===
FINNHUB_KEY   = os.environ["FINNHUB_API_KEY"]
BEEHIIV_KEY   = os.environ["BEEHIIV_API_KEY"]
BEEHIIV_PUB   = os.environ["BEEHIIV_PUBLICATION_ID"]
ANTHROPIC_KEY = os.environ["ANTHROPIC_API_KEY"]
RESEND_KEY    = os.environ["RESEND_API_KEY"]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept-Language": "sv-SE,sv;q=0.9,en;q=0.8",
}

# =============================================================
# 1. KURSER & TERMINSPRISER (Yahoo Finance + Finnhub)
# =============================================================
def get_yahoo(symbol):
    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range=2d"
        r   = requests.get(url, headers=HEADERS, timeout=8).json()
        meta   = r["chart"]["result"][0]["meta"]
        price  = round(meta.get("regularMarketPrice", 0), 2)
        prev   = round(meta.get("previousClose", price), 2)
        change = round(((price - prev) / prev * 100) if prev else 0, 2)
        return {"price": price, "change": change}
    except Exception as e:
        print(f"Yahoo-fel {symbol}: {e}")
        return {"price": 0, "change": 0}

def get_finnhub(symbol):
    try:
        r = requests.get(
            f"https://finnhub.io/api/v1/quote?symbol={symbol}&token={FINNHUB_KEY}",
            timeout=8
        ).json()
        return {"price": round(r.get("c", 0), 2), "change": round(r.get("dp", 0), 2)}
    except Exception as e:
        print(f"Finnhub-fel {symbol}: {e}")
        return {"price": 0, "change": 0}

def get_all_market_data():
    futures = {
        "S&P 500 Futures": get_yahoo("ES=F"),
        "NASDAQ Futures":  get_yahoo("NQ=F"),
        "DAX Futures":     get_yahoo("FDAX=F"),
        "Olja (WTI)":      get_yahoo("CL=F"),
        "Guld":            get_yahoo("GC=F"),
        "VIX":             get_yahoo("^VIX"),
    }
    spots = {
        "OMX30":   get_yahoo("^OMXS30"),
        "S&P 500": get_yahoo("^GSPC"),
        "NASDAQ":  get_yahoo("^IXIC"),
        "EUR/USD": get_yahoo("EURUSD=X"),
        "USD/SEK": get_yahoo("USDSEK=X"),
        "EUR/SEK": get_yahoo("EURSEK=X"),
        "BTC/USD": get_finnhub("BINANCE:BTCUSDT"),
    }
    return futures, spots

# =============================================================
# 2. INVESTING.COM — EKONOMISK KALENDER (bästa makrokällan)
# =============================================================
def get_investing_calendar():
    """
    Hämtar dagens makrohändelser från Investing.com ekonomiska kalender.
    Täcker: Fed, ECB, Riksbanken, CPI, NFP, BNP, PMI m.m.
    """
    events = []
    today_str = date.today().strftime("%Y-%m-%d")

    try:
        # Investing.com Economic Calendar API (öppen endpoint)
        url = "https://economic-calendar.tradingview.com/events"
        params = {
            "from":       f"{today_str}T00:00:00.000Z",
            "to":         f"{today_str}T23:59:59.000Z",
            "countries":  "US,SE,EU,GB,DE,JP,CN,NO,DK,FI",  # Relevanta länder
            "importance": "2,3",  # 2=medium, 3=high
        }
        r = requests.get(url, params=params, headers=HEADERS, timeout=10).json()

        for e in r.get("result", []):
            country    = e.get("country", "")
            title      = e.get("title", "")
            importance = e.get("importance", 0)
            actual     = e.get("actual")
            forecast   = e.get("forecast")
            previous   = e.get("previous")
            time_utc   = e.get("date", "")[:16].replace("T", " ")

            if not title:
                continue

            imp_label = "🔴 HÖG" if importance == 3 else "🟡 MEDEL"
            line = f"{imp_label} [{country}] {title}"
            if actual is not None:
                line += f" — Utfall: {actual}"
                if forecast is not None:
                    line += f" (prognos: {forecast})"
            elif forecast is not None:
                line += f" — Prognos: {forecast}"
            if previous is not None:
                line += f" | Föregående: {previous}"
            events.append(line)

    except Exception as e:
        print(f"TradingView kalender-fel: {e}")

    # Fallback: Forexfactory RSS om TradingView misslyckas
    if not events:
        try:
            r = requests.get(
                "https://nfs.faireconomy.media/ff_calendar_thisweek.json",
                headers=HEADERS, timeout=10
            ).json()
            today = date.today().strftime("%m-%d-%Y")
            for e in r:
                if e.get("date", "").startswith(today) and e.get("impact") in ["High", "Medium"]:
                    country = e.get("country", "")
                    title   = e.get("title", "")
                    imp     = "🔴 HÖG" if e.get("impact") == "High" else "🟡 MEDEL"
                    forecast = e.get("forecast", "")
                    prev     = e.get("previous", "")
                    line = f"{imp} [{country}] {title}"
                    if forecast: line += f" — Prognos: {forecast}"
                    if prev:     line += f" | Föregående: {prev}"
                    events.append(line)
        except Exception as e2:
            print(f"Forexfactory-fel: {e2}")

    print(f"   {len(events)} makrohändelser hittade")
    return events[:12]

# =============================================================
# 3. SVENSKA RAPPORTER (Nasdaq OMX Nordic + Cision)
# =============================================================
def get_swedish_reports():
    """Hämtar svenska och nordiska bolagsrapporter för idag"""
    reports = []
    today   = date.today().strftime("%Y-%m-%d")

    # Källa 1: Finnhub earnings (nordiska bolag)
    try:
        r = requests.get(
            f"https://finnhub.io/api/v1/calendar/earnings?from={today}&to={today}&token={FINNHUB_KEY}",
            timeout=8
        ).json()
        nordic_suffixes = [".ST", ".HE", ".OL", ".CO", "-SE", "-FI", "-DK", "-NO"]
        nordic_tickers  = ["ERIC", "VOLV", "SAND", "SKF", "ALIV", "SWED", "SEB", "SSAB",
                           "ASSA", "ATCO", "BOL", "CAST", "GETI", "HEXA", "HUSQ", "INVE",
                           "KINV", "LATO", "NIBE", "PEAB", "SAAB", "SINCH", "SWMA", "TELE2"]
        for item in r.get("earningsCalendar", []):
            sym  = item.get("symbol", "")
            eps  = item.get("epsEstimate")
            hour = item.get("hour", "")
            if any(sym.endswith(s) for s in nordic_suffixes) or any(t in sym for t in nordic_tickers):
                line = sym
                if eps:  line += f" (EPS-est: {eps})"
                if hour: line += f" [{hour}]"
                reports.append(line)
    except Exception as e:
        print(f"Earnings-fel: {e}")

    # Källa 2: Cision PR Newswire Sverige RSS (pressreleaser samma dag)
    try:
        r = requests.get(
            "https://www.cision.com/se/pressreleaser/rss/",
            headers=HEADERS, timeout=8
        )
        root  = ET.fromstring(r.content)
        today_str = date.today().strftime("%d %b")
        for item in root.findall(".//item")[:10]:
            title = (item.findtext("title") or "").strip()
            pubdate = (item.findtext("pubDate") or "")
            if any(kw in title.lower() for kw in ["rapport", "bokslut", "delår", "resultat", "q1", "q2", "q3", "q4"]):
                reports.append(f"[Pressrelease] {title}")
    except Exception as e:
        print(f"Cision-fel: {e}")

    # Källa 3: Placera.se RSS (svenska börsrapporter)
    try:
        r = requests.get(
            "https://www.placera.se/placera/forstasidan.rss",
            headers=HEADERS, timeout=8
        )
        root = ET.fromstring(r.content)
        for item in root.findall(".//item")[:8]:
            title = re.sub(r'<[^>]+>', '', (item.findtext("title") or "")).strip()
            if any(kw in title.lower() for kw in ["rapport", "bokslut", "resultat", "vinst", "förlust"]):
                reports.append(f"[Placera] {title}")
    except Exception as e:
        print(f"Placera-fel: {e}")

    print(f"   {len(reports)} svenska/nordiska rapporter hittade")
    return reports[:10]

# =============================================================
# 4. RSS-NYHETER (realtid — internationellt + Sverige)
# =============================================================
def get_rss_headlines():
    feeds = [
        # Internationellt — marknader
        ("Reuters Markets",   "https://feeds.reuters.com/reuters/financialmarketsnews"),
        ("Reuters Business",  "https://feeds.reuters.com/reuters/businessNews"),
        ("CNBC Markets",      "https://www.cnbc.com/id/20910258/device/rss/rss.html"),
        ("Yahoo Finance",     "https://finance.yahoo.com/rss/topstories"),
        # Geopolitik (påverkar marknaden direkt)
        ("Reuters World",     "https://feeds.reuters.com/Reuters/worldNews"),
        # Sverige & Norden
        ("Dagens Industri",   "https://www.di.se/rss"),
        ("SvD Näringsliv",    "https://www.svd.se/feed/section/naringsliv.rss"),
        ("Placera",           "https://www.placera.se/placera/forstasidan.rss"),
        ("Breakit",           "https://www.breakit.se/feed/articles"),
        # Riksbanken
        ("Riksbanken",        "https://www.riksbank.se/sv/om-riksbanken/press-och-publicerat/rss/"),
    ]

    headlines = []
    for source, url in feeds:
        try:
            r    = requests.get(url, headers=HEADERS, timeout=8)
            root = ET.fromstring(r.content)
            ns   = {"atom": "http://www.w3.org/2005/Atom"}
            items = root.findall(".//item") or root.findall(".//atom:entry", ns)
            for item in items[:4]:
                title = (
                    re.sub(r'<[^>]+>', '', item.findtext("title") or
                    item.findtext("{http://www.w3.org/2005/Atom}title") or "")
                ).strip()
                desc = (
                    re.sub(r'<[^>]+>', '', item.findtext("description") or
                    item.findtext("{http://www.w3.org/2005/Atom}summary") or "")
                ).strip()[:150]
                if title and len(title) > 15:
                    headlines.append(f"[{source}] {title}: {desc}")
        except Exception as e:
            print(f"RSS-fel {source}: {e}")

    print(f"   {len(headlines)} RSS-rubriker hämtade")
    return headlines[:25]

# =============================================================
# 5. GENERERA BRIEFING — Claude söker + skriver
# =============================================================
def extract_json(text):
    text = re.sub(r'```json\s*', '', text)
    text = re.sub(r'```\s*', '', text)
    text = text.strip()
    start = text.find('{')
    end   = text.rfind('}')
    if start == -1 or end == -1:
        raise ValueError("Ingen JSON hittades")
    return json.loads(text[start:end+1])

def generate_briefing(futures, spots, rss, macro_events, swedish_reports):
    now      = datetime.now()
    today    = now.strftime("%A %d %B %Y")
    time_str = now.strftime("%H:%M")

    def fmt(d):
        sign = "+" if d["change"] >= 0 else ""
        return f"{d['price']} ({sign}{d['change']}%)"

    futures_str  = "\n".join([f"  {k}: {fmt(v)}" for k, v in futures.items()])
    spots_str    = "\n".join([f"  {k}: {fmt(v)}" for k, v in spots.items()])
    rss_str      = "\n".join([f"  - {h}" for h in rss]) if rss else "  Inga RSS-rubriker"
    macro_str    = "\n".join([f"  {e}" for e in macro_events]) if macro_events else "  Inga kända makrohändelser idag"
    reports_str  = "\n".join([f"  - {r}" for r in swedish_reports]) if swedish_reports else "  Inga kända svenska rapporter idag"

    context = f"""ESPRESSO MARKET DATA — {today} kl. {time_str}

=== TERMINSPRISER (pre-market indikatorer) ===
{futures_str}
(DAX Futures = bästa proxy för OMX30 på morgonen. VIX > 20 = förhöjd oro.)

=== STÄNGNINGSKURSER IGÅR ===
{spots_str}

=== MAKROKALENDER IDAG (Investing.com / Forexfactory) ===
{macro_str}

=== SVENSKA & NORDISKA RAPPORTER IDAG ===
{reports_str}

=== RSS-NYHETER (realtid från Reuters, DI, CNBC, Placera m.fl.) ===
{rss_str}"""

    print("=== KONTEXT TILL CLAUDE (preview) ===")
    print(context[:800])
    print("=====================================")

    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)

    system_prompt = f"""Du är Espresso Market — Sveriges skarpaste AI-finansbriefing. Datum: {today}.

DIN PROCESS:
1. Läs kontextdatan nedan noggrant (terminspriser, makrokalender, rapporter, RSS-nyheter)
2. Använd web_search för att komplettera med det senaste:
   - Sök: "market overnight news {today}" — Wall Street stängning, Asien i morse
   - Sök: "OMX Stockholm börsen {today}" — svensk börs
   - Sök på de viktigaste makrohändelserna i kalendern (t.ex. "Fed meeting {today}", "US CPI {today}")
   - Sök på de svenska rapporterna som nämns
   - Sök på det mest aktuella geopolitiska temat (Iran, tullar, krig, energi etc.)
3. Skriv en faktabaserad briefing baserad på vad du faktiskt hittat

KRAV PÅ INNEHÅLLET:
- Varje punkt ska handla om ett RIKTIGT händelse/tema från idag
- Analytiker: MÅSTE nämna terminspriser med siffror, dagens makrohändelser och rapporter
- Nybörjare: förklara VARFÖR marknaden rör sig — konkret orsak ("Eftersom Fed signalerade...")
- Pension: koppla nyheten till svenska pensionsfonder (AP7, AMF, SPP) när relevant
- Om VIX är förhöjd (>20): nämn det och vad det betyder
- Om det är en stor makrodag (Fed, ECB, Riksbanken, CPI): gör det till huvudtemat

Svara med EXAKT denna JSON-struktur efter dina sökningar:
{{"headline":"rubrik max 10 ord — dagens viktigaste marknadstema","date":"{today}","beginner":[{{"icon":"📈","label":"RUBRIK MED STORA BOKSTÄVER","text":"Vad hände och varför — 2 konkreta meningar","explain":"💡 Vad det betyder för en vanlig person — 2 meningar"}}],"analyst":[{{"icon":"📊","label":"RUBRIK MED STORA BOKSTÄVER","text":"Teknisk/fundamental analys med siffror — 2-3 meningar"}}],"pension":[{{"icon":"🌱","label":"RUBRIK MED STORA BOKSTÄVER","text":"Hur detta påverkar pensionssparare — 2 meningar","tip":"💡 Konkret råd eller vad man bör tänka på — 2 meningar"}}],"sources":["Reuters","Di","Placera","källa4"]}}

EXAKT 4 punkter per nivå. Avsluta alltid med JSON."""

    msg = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=5000,
        tools=[{"type": "web_search_20250305", "name": "web_search"}],
        system=system_prompt,
        messages=[{
            "role":    "user",
            "content": f"Sök efter nattens och morgonens marknadsnyheter, sedan generera briefingen. Kontextdata:\n\n{context}"
        }]
    )

    full_text = ""
    for block in msg.content:
        if hasattr(block, "type") and block.type == "text":
            full_text += block.text

    print(f"AI-svar (första 400 tecken): {full_text[:400]}")
    return extract_json(full_text)

# =============================================================
# 6. SPARA
# =============================================================
def save_briefing(data, futures, spots):
    os.makedirs("data", exist_ok=True)
    output = {
        "generated": datetime.now().isoformat(),
        "quotes":    spots,
        "futures":   futures,
        "briefing":  data
    }
    with open("data/briefing.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print("✅ Briefing sparad till data/briefing.json")

# =============================================================
# 7. PRENUMERANTER
# =============================================================
def get_subscribers():
    subscribers = []
    page = 1
    while True:
        r = requests.get(
            f"https://api.beehiiv.com/v2/publications/{BEEHIIV_PUB}/subscriptions",
            headers={"Authorization": f"Bearer {BEEHIIV_KEY}"},
            params={"status": "active", "limit": 100, "page": page, "expand[]": "custom_fields"}
        )
        data = r.json()
        subs = data.get("data", [])
        if not subs:
            break
        for s in subs:
            email = s["email"]
            niva  = "beginner"
            for field in s.get("custom_fields", []):
                if field.get("name") == "niva" and field.get("value"):
                    niva = field["value"].lower()
                    break
            subscribers.append({"email": email, "niva": niva})
        if len(subs) < 100:
            break
        page += 1
    print(f"Hittade {len(subscribers)} prenumeranter")
    return subscribers

# =============================================================
# 8. BYGG EMAIL
# =============================================================
def build_email(data, niva, futures):
    today = datetime.now().strftime("%d %B %Y")

    futures_html = ""
    for name, fv in futures.items():
        if fv["price"] == 0:
            continue
        up    = fv["change"] >= 0
        arrow = "▲" if up else "▼"
        col   = "#5bbf8a" if up else "#e06060"
        futures_html += (
            f'<span style="margin-right:10px;white-space:nowrap;font-family:monospace;font-size:0.76rem">'
            f'<span style="color:#8a7560">{name}</span> '
            f'<span style="color:{col}">{arrow}{abs(fv["change"])}%</span>'
            f'</span>'
        )

    if niva == "analyst":
        bullets = data.get("analyst", [])
        color   = "#d4a55a"
        label   = "📊 ANALYTIKER"
        rows = "".join([
            f'<tr><td style="padding:14px 0;border-bottom:1px solid #f0e8d8">'
            f'<span style="font-size:1.1rem">{b["icon"]}</span>'
            f'<strong style="color:#d4a55a;font-size:0.66rem;letter-spacing:0.12em;text-transform:uppercase;display:block;margin:5px 0">{b["label"]}</strong>'
            f'<span style="color:#3d2510;font-size:0.88rem;line-height:1.65">{b["text"]}</span>'
            f'</td></tr>'
            for b in bullets
        ])
    elif niva == "pension":
        bullets = data.get("pension", [])
        color   = "#5bbf8a"
        label   = "🌱 PENSIONSSPARARE"
        rows = "".join([
            f'<tr><td style="padding:14px 0;border-bottom:1px solid #f0e8d8">'
            f'<span style="font-size:1.1rem">{b["icon"]}</span>'
            f'<strong style="color:#5bbf8a;font-size:0.66rem;letter-spacing:0.12em;text-transform:uppercase;display:block;margin:5px 0">{b["label"]}</strong>'
            f'<span style="color:#3d2510;font-size:0.88rem;line-height:1.65">{b["text"]}</span>'
            f'<span style="display:block;margin-top:7px;padding:9px 13px;background:#f0fdf6;border-left:3px solid #5bbf8a;color:#1a3a2a;font-size:0.8rem;line-height:1.55">{b.get("tip","")}</span>'
            f'</td></tr>'
            for b in bullets
        ])
    else:
        bullets = data.get("beginner", [])
        color   = "#7ab3d4"
        label   = "☕ NYBÖRJARE"
        rows = "".join([
            f'<tr><td style="padding:14px 0;border-bottom:1px solid #f0e8d8">'
            f'<span style="font-size:1.1rem">{b["icon"]}</span>'
            f'<strong style="color:#7ab3d4;font-size:0.66rem;letter-spacing:0.12em;text-transform:uppercase;display:block;margin:5px 0">{b["label"]}</strong>'
            f'<span style="color:#3d2510;font-size:0.88rem;line-height:1.65">{b["text"]}</span>'
            f'<span style="display:block;margin-top:7px;padding:9px 13px;background:#f0f7fd;border-left:3px solid #7ab3d4;color:#1a3a4a;font-size:0.8rem;line-height:1.55">{b.get("explain","")}</span>'
            f'</td></tr>'
            for b in bullets
        ])

    sources = " · ".join(data.get("sources", []))

    return f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"></head>
<body style="margin:0;padding:0;background:#f5ead6;font-family:'Georgia',serif">
<div style="max-width:600px;margin:0 auto;background:#1a1208">
  <div style="background:linear-gradient(135deg,#1a1208,#3d2510);padding:32px 40px;text-align:center;border-bottom:2px solid {color}">
    <p style="color:{color};font-size:0.63rem;letter-spacing:0.2em;text-transform:uppercase;margin:0 0 8px">☕ ESPRESSO MARKET · {label}</p>
    <h1 style="color:#f5ead6;font-size:1.45rem;margin:0;line-height:1.2">{data["headline"]}</h1>
    <p style="color:#8a7560;font-size:0.76rem;margin:10px 0 0">{today}</p>
  </div>
  <div style="padding:13px 32px;background:#0f0b05;border-bottom:1px solid #3d2510;text-align:center">
    <p style="color:#8a7560;font-size:0.56rem;letter-spacing:0.14em;text-transform:uppercase;margin:0 0 7px">TERMINSPRISER I MORSE</p>
    <div style="line-height:2.2">{futures_html}</div>
  </div>
  <div style="padding:28px 40px;background:#fff8f0">
    <table style="width:100%;border-collapse:collapse">{rows}</table>
  </div>
  <div style="padding:11px 40px;background:#fdf5e8;border-top:1px solid #f0e8d8;text-align:center">
    <p style="color:#c49a6c;font-size:0.6rem;margin:0">Källor: {sources}</p>
  </div>
  <div style="padding:22px 40px;background:#1a1208;text-align:center">
    <a href="https://espressomarket.se" style="display:inline-block;background:linear-gradient(135deg,#c49a6c,{color});color:#1a1208;padding:11px 26px;font-size:0.78rem;font-weight:bold;letter-spacing:0.08em;text-transform:uppercase;text-decoration:none;border-radius:24px">Läs hela briefingen →</a>
    <p style="color:#8a7560;font-size:0.66rem;margin:12px 0 0">Espresso Market · Gratis varje vardag kl. 07:00</p>
  </div>
</div>
</body></html>"""

# =============================================================
# 9. SKICKA EMAIL
# =============================================================
def send_with_resend(data, subscribers, futures):
    if not subscribers:
        print("Inga prenumeranter att skicka till")
        return

    counts = {"beginner": 0, "analyst": 0, "pension": 0, "error": 0}
    for sub in subscribers:
        email = sub["email"]
        niva  = sub["niva"] if sub["niva"] in ["beginner", "analyst", "pension"] else "beginner"
        html  = build_email(data, niva, futures)
        r = requests.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {RESEND_KEY}", "Content-Type": "application/json"},
            json={
                "from":    "Espresso Market <briefing@espressomarket.se>",
                "to":      email,
                "subject": f"☕ {data['headline']}",
                "html":    html
            }
        )
        if r.status_code in [200, 201]:
            counts[niva] += 1
        else:
            counts["error"] += 1
            print(f"Fel för {email}: {r.status_code}")

    total = sum(v for k, v in counts.items() if k != "error")
    print(f"✅ Skickade till {total} prenumeranter")
    print(f"   Nybörjare: {counts['beginner']} | Analytiker: {counts['analyst']} | Pension: {counts['pension']} | Fel: {counts['error']}")

# =============================================================
# MAIN
# =============================================================
if __name__ == "__main__":
    print("📈 Hämtar kurser och terminspriser...")
    futures, spots = get_all_market_data()
    for k, v in futures.items():
        sign = "+" if v["change"] >= 0 else ""
        print(f"   {k}: {v['price']} ({sign}{v['change']}%)")

    print("🌍 Hämtar makrokalender (Investing.com/Forexfactory)...")
    macro = get_investing_calendar()
    for e in macro[:3]:
        print(f"   {e}")

    print("🇸🇪 Hämtar svenska rapporter...")
    swedish_reports = get_swedish_reports()

    print("📰 Hämtar RSS-nyheter i realtid...")
    rss = get_rss_headlines()

    print("🤖 Claude söker nattens nyheter och genererar briefing...")
    briefing = generate_briefing(futures, spots, rss, macro, swedish_reports)

    save_briefing(briefing, futures, spots)

    print("👥 Hämtar prenumeranter...")
    subscribers = get_subscribers()

    print("📧 Skickar email...")
    send_with_resend(briefing, subscribers, futures)

    print("✅ Klart!")
