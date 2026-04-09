import os, requests, json, re, xml.etree.ElementTree as ET, time
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
# 1. KURSER & TERMINSPRISER — med korrekt prisförändring
# =============================================================
def get_yahoo(symbol):
    """
    Hämtar pris + förändring. Använder range=5d så vi alltid
    har previousClose att jämföra med, även tidigt på morgonen.
    """
    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range=5d"
        r   = requests.get(url, headers=HEADERS, timeout=10).json()
        meta = r["chart"]["result"][0]["meta"]

        price = round(meta.get("regularMarketPrice", 0), 2)

        # Försök hämta regularMarketChangePercent direkt
        change = meta.get("regularMarketChangePercent")
        if change is not None:
            change = round(change, 2)
        else:
            # Räkna ut från previousClose
            prev   = meta.get("previousClose") or meta.get("chartPreviousClose") or price
            change = round(((price - prev) / prev * 100) if prev else 0, 2)

        prev_close = round(meta.get("previousClose") or meta.get("chartPreviousClose") or price, 2)

        return {"price": price, "change": change, "prev": prev_close}
    except Exception as e:
        print(f"Yahoo-fel {symbol}: {e}")
        return {"price": 0, "change": 0, "prev": 0}

def get_finnhub(symbol):
    try:
        r = requests.get(
            f"https://finnhub.io/api/v1/quote?symbol={symbol}&token={FINNHUB_KEY}",
            timeout=8
        ).json()
        price  = round(r.get("c", 0), 2)
        change = round(r.get("dp", 0), 2)
        prev   = round(r.get("pc", price), 2)
        return {"price": price, "change": change, "prev": prev}
    except Exception as e:
        print(f"Finnhub-fel {symbol}: {e}")
        return {"price": 0, "change": 0, "prev": 0}

def get_all_market_data():
    print("   Hämtar terminspriser...")
    futures = {
        "S&P 500 Futures": get_yahoo("ES=F"),
        "NASDAQ Futures":  get_yahoo("NQ=F"),
        "DAX":             get_yahoo("^GDAXI"),
        "Olja (WTI)":      get_yahoo("CL=F"),
        "Guld":            get_yahoo("GC=F"),
        "VIX":             get_yahoo("^VIX"),
    }
    print("   Hämtar spotpriser...")
    spots = {
        "OMX30":   get_yahoo("^OMXS30"),
        "S&P 500": get_yahoo("^GSPC"),
        "NASDAQ":  get_yahoo("^IXIC"),
        "EUR/USD": get_yahoo("EURUSD=X"),
        "USD/SEK": get_yahoo("USDSEK=X"),
        "EUR/SEK": get_yahoo("EURSEK=X"),
        "BTC/USD": get_finnhub("BINANCE:BTCUSDT"),
    }

    # Logga alla priser
    for k, v in {**futures, **spots}.items():
        sign = "+" if v["change"] >= 0 else ""
        print(f"   {k}: {v['price']} ({sign}{v['change']}%)")

    return futures, spots

# =============================================================
# 2. MAKROKALENDER
# =============================================================
def get_macro_calendar():
    events = []
    try:
        r = requests.get(
            "https://nfs.faireconomy.media/ff_calendar_thisweek.json",
            headers=HEADERS, timeout=10
        ).json()
        today = date.today().strftime("%m-%d-%Y")
        for e in r:
            if not e.get("date", "").startswith(today): continue
            if e.get("impact") not in ["High", "Medium"]: continue
            country  = e.get("country", "")
            title    = e.get("title", "")
            impact   = e.get("impact", "")
            forecast = e.get("forecast", "")
            prev     = e.get("previous", "")
            icon     = "🔴" if impact == "High" else "🟡"
            line     = f"{icon} [{country}] {title}"
            if forecast: line += f" — Prognos: {forecast}"
            if prev:     line += f" | Föregående: {prev}"
            events.append(line)
        print(f"   Forexfactory: {len(events)} händelser")
    except Exception as e:
        print(f"Forexfactory-fel: {e}")

    if not events:
        try:
            today_str = date.today().strftime("%Y-%m-%d")
            r = requests.get(
                f"https://finnhub.io/api/v1/calendar/economic?from={today_str}&to={today_str}&token={FINNHUB_KEY}",
                timeout=8
            ).json()
            for e in r.get("economicCalendar", []):
                event  = e.get("event", "")
                impact = e.get("impact", "")
                country = e.get("country", "")
                if event and impact in ["high", "medium"]:
                    icon = "🔴" if impact == "high" else "🟡"
                    events.append(f"{icon} [{country}] {event}")
            print(f"   Finnhub backup: {len(events)} händelser")
        except Exception as e2:
            print(f"Finnhub makro-fel: {e2}")
    return events[:12]

