import os, requests, json, re
from datetime import datetime, date
import anthropic

# === API-NYCKLAR ===
FINNHUB_KEY   = os.environ["FINNHUB_API_KEY"]
BEEHIIV_KEY   = os.environ["BEEHIIV_API_KEY"]
BEEHIIV_PUB   = os.environ["BEEHIIV_PUBLICATION_ID"]
ANTHROPIC_KEY = os.environ["ANTHROPIC_API_KEY"]
RESEND_KEY    = os.environ["RESEND_API_KEY"]
NEWS_API_KEY  = os.environ["NEWS_API_KEY"]

# =============================================================
# 1. KURSER (Finnhub)
# =============================================================
def get_quotes():
    symbols = {
        "S&P 500": "SPY",
        "NASDAQ":  "QQQ",
        "OMX30":   "OMXS30.ST",
        "BTC/USD": "BINANCE:BTCUSDT",
        "GULD":    "GLD",
        "OLJA":    "USO",
        "EUR/USD": "OANDA:EUR_USD",
        "USD/SEK": "OANDA:USD_SEK",
    }
    quotes = {}
    for name, sym in symbols.items():
        try:
            r = requests.get(
                f"https://finnhub.io/api/v1/quote?symbol={sym}&token={FINNHUB_KEY}",
                timeout=8
            ).json()
            quotes[name] = {"price": r.get("c", 0), "change": round(r.get("dp", 0), 2)}
        except Exception as e:
            print(f"Kursfel {name}: {e}")
            quotes[name] = {"price": 0, "change": 0}
    return quotes

# =============================================================
# 2. TERMINSPRISER (Yahoo Finance, inga nycklar)
# =============================================================
def get_futures():
    symbols = {
        "S&P 500 Futures": "ES=F",
        "NASDAQ Futures":  "NQ=F",
        "DAX Futures":     "FDAX=F",
        "Olja (WTI)":      "CL=F",
        "Guld":            "GC=F",
    }
    futures = {}
    for name, sym in symbols.items():
        try:
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?interval=1d&range=2d"
            r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=8).json()
            meta   = r["chart"]["result"][0]["meta"]
            price  = round(meta.get("regularMarketPrice", 0), 2)
            prev   = round(meta.get("previousClose", price), 2)
            change = round(((price - prev) / prev * 100) if prev else 0, 2)
            futures[name] = {"price": price, "change": change}
        except Exception as e:
            print(f"Futures-fel {name}: {e}")
            futures[name] = {"price": 0, "change": 0}
    return futures

# =============================================================
# 3. NYHETER (NewsAPI)
# =============================================================
def get_news():
    headlines = []
    queries = [
        {"q": "stock market OR Fed OR inflation OR recession OR tariffs OR OPEC OR Iran OR economy OR earnings", "language": "en"},
        {"q": "börsen OR Riksbanken OR ränta OR inflation OR ekonomi OR aktier", "language": "sv"},
    ]
    for params in queries:
        try:
            r = requests.get(
                "https://newsapi.org/v2/everything",
                params={
                    **params,
                    "sortBy":   "publishedAt",
                    "pageSize": 10,
                    "from":     datetime.now().strftime("%Y-%m-%d"),
                    "apiKey":   NEWS_API_KEY,
                },
                timeout=10
            ).json()
            for a in r.get("articles", [])[:8]:
                title  = a.get("title", "").split(" - ")[0]
                source = a.get("source", {}).get("name", "")
                desc   = (a.get("description") or "")[:120]
                if title and len(title) > 20:
                    headlines.append(f"[{source}] {title}: {desc}")
        except Exception as e:
            print(f"NewsAPI-fel: {e}")
    return headlines[:15]

