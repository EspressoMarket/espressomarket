import os, requests, json, re
from datetime import datetime
import anthropic

FINNHUB_KEY = os.environ["FINNHUB_API_KEY"]
BEEHIIV_KEY = os.environ["BEEHIIV_API_KEY"]
BEEHIIV_PUB = os.environ["BEEHIIV_PUBLICATION_ID"]
ANTHROPIC_KEY = os.environ["ANTHROPIC_API_KEY"]
RESEND_KEY = os.environ["RESEND_API_KEY"]

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
    text = re.sub(r'```json\s*', '', text)
    text = re.sub(r'```\s*', '', text)
    text = text.strip()
    start = text.find('{')
    end = text.rfind('}')
    if start == -1 or end == -1:
        raise ValueError("Ingen JSON hittades")
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

def get_subscribers():
    subscribers = []
    page = 1
    while True:
        r = requests.get(
            f"https://api.beehiiv.com/v2/publications/{BEEHIIV_PUB}/subscriptions",
            headers={"Authorization": f"Bearer {BEEHIIV_KEY}"},
            params={"status": "active", "limit": 100, "page": page}
        )
        data = r.json()
        subs = data.get("data", [])
        if not subs:
            break
        subscribers.extend([s["email"] for s in subs])
        if len(subs) < 100:
            break
        page += 1
    print(f"Hittade {len(subscribers)} prenumeranter")
    return subscribers

def send_with_resend(data, subscribers):
    today = datetime.now().strftime("%d %B %Y")
    
    beginner_bullets = "".join([f"""
        <tr>
          <td style="padding:12px 0;border-bottom:1px solid #f0e8d8">
            <span style="font-size:1.2rem">{b['icon']}</span>
            <strong style="color:#8a6030;font-size:0.7rem;letter-spacing:0.1em;text-transform:uppercase;display:block;margin:4px 0">{b['label']}</strong>
            <span style="color:#3d2510;font-size:0.9rem;line-height:1.6">{b['text']}</span>
            <span style="display:block;margin-top:6px;padding:8px 12px;background:#fdf5e8;border-left:3px solid #d4a55a;color:#6b3d1e;font-size:0.82rem;line-height:1.5">{b.get('explain','')}</span>
          </td>
        </tr>""" for b in data.get("beginner",[])])

    html = f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"></head>
<body style="margin:0;padding:0;background:#f5ead6;font-family:'Georgia',serif">
  <div style="max-width:600px;margin:0 auto;background:#1a1208">
    <div style="background:linear-gradient(135deg,#1a1208,#3d2510);padding:32px 40px;text-align:center;border-bottom:2px solid #d4a55a">
      <p style="color:#d4a55a;font-size:0.7rem;letter-spacing:0.2em;text-transform:uppercase;margin:0 0 8px">☕ ESPRESSO MARKET</p>
      <h1 style="color:#f5ead6;font-size:1.6rem;margin:0;line-height:1.2">{data['headline']}</h1>
      <p style="color:#8a7560;font-size:0.8rem;margin:12px 0 0">{today}</p>
    </div>
    <div style="padding:32px 40px;background:#fff8f0">
      <p style="color:#d4a55a;font-size:0.65rem;letter-spacing:0.15em;text-transform:uppercase;margin:0 0 16px">📖 DAGENS BRIEFING – NYBÖRJARE</p>
      <table style="width:100%;border-collapse:collapse">
        {beginner_bullets}
      </table>
    </div>
    <div style="padding:24px 40px;background:#1a1208;text-align:center;border-top:1px solid #3d2510">
      <a href="https://espressomarket.se" style="display:inline-block;background:linear-gradient(135deg,#c49a6c,#d4a55a);color:#1a1208;padding:12px 28px;font-size:0.8rem;font-weight:bold;letter-spacing:0.08em;text-transform:uppercase;text-decoration:none;border-radius:24px">Läs hela briefingen →</a>
      <p style="color:#8a7560;font-size:0.72rem;margin:16px 0 0">Espresso Market · Gratis varje vardag kl. 07:00</p>
    </div>
  </div>
</body></html>"""

    if not subscribers:
        print("Inga prenumeranter att skicka till")
        return

    success = 0
    for email in subscribers:
        r = requests.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {RESEND_KEY}", "Content-Type": "application/json"},
            json={
                "from": "Espresso Market <briefing@espressomarket.se>",
                "to": email,
                "subject": f"☕ {data['headline']}",
                "html": html
            }
        )
        if r.status_code == 200:
            success += 1
        else:
            print(f"Fel för {email}: {r.status_code}")

    print(f"✅ Skickade till {success}/{len(subscribers)} prenumeranter via Resend")

if __name__ == "__main__":
    print("Hämtar kurser...")
    quotes = get_quotes()
    print("Genererar briefing...")
    briefing = generate_briefing(quotes)
    save_briefing(briefing, quotes)
    subscribers = get_subscribers()
    send_with_resend(briefing, subscribers)
    print("✅ Klart!")