# =============================================================
# 3. SVENSKA RAPPORTER
# =============================================================
def get_swedish_reports():
    reports = []
    for url, source in [
        ("https://www.placera.se/placera/forstasidan.rss", "Placera"),
        ("https://www.di.se/rss", "DI"),
    ]:
        try:
            r    = requests.get(url, headers=HEADERS, timeout=8)
            root = ET.fromstring(r.content)
            for item in root.findall(".//item")[:15]:
                title = re.sub(r'<[^>]+>', '', item.findtext("title") or "").strip()
                if any(kw in title.lower() for kw in ["rapport", "bokslut", "resultat", "vinst", "förlust", "q1", "q2", "q3", "q4", "delår"]):
                    reports.append(f"[{source}] {title}")
        except Exception as e:
            print(f"{source}-fel: {e}")

    try:
        today_str = date.today().strftime("%Y-%m-%d")
        r = requests.get(
            f"https://finnhub.io/api/v1/calendar/earnings?from={today_str}&to={today_str}&token={FINNHUB_KEY}",
            timeout=8
        ).json()
        nordic  = [".ST", ".HE", ".OL", ".CO"]
        tickers = ["ERIC", "VOLV", "SAND", "SKF", "SWED", "SEB", "SSAB", "ASSA",
                   "ATCO", "BOL", "INVE", "KINV", "NIBE", "SAAB", "TELE2", "SINCH"]
        for item in r.get("earningsCalendar", []):
            sym = item.get("symbol", "")
            eps = item.get("epsEstimate")
            if any(sym.endswith(s) for s in nordic) or any(t in sym for t in tickers):
                line = sym
                if eps: line += f" (EPS-est: {eps})"
                reports.append(f"[Finnhub] {line}")
    except Exception as e:
        print(f"Finnhub earnings-fel: {e}")

    seen, unique = set(), []
    for r in reports:
        key = r[:50]
        if key not in seen:
            seen.add(key)
            unique.append(r)
    print(f"   {len(unique)} svenska/nordiska rapporter hittade")
    return unique[:10]

# =============================================================
# 4. RSS-NYHETER
# =============================================================
def get_rss_headlines():
    feeds = [
        ("MarketWatch",     "https://feeds.marketwatch.com/marketwatch/topstories/"),
        ("CNBC Markets",    "https://www.cnbc.com/id/20910258/device/rss/rss.html"),
        ("Yahoo Finance",   "https://finance.yahoo.com/rss/topstories"),
        ("Investing.com",   "https://www.investing.com/rss/news_25.rss"),
        ("Dagens Industri", "https://www.di.se/rss"),
        ("Placera",         "https://www.placera.se/placera/forstasidan.rss"),
        ("Breakit",         "https://www.breakit.se/feed/articles"),
        ("Affärsvärlden",   "https://www.affarsvarlden.se/rss.xml"),
    ]
    headlines = []
    for source, url in feeds:
        try:
            r    = requests.get(url, headers=HEADERS, timeout=8)
            root = ET.fromstring(r.content)
            ns   = {"atom": "http://www.w3.org/2005/Atom"}
            items = root.findall(".//item") or root.findall(".//atom:entry", ns)
            for item in items[:4]:
                title = re.sub(r'<[^>]+>', '', (
                    item.findtext("title") or
                    item.findtext("{http://www.w3.org/2005/Atom}title") or ""
                )).strip()
                desc = re.sub(r'<[^>]+>', '', (
                    item.findtext("description") or
                    item.findtext("{http://www.w3.org/2005/Atom}summary") or ""
                )).strip()[:150]
                if title and len(title) > 15:
                    headlines.append(f"[{source}] {title}: {desc}")
        except Exception as e:
            print(f"RSS-fel {source}: {e}")
    print(f"   {len(headlines)} RSS-rubriker hämtade")
    return headlines[:25]