# =============================================================
# 4. RAPPORTKALENDER (Finnhub + Nasdaq OMX Nordic)
# =============================================================
def get_earnings_calendar():
    today = date.today().strftime("%Y-%m-%d")
    reports = []

    # Internationella rapporter
    try:
        r = requests.get(
            f"https://finnhub.io/api/v1/calendar/earnings?from={today}&to={today}&token={FINNHUB_KEY}",
            timeout=8
        ).json()
        for item in r.get("earningsCalendar", [])[:10]:
            sym = item.get("symbol", "")
            eps = item.get("epsEstimate")
            if sym:
                line = sym
                if eps:
                    line += f" (EPS-est: {eps})"
                reports.append(line)
    except Exception as e:
        print(f"Earnings-fel: {e}")

    # Svenska rapporter (Nasdaq OMX Nordic)
    swedish = []
    try:
        r = requests.get(
            "https://www.nasdaqomxnordic.com/news/companynews",
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=10
        )
        matches = re.findall(
            r'<a[^>]*>([^<]*(?:rapport|bokslut|delår|Q[1-4])[^<]*)</a>',
            r.text, re.IGNORECASE
        )
        swedish = [m.strip() for m in matches[:5] if len(m.strip()) > 5]
    except Exception as e:
        print(f"Nasdaq OMX-fel: {e}")

    return {"international": reports[:8], "swedish": swedish[:5]}

# =============================================================
# 5. MAKROKALENDER (Finnhub)
# =============================================================
def get_macro_calendar():
    today = date.today().strftime("%Y-%m-%d")
    events = []
    try:
        r = requests.get(
            f"https://finnhub.io/api/v1/calendar/economic?from={today}&to={today}&token={FINNHUB_KEY}",
            timeout=8
        ).json()
        for e in r.get("economicCalendar", [])[:8]:
            event  = e.get("event", "")
            impact = e.get("impact", "")
            country = e.get("country", "")
            if event and impact in ["high", "medium"]:
                events.append(f"{country}: {event} (påverkan: {impact})")
    except Exception as ex:
        print(f"Makro-fel: {ex}")
    return events[:6]

# =============================================================
# 6. GENERERA BRIEFING MED CLAUDE
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

def generate_briefing(quotes, futures, news, earnings, macro):
    today = datetime.now().strftime("%A %d %B %Y")

    quote_str   = "\n".join([f"  {k}: {v['price']} ({'+' if v['change']>=0 else ''}{v['change']}%)" for k,v in quotes.items()])
    futures_str = "\n".join([f"  {k}: {v['price']} ({'+' if v['change']>=0 else ''}{v['change']}%)" for k,v in futures.items()])
    news_str    = "\n".join([f"  - {h}" for h in news]) if news else "  Inga nyheter"
    intl        = ", ".join(earnings.get("international", [])) or "Inga"
    swe         = ", ".join(earnings.get("swedish", [])) or "Inga kända svenska rapporter idag"
    macro_str   = "\n".join([f"  - {e}" for e in macro]) if macro else "  Inga stora makrohändelser"

    context = f"""MARKNADSDATA {today}

TERMINSPRISER (pre-market indikationer):
{futures_str}

STÄNGNINGSKURSER IGÅR:
{quote_str}

SENASTE NYHETER (senaste timmarna):
{news_str}

RAPPORTKALENDER IDAG:
  Internationellt: {intl}
  Sverige/Norden: {swe}

MAKROHÄNDELSER IDAG:
{macro_str}"""

    print("=== KONTEXT TILL CLAUDE (preview) ===")
    print(context[:600])
    print("=====================================")

    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)

    system_prompt = f"""Du är Espresso Market – Sveriges skarpaste AI-finansbriefing. Datum: {today}.

Du får RIKTIG marknadsdata och nyhetsrubriker. Skriv en faktabaserad briefing som baseras på dessa.

REGLER:
- Använd konkreta händelser, siffror och länder från datan du fått
- Nämn geopolitiska risker om de finns (Iran, tullar, krig, sanktioner etc.)
- Analytikernivå MÅSTE nämna dagens rapporter och terminsrörelserna
- Nybörjarnivå ska förklara VARFÖR terminserna rör sig som de gör
- Pensionsnivå ska koppla nyheter till långsiktigt sparande

Svara ENDAST med giltig JSON utan kodblock:
{{"headline":"rubrik max 10 ord som speglar dagens viktigaste tema","date":"{today}","beginner":[{{"icon":"📈","label":"KATEGORI","text":"enkel förklaring 2 meningar baserad på riktiga nyheter","explain":"💡 vad betyder detta för en nybörjare 2 meningar"}}],"analyst":[{{"icon":"📊","label":"KATEGORI","text":"teknisk/fundamental analys 2-3 meningar med konkreta siffror och terminspriser"}}],"pension":[{{"icon":"🌱","label":"KATEGORI","text":"hur påverkar detta pensionssparare 2 meningar","tip":"💡 råd för långsiktigt sparande"}}],"sources":["källa1","källa2","källa3"]}}

Inkludera exakt 4 punkter per nivå."""

    msg = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=3000,
        system=system_prompt,
        messages=[{"role": "user", "content": f"Generera briefingen baserad på:\n\n{context}\n\nSvara ENDAST med JSON."}]
    )

    text = next(b.text for b in msg.content if b.type == "text")
    print(f"AI-svar (första 300 tecken): {text[:300]}")
    return extract_json(text)

