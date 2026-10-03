"""
Raccolta oraria del GEX di BTC ed ETH dall'API pubblica Deribit (gratuita, senza chiave).
Aggiunge una riga per asset a data/gex_orario.csv ogni volta che viene lanciato.
Solo libreria standard di Python: nessuna installazione necessaria.

GEX in milioni di $ per movimento dell'1%, convenzione call +, put -.
Separato per fascia di scadenza: entro 1 giorno (daily / "0DTE"), 1-7, 7-30, oltre 30 giorni.
Gamma calcolata con Black-Scholes sul forward (verificata ~1.00 contro la gamma Deribit).
"""
import csv, json, math, os, time, urllib.parse, urllib.request
from datetime import datetime, timezone

API = "https://www.deribit.com/api/v2/public/"
FILE = "data/gex_orario.csv"
MESI = {m: i + 1 for i, m in enumerate(
    ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"])}
FASCE = [("gex_entro1g", 1), ("gex_1_7g", 7), ("gex_7_30g", 30), ("gex_oltre30g", float("inf"))]
COLONNE = ["ora_utc", "asset", "spot", "gex_totale"] + [f for f, _ in FASCE] + \
          ["gamma_lorda_call", "gamma_lorda_put", "iv_atm_30g", "dvol", "n_opzioni"]


def api(metodo, **parametri):
    url = API + metodo + "?" + urllib.parse.urlencode(parametri)
    for tentativo in range(3):
        try:
            with urllib.request.urlopen(url, timeout=30) as r:
                return json.load(r)["result"]
        except Exception as e:
            errore = e
            time.sleep(5)
    raise errore


def scadenza(testo):                     # "27DEC26" oppure "3OCT26", scadenza alle 08:00 UTC
    return datetime(2000 + int(testo[-2:]), MESI[testo[-5:-2]], int(testo[:-5]), 8, tzinfo=timezone.utc)


def gamma_bs(S, K, T, sig):
    d1 = (math.log(S / K) + 0.5 * sig * sig * T) / (sig * math.sqrt(T))
    return math.exp(-0.5 * d1 * d1) / math.sqrt(2 * math.pi) / (S * sig * math.sqrt(T))


def riga_asset(asset, adesso):
    fasce = {f: 0.0 for f, _ in FASCE}
    lorda_call = lorda_put = 0.0
    n = 0
    candidati_atm = []
    for o in api("get_book_summary_by_currency", currency=asset, kind="option"):
        oi, iv, S = o.get("open_interest") or 0, o.get("mark_iv") or 0, o.get("underlying_price")
        if oi <= 0 or iv <= 0 or not S:
            continue
        _, exp, K, cp = o["instrument_name"].split("-")
        K = float(K)
        giorni = (scadenza(exp) - adesso).total_seconds() / 86400
        if giorni <= 0:
            continue
        g = gamma_bs(S, K, giorni / 365, iv / 100) * oi * S * S * 0.01 / 1e6
        segno = 1 if cp == "C" else -1
        for nome, limite in FASCE:
            if giorni <= limite:
                fasce[nome] += segno * g
                break
        if segno > 0:
            lorda_call += g
        else:
            lorda_put += g
        n += 1
        candidati_atm.append((round(abs(giorni - 30), 3), abs(K / S - 1), iv))

    spot = api("get_index_price", index_name=asset.lower() + "_usd")["index_price"]
    try:
        ms = int(adesso.timestamp() * 1000)
        dvol = api("get_volatility_index_data", currency=asset, resolution="3600",
                   start_timestamp=ms - 3 * 3600 * 1000, end_timestamp=ms)["data"][-1][4]
    except Exception:
        dvol = ""
    iv_atm = min(candidati_atm)[2] if candidati_atm else ""

    riga = {"ora_utc": adesso.strftime("%Y-%m-%d %H:%M"), "asset": asset, "spot": round(spot, 2),
            "gex_totale": round(sum(fasce.values()), 4),
            "gamma_lorda_call": round(lorda_call, 4), "gamma_lorda_put": round(lorda_put, 4),
            "iv_atm_30g": iv_atm, "dvol": dvol, "n_opzioni": n}
    riga.update({k: round(v, 4) for k, v in fasce.items()})
    return riga


if __name__ == "__main__":
    adesso = datetime.now(timezone.utc)
    righe = [riga_asset(a, adesso) for a in ["BTC", "ETH"]]
    os.makedirs("data", exist_ok=True)
    nuovo = not os.path.exists(FILE)
    with open(FILE, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLONNE)
        if nuovo:
            w.writeheader()
        w.writerows(righe)
    for r in righe:
        print(r)