# =============================================================
# 5. GENERERA BRIEFING — KORT (email) + LÅNG (hemsida)
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
        if d["price"] == 0: return "ej tillgänglig"
        sign = "+" if d["change"] >= 0 else ""
        return f"{d['price']} ({sign}{d['change']}%)"

    futures_str = "\n".join([f"  {k}: {fmt(v)}" for k, v in futures.items()])
    spots_str   = "\n".join([f"  {k}: {fmt(v)}" for k, v in spots.items()])
    rss_str     = "\n".join([f"  - {h}" for h in rss]) if rss else "  Inga RSS-rubriker"
    macro_str   = "\n".join([f"  {e}" for e in macro_events]) if macro_events else "  Inga kända makrohändelser idag"
    reports_str = "\n".join([f"  - {r}" for r in swedish_reports]) if swedish_reports else "  Inga kända svenska rapporter idag"

    context = f"""ESPRESSO MARKET DATA — {today} kl. {time_str}

=== TERMINSPRISER (pre-market) ===
{futures_str}
(DAX = europeisk proxy för OMX30. VIX > 20 = förhöjd oro, > 30 = panik.)

=== STÄNGNINGSKURSER IGÅR ===
{spots_str}

=== MAKROKALENDER IDAG ===
{macro_str}

=== SVENSKA & NORDISKA RAPPORTER IDAG ===
{reports_str}

=== RSS-NYHETER (realtid) ===
{rss_str}"""

    print("=== KONTEXT TILL CLAUDE (preview) ===")
    print(context[:600])
    print("=====================================")

    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)

    system_prompt = f"""Du är Espresso Market — Sveriges skarpaste AI-finansbriefing. Datum: {today}.

PROCESS:
1. Läs kontextdatan (terminspriser, makro, rapporter, RSS)
2. Använd web_search:
   - "stock market overnight {today}"
   - "OMX Stockholm {today}"
   - Sök på makrohändelserna i kalendern
   - Sök på det dominerande geopolitiska temat
3. Skriv faktabaserad briefing

KRAV:
- Varje punkt = riktig konkret händelse från idag
- Analytiker: terminspriser med siffror + makro + rapporter
- Nybörjare: orsak → effekt på enkelt språk
- Pension: koppla till AP7/AMF/SPP när relevant
- VIX > 20: kommentera
- Stor makrodag (Fed/ECB/Riksbanken/CPI): gör det till huvudtemat

VIKTIGT — du måste returnera ALLA sex sektioner:
- beginner/analyst/pension = kort version för EMAIL (2-3 meningar per punkt)
- full_beginner/full_analyst/full_pension = lång version för HEMSIDAN (4-6 meningar per punkt + extra fält)

Svara med exakt denna JSON:
{{
  "headline": "rubrik max 10 ord",
  "date": "{today}",
  "date_short": "{now.strftime('%d %b %Y')}",
  "sources": ["källa1","källa2","källa3","källa4"],
  "beginner": [
    {{"icon":"📈","label":"RUBRIK","text":"2-3 meningar om vad som hänt","explain":"💡 kort förklaring för nybörjare"}}
  ],
  "analyst": [
    {{"icon":"📊","label":"RUBRIK","text":"2-3 meningar teknisk analys med siffror"}}
  ],
  "pension": [
    {{"icon":"🌱","label":"RUBRIK","text":"2-3 meningar om pensionspåverkan","tip":"💡 kort råd"}}
  ],
  "full_beginner": [
    {{"icon":"📈","label":"RUBRIK","text":"4-6 meningar djupare förklaring av vad som hänt och varför","explain":"💡 Vad det konkret betyder för en vanlig person, 3-4 meningar","background":"📖 Bakgrund: Varför är detta viktigt just nu, 2-3 meningar"}}
  ],
  "full_analyst": [
    {{"icon":"📊","label":"RUBRIK","text":"4-6 meningar djup teknisk och fundamental analys med konkreta siffror och nivåer","detail":"🔍 Nyckeltal och tekniska nivåer att bevaka, 3-4 meningar","outlook":"🎯 Vad händer härnäst och vad triggar nästa rörelse, 2-3 meningar"}}
  ],
  "full_pension": [
    {{"icon":"🌱","label":"RUBRIK","text":"4-6 meningar om hur detta påverkar pensionssparare på lång sikt","tip":"💡 Konkret råd om vad man bör tänka på eller göra, 3-4 meningar","funds":"🏦 Hur AP7, AMF, SPP eller andra svenska pensionsfonder berörs, 2-3 meningar"}}
  ]
}}

EXAKT 4 punkter i VARJE sektion (beginner, analyst, pension, full_beginner, full_analyst, full_pension).
Avsluta alltid med hela JSON-blocket."""

    msg = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=10000,
        tools=[{"type": "web_search_20250305", "name": "web_search"}],
        system=system_prompt,
        messages=[{"role": "user", "content": f"Sök efter nattens marknadsnyheter och generera briefingen.\n\nKontextdata:\n\n{context}"}]
    )

    full_text = ""
    for block in msg.content:
        if hasattr(block, "type") and block.type == "text":
            full_text += block.text

    print(f"AI-svar (första 400 tecken): {full_text[:400]}")
    return extract_json(full_text)

