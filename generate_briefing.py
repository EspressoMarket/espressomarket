import os, requests, json, re
from datetime import datetime
import anthropic

FINNHUB_KEY = os.environ["FINNHUB_API_KEY"]
BEEHIIV_KEY = os.environ["BEEHIIV_API_KEY"]
BEEHIIV_PUB = os.environ["BEEHIIV_PUBLICATION_ID"]
ANTHROPIC_KEY = os.environ["ANTHROPIC_API_KEY"]

def get_quotes():
    symbols = {"S&P 500":"^GSPC","NASDAQ":"^IXIC","OMX30":"^OMX","BTC/USD":"BINANCE:BTCUSDT","OIL":"USOIL","GULD":"OANDA:XAUUSD"}
    quotes = {}
    for name, sym in symbols.items():
        try:
            r = requests.get(f"https://finnhub.io/api/v1/quote?symbol={sym}&token={FINNHUB_KEY}").json()
            quotes[name] = {"price": r["c"], "change": round(r["dp"], 2)}
        except:
            quotes[name] = {"price": 0, "change": 0}
    return quotes

def extract_json(text):
    # Ta bort markdown-kodblock om de finns
    text = re.sub(r'```json\s*', '', text)
    text = re.sub(r'```\s*', '', text)
    text = text.strip()
    # Hitta första { och sista }
    start = text.find('{')
    end = text.rfind('}')
    if start == -1 or end == -1:
        raise ValueError("Ingen JSON hittades i svaret")
    return json.loads(text[start:end+1])

def generate_briefing(quotes):
    today = datetime.now().strftime("%A %d %B %Y")
    quote_str = "\n".join([f"{k}: {v['price']} ({v['change']}%)" for k,v in quotes.items()])
    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
    msg = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1500,
        tools=[{"type": "web_search_20250305", "name": "web_search"}],
        system=f"""Du är Espresso Market – Sveriges skarpaste finansbriefing. Datum: {today}.
Svara ENDAST med giltig JSON, inga förklaringar, inga kodblock, ingen extra text.
Format:
{{"headline":"rubrik max 10 ord","date":"{today}","beginner":[{{"icon":"📈","label":"KATEGORI","text":"enkel förklaring max 2 meningar","explain":"💡 pedagogisk förklaring max 2 meningar"}}],"analyst":[{{"icon":"📊","label":"KATEGORI","text":"teknisk analys max 2 meningar"}}],"sources":["källa1","källa2"]}}
Inkludera 4 punkter i beginner och 4 punkter i analyst.""",
        messages=[{"role":"user","content":f"Dagens kurser:\n{quote_str}\n\nSök dagens viktigaste finansnyheter och generera briefing på svenska. Svara ENDAST med JSON."}]
    )
    text = next(b.text for b in msg.content if b.type == "text")
    print(f"AI svar (första 200 tecken): {text[:200]}")
    return extract_json(text)

def save_briefing(data, quotes):
    os.makedirs("data", exist_ok=True)
    output = {"generated": datetime.now().isoformat(), "quotes": quotes, "briefing": data}
    with open("data/briefing.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print("✅ Briefing sparad till data/briefing.json")

def send_to_beehiiv(data, quotes):
    today = datetime.now().strftime("%d %B %Y")
    bullets = "".join([f"<li><strong>{b['label']}</strong>: {b['text']}</li>" for b in data.get("beginner",[])])
    html = f"""<h2>{data['headline']}</h2>
<p><em>Espresso Market – {today}</em></p>
<ul>{bullets}</ul>
<p>Läs hela briefingen på <a href="https://espressomarket.se">espressomarket.se</a></p>"""
    r = requests.post(
        f"https://api.beehiiv.com/v2/publications/{BEEHIIV_PUB}/posts",
        headers={"Authorization": f"Bearer {BEEHIIV_KEY}", "Content-Type": "application/json"},
        json={"subject": data["headline"], "content": {"free": {"web": html, "email": html}}, "status": "draft"}
    )
    print(f"Beehiiv: {r.status_code}")

if __name__ == "__main__":
    print("Hämtar kurser...")
    quotes = get_quotes()
    print("Genererar briefing...")
    briefing = generate_briefing(quotes)
    save_briefing(briefing, quotes)
    send_to_beehiiv(briefing, quotes)
    print("✅ Klart!")