# =============================================================
# 7. SPARA
# =============================================================
def save_briefing(data, quotes, futures):
    os.makedirs("data", exist_ok=True)
    output = {
        "generated": datetime.now().isoformat(),
        "quotes":    quotes,
        "futures":   futures,
        "briefing":  data
    }
    with open("data/briefing.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print("✅ Briefing sparad till data/briefing.json")

# =============================================================
# 8. HÄMTA PRENUMERANTER
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
# 9. BYGG EMAIL
# =============================================================
def build_email(data, niva, futures):
    today = datetime.now().strftime("%d %B %Y")

    futures_html = ""
    for name, fv in futures.items():
        up    = fv["change"] >= 0
        arrow = "▲" if up else "▼"
        col   = "#5bbf8a" if up else "#e06060"
        futures_html += f'<span style="margin-right:14px;font-family:monospace;font-size:0.8rem"><span style="color:#8a7560">{name}</span> <span style="color:{col}">{arrow} {abs(fv["change"])}%</span></span>'

    if niva == "analyst":
        bullets = data.get("analyst", [])
        color   = "#d4a55a"
        label   = "📊 ANALYTIKER"
        rows    = "".join([f"""<tr><td style="padding:14px 0;border-bottom:1px solid #f0e8d8"><span style="font-size:1.2rem">{b['icon']}</span><strong style="color:#d4a55a;font-size:0.68rem;letter-spacing:0.12em;text-transform:uppercase;display:block;margin:5px 0">{b['label']}</strong><span style="color:#3d2510;font-size:0.9rem;line-height:1.65">{b['text']}</span></td></tr>""" for b in bullets])
    elif niva == "pension":
        bullets = data.get("pension", [])
        color   = "#5bbf8a"
        label   = "🌱 PENSIONSSPARARE"
        rows    = "".join([f"""<tr><td style="padding:14px 0;border-bottom:1px solid #f0e8d8"><span style="font-size:1.2rem">{b['icon']}</span><strong style="color:#5bbf8a;font-size:0.68rem;letter-spacing:0.12em;text-transform:uppercase;display:block;margin:5px 0">{b['label']}</strong><span style="color:#3d2510;font-size:0.9rem;line-height:1.65">{b['text']}</span><span style="display:block;margin-top:7px;padding:9px 13px;background:#f0fdf6;border-left:3px solid #5bbf8a;color:#1a3a2a;font-size:0.82rem;line-height:1.55">{b.get('tip','')}</span></td></tr>""" for b in bullets])
    else:
        bullets = data.get("beginner", [])
        color   = "#7ab3d4"
        label   = "☕ NYBÖRJARE"
        rows    = "".join([f"""<tr><td style="padding:14px 0;border-bottom:1px solid #f0e8d8"><span style="font-size:1.2rem">{b['icon']}</span><strong style="color:#7ab3d4;font-size:0.68rem;letter-spacing:0.12em;text-transform:uppercase;display:block;margin:5px 0">{b['label']}</strong><span style="color:#3d2510;font-size:0.9rem;line-height:1.65">{b['text']}</span><span style="display:block;margin-top:7px;padding:9px 13px;background:#f0f7fd;border-left:3px solid #7ab3d4;color:#1a3a4a;font-size:0.82rem;line-height:1.55">{b.get('explain','')}</span></td></tr>""" for b in bullets])

    sources = " · ".join(data.get("sources", []))

    return f"""<!DOCTYPE html><html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"></head>
<body style="margin:0;padding:0;background:#f5ead6;font-family:'Georgia',serif">
<div style="max-width:600px;margin:0 auto;background:#1a1208">
  <div style="background:linear-gradient(135deg,#1a1208,#3d2510);padding:32px 40px;text-align:center;border-bottom:2px solid {color}">
    <p style="color:{color};font-size:0.65rem;letter-spacing:0.2em;text-transform:uppercase;margin:0 0 8px">☕ ESPRESSO MARKET · {label}</p>
    <h1 style="color:#f5ead6;font-size:1.5rem;margin:0;line-height:1.2">{data['headline']}</h1>
    <p style="color:#8a7560;font-size:0.78rem;margin:12px 0 0">{today}</p>
  </div>
  <div style="padding:14px 40px;background:#0f0b05;text-align:center;border-bottom:1px solid #3d2510">
    <p style="color:#8a7560;font-size:0.58rem;letter-spacing:0.12em;text-transform:uppercase;margin:0 0 7px">TERMINSPRISER I MORSE</p>
    <div>{futures_html}</div>
  </div>
  <div style="padding:32px 40px;background:#fff8f0">
    <table style="width:100%;border-collapse:collapse">{rows}</table>
  </div>
  <div style="padding:12px 40px;background:#fdf5e8;border-top:1px solid #f0e8d8;text-align:center">
    <p style="color:#c49a6c;font-size:0.62rem;margin:0">Källor: {sources}</p>
  </div>
  <div style="padding:24px 40px;background:#1a1208;text-align:center">
    <a href="https://espressomarket.se" style="display:inline-block;background:linear-gradient(135deg,#c49a6c,{color});color:#1a1208;padding:12px 28px;font-size:0.8rem;font-weight:bold;letter-spacing:0.08em;text-transform:uppercase;text-decoration:none;border-radius:24px">Läs hela briefingen →</a>
    <p style="color:#8a7560;font-size:0.68rem;margin:14px 0 0">Espresso Market · Gratis varje vardag kl. 07:00</p>
  </div>
</div>
</body></html>"""

# =============================================================
# 10. SKICKA EMAIL
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
    print("📈 Hämtar kurser...")
    quotes  = get_quotes()

    print("📊 Hämtar terminspriser...")
    futures = get_futures()

    print("📰 Hämtar nyheter...")
    news = get_news()
    print(f"   {len(news)} rubriker")

    print("📅 Hämtar rapportkalender...")
    earnings = get_earnings_calendar()
    print(f"   Internationellt: {len(earnings['international'])} | Sverige: {len(earnings['swedish'])}")

    print("🌍 Hämtar makrokalender...")
    macro = get_macro_calendar()
    print(f"   {len(macro)} händelser")

    print("🤖 Genererar briefing med Claude...")
    briefing = generate_briefing(quotes, futures, news, earnings, macro)

    save_briefing(briefing, quotes, futures)

    print("👥 Hämtar prenumeranter...")
    subscribers = get_subscribers()

    print("📧 Skickar email...")
    send_with_resend(briefing, subscribers, futures)

    print("✅ Klart!")