# =============================================================
# 6. SPARA + ARKIV
# =============================================================
def save_briefing(data, futures, spots):
    os.makedirs("data", exist_ok=True)

    # Spara dagens briefing
    output = {
        "generated": datetime.now().isoformat(),
        "quotes":    spots,
        "futures":   futures,
        "briefing":  data
    }
    with open("data/briefing.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print("✅ Briefing sparad till data/briefing.json")

    # Spara till arkiv — alltid, även om full_* saknas
    archive_path = "data/archive.json"
    archive = []
    if os.path.exists(archive_path):
        try:
            with open(archive_path, "r", encoding="utf-8") as f:
                archive = json.load(f)
        except:
            archive = []

    archive_entry = {
        "date":          data.get("date", datetime.now().strftime("%A %d %B %Y")),
        "date_short":    data.get("date_short", datetime.now().strftime("%d %b %Y")),
        "generated":     datetime.now().isoformat(),
        "headline":      data.get("headline", ""),
        "sources":       data.get("sources", []),
        "beginner":      data.get("beginner", []),
        "analyst":       data.get("analyst", []),
        "pension":       data.get("pension", []),
        # Fallback: om full_* saknas, använd kort version
        "full_beginner": data.get("full_beginner") or data.get("beginner", []),
        "full_analyst":  data.get("full_analyst")  or data.get("analyst", []),
        "full_pension":  data.get("full_pension")  or data.get("pension", []),
        "futures":       futures,
        "quotes":        spots,
    }

    # Ta bort eventuell dubblett för samma dag
    today_str = date.today().isoformat()
    archive   = [a for a in archive if not a.get("generated", "").startswith(today_str)]
    archive.insert(0, archive_entry)
    archive   = archive[:30]

    with open(archive_path, "w", encoding="utf-8") as f:
        json.dump(archive, f, ensure_ascii=False, indent=2)
    print(f"✅ Arkiv uppdaterat — {len(archive)} briefingar sparade")

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
        if not subs: break
        for s in subs:
            email = s["email"]
            niva  = "beginner"
            for field in s.get("custom_fields", []):
                if field.get("name") == "niva" and field.get("value"):
                    niva = field["value"].lower()
                    break
            subscribers.append({"email": email, "niva": niva})
        if len(subs) < 100: break
        page += 1
    print(f"Hittade {len(subscribers)} prenumeranter")
    return subscribers

# =============================================================
# 8. BYGG EMAIL — med fungerande terminspriser
# =============================================================
def build_email(data, niva, futures):
    today = datetime.now().strftime("%d %B %Y")

    # Terminspriser — filtrera bort 0-värden
    futures_html = ""
    for name, fv in futures.items():
        if not fv.get("price") or fv["price"] == 0:
            continue
        up    = fv["change"] >= 0
        arrow = "▲" if up else "▼"
        col   = "#5bbf8a" if up else "#e06060"
        change_str = f"{'+' if up else ''}{fv['change']}%"
        futures_html += (
            f'<span style="display:inline-block;margin:3px 8px 3px 0;white-space:nowrap;'
            f'font-family:monospace;font-size:0.76rem">'
            f'<span style="color:#8a7560">{name}</span> '
            f'<span style="color:{col};font-weight:600">{arrow}{abs(fv["change"])}%</span>'
            f'</span>'
        )

    if not futures_html:
        futures_html = '<span style="color:#8a7560;font-size:0.76rem">Kurser ej tillgängliga</span>'

    if niva == "analyst":
        bullets = data.get("analyst", [])
        color   = "#d4a55a"
        label   = "📊 ANALYTIKER"
        cta_url = "https://espressomarket.se?niva=analyst"
        rows = "".join([
            f'<tr><td style="padding:16px 0;border-bottom:1px solid #f0e8d8">'
            f'<span style="font-size:1.2rem">{b["icon"]}</span>'
            f'<strong style="color:#d4a55a;font-size:0.66rem;letter-spacing:0.12em;text-transform:uppercase;display:block;margin:6px 0 4px">{b["label"]}</strong>'
            f'<span style="color:#3d2510;font-size:0.9rem;line-height:1.7">{b["text"]}</span>'
            f'</td></tr>'
            for b in bullets
        ])
    elif niva == "pension":
        bullets = data.get("pension", [])
        color   = "#5bbf8a"
        label   = "🌱 PENSIONSSPARARE"
        cta_url = "https://espressomarket.se?niva=pension"
        rows = "".join([
            f'<tr><td style="padding:16px 0;border-bottom:1px solid #f0e8d8">'
            f'<span style="font-size:1.2rem">{b["icon"]}</span>'
            f'<strong style="color:#5bbf8a;font-size:0.66rem;letter-spacing:0.12em;text-transform:uppercase;display:block;margin:6px 0 4px">{b["label"]}</strong>'
            f'<span style="color:#3d2510;font-size:0.9rem;line-height:1.7">{b["text"]}</span>'
            f'<span style="display:block;margin-top:8px;padding:10px 14px;background:#f0fdf6;border-left:3px solid #5bbf8a;color:#1a3a2a;font-size:0.82rem;line-height:1.6">{b.get("tip","")}</span>'
            f'</td></tr>'
            for b in bullets
        ])
    else:
        bullets = data.get("beginner", [])
        color   = "#7ab3d4"
        label   = "☕ NYBÖRJARE"
        cta_url = "https://espressomarket.se?niva=beginner"
        rows = "".join([
            f'<tr><td style="padding:16px 0;border-bottom:1px solid #f0e8d8">'
            f'<span style="font-size:1.2rem">{b["icon"]}</span>'
            f'<strong style="color:#7ab3d4;font-size:0.66rem;letter-spacing:0.12em;text-transform:uppercase;display:block;margin:6px 0 4px">{b["label"]}</strong>'
            f'<span style="color:#3d2510;font-size:0.9rem;line-height:1.7">{b["text"]}</span>'
            f'<span style="display:block;margin-top:8px;padding:10px 14px;background:#f0f7fd;border-left:3px solid #7ab3d4;color:#1a3a4a;font-size:0.82rem;line-height:1.6">{b.get("explain","")}</span>'
            f'</td></tr>'
            for b in bullets
        ])

    sources = " · ".join(data.get("sources", []))

    return f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"></head>
<body style="margin:0;padding:0;background:#f5ead6;font-family:'Georgia',serif">
<div style="max-width:600px;margin:0 auto;background:#1a1208">

  <!-- HEADER -->
  <div style="background:linear-gradient(135deg,#1a1208,#3d2510);padding:32px 40px;text-align:center;border-bottom:2px solid {color}">
    <p style="color:{color};font-size:0.63rem;letter-spacing:0.2em;text-transform:uppercase;margin:0 0 10px">☕ ESPRESSO MARKET · {label}</p>
    <h1 style="color:#f5ead6;font-size:1.5rem;margin:0;line-height:1.2;font-family:'Georgia',serif">{data["headline"]}</h1>
    <p style="color:#8a7560;font-size:0.76rem;margin:10px 0 0">{today}</p>
  </div>

  <!-- TERMINSPRISER -->
  <div style="padding:14px 32px;background:#0f0b05;border-bottom:1px solid #3d2510;text-align:center">
    <p style="color:#8a7560;font-size:0.56rem;letter-spacing:0.14em;text-transform:uppercase;margin:0 0 8px">TERMINSPRISER I MORSE</p>
    <div style="line-height:2.4">{futures_html}</div>
  </div>

  <!-- BRIEFING INNEHÅLL -->
  <div style="padding:28px 40px;background:#fff8f0">
    <table style="width:100%;border-collapse:collapse">{rows}</table>
  </div>

  <!-- LÄSA MER -->
  <div style="padding:20px 40px;background:#f5f0e8;text-align:center;border-top:1px solid #f0e8d8">
    <p style="color:#8a7560;font-size:0.8rem;margin:0 0 14px">Vill du läsa hela analysen med djupare bakgrund?</p>
    <a href="{cta_url}" style="display:inline-block;background:linear-gradient(135deg,#c49a6c,{color});color:#1a1208;padding:12px 28px;font-size:0.8rem;font-weight:bold;letter-spacing:0.08em;text-transform:uppercase;text-decoration:none;border-radius:24px">Läs hela briefingen →</a>
  </div>

  <!-- KÄLLOR -->
  <div style="padding:11px 40px;background:#fdf5e8;text-align:center">
    <p style="color:#c49a6c;font-size:0.6rem;margin:0">Källor: {sources}</p>
  </div>

  <!-- FOOTER -->
  <div style="padding:16px 40px;background:#1a1208;text-align:center">
    <p style="color:#8a7560;font-size:0.66rem;margin:0">Espresso Market · Gratis varje vardag kl. 07:00</p>
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
    for i, sub in enumerate(subscribers):
        if i > 0:
            time.sleep(1.2)
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
            print(f"   ✅ {email}")
        else:
            counts["error"] += 1
            print(f"   ❌ {email}: {r.status_code} — {r.text[:80]}")

    total = sum(v for k, v in counts.items() if k != "error")
    print(f"\n✅ Skickade till {total}/{len(subscribers)} prenumeranter")
    print(f"   Nybörjare: {counts['beginner']} | Analytiker: {counts['analyst']} | Pension: {counts['pension']} | Fel: {counts['error']}")

# =============================================================
# MAIN
# =============================================================
if __name__ == "__main__":
    print("📈 Hämtar kurser och terminspriser...")
    futures, spots = get_all_market_data()

    print("🌍 Hämtar makrokalender...")
    macro = get_macro_calendar()

    print("🇸🇪 Hämtar svenska rapporter...")
    swedish_reports = get_swedish_reports()

    print("📰 Hämtar RSS-nyheter...")
    rss = get_rss_headlines()

    print("🤖 Claude söker nattens nyheter och genererar briefing (kort + lång)...")
    briefing = generate_briefing(futures, spots, rss, macro, swedish_reports)

    print("💾 Sparar briefing och arkiv...")
    save_briefing(briefing, futures, spots)

    print("👥 Hämtar prenumeranter...")
    subscribers = get_subscribers()

    print("📧 Skickar email...")
    send_with_resend(briefing, subscribers, futures)

    print("✅ Klart!")
