"""
Studio storico del GEX di BTC ed ETH con i dati gratuiti di Tardis.dev (primo giorno di ogni mese).

Per ogni primo del mese e per ogni asset:
  * dal file options_chain prende la situazione di ogni opzione alle 01:00 UTC (OI, mark IV,
    forward) e calcola il GEX con la stessa formula del collettore (Black-Scholes sul forward,
    milioni di $ per 1%, call +, put -). Il file e' ordinato per tempo: si smette di leggerlo
    poco dopo le 01:00, quindi si scarica solo una piccola parte
  * dal file trades del perpetuo prende l'ultimo prezzo di ogni ora, dalle 01:00 alle 24:00,
    e calcola quanto si e' mosso il prezzo nelle 23 ore successive

Pensato per GitHub Actions (questo ambiente non raggiunge datasets.tardis.dev). Solo libreria standard.
Uso:
    python3 analisi/studio_tardis.py --anno 2024 --mesi 06 --uscita studio_2024.csv
    python3 analisi/studio_tardis.py --anno 2024 --uscita studio_2024.csv      # tutti i mesi
"""
import argparse, csv, gzip, io, math, statistics, sys, time, urllib.error, urllib.request
from datetime import date, datetime, timedelta, timezone

URL = "https://datasets.tardis.dev/v1/deribit/{tipo}/{d:%Y/%m/%d}/{simbolo}.csv.gz"
PRIMO_GIORNO = date(2020, 3, 1)          # options_chain Deribit su Tardis parte da qui
ORA_FOTO = 1                             # fotografia della catena alle 01:00 UTC
MARGINE_LETTURA = timedelta(minutes=10)  # si legge fino a 01:10 (local_timestamp) per sicurezza
BANDA = 0.30
COLONNE = ["data", "asset", "spot_0100", "gex_totale", "gex_banda30", "gex_entro7g",
           "gamma_lorda_call", "gamma_lorda_put", "gex_norm", "iv_atm_30g", "n_opzioni",
           "ore_prezzo", "mov_medio_bp", "range_pct", "rend_pct"]


def apri(tipo, giorno, simbolo):
    url = URL.format(tipo=tipo, d=giorno, simbolo=simbolo)
    req = urllib.request.Request(url, headers={"User-Agent": "gex-crypto-studio"})
    for tentativo in range(3):
        try:
            risposta = urllib.request.urlopen(req, timeout=120)
            return risposta, io.TextIOWrapper(gzip.GzipFile(fileobj=risposta), encoding="utf-8")
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None, None
            errore = e
        except Exception as e:
            errore = e
        time.sleep(10 * (tentativo + 1))
    raise errore


def colonne(intestazione, richieste, nome_file):
    nomi = intestazione.strip().split(",")
    mancanti = [c for c in richieste if c not in nomi]
    if mancanti:
        sys.exit(f"{nome_file}: colonne mancanti {mancanti}. Colonne trovate: {nomi}")
    return {c: nomi.index(c) for c in richieste}


def us(ts):                              # microsecondi -> datetime UTC
    return datetime.fromtimestamp(int(ts) / 1e6, tz=timezone.utc)


def gamma_bs(S, K, T, sig):
    d1 = (math.log(S / K) + 0.5 * sig * sig * T) / (sig * math.sqrt(T))
    return math.exp(-0.5 * d1 * d1) / math.sqrt(2 * math.pi) / (S * sig * math.sqrt(T))


def foto_catena(giorno):
    """Ultimo stato di ogni opzione con timestamp <= 01:00, per BTC ed ETH."""
    foto_ora = datetime(giorno.year, giorno.month, giorno.day, ORA_FOTO, tzinfo=timezone.utc)
    stop = int((foto_ora + MARGINE_LETTURA).timestamp() * 1e6)
    limite = int(foto_ora.timestamp() * 1e6)
    risposta, f = apri("options_chain", giorno, "OPTIONS")
    if f is None:
        return None, foto_ora
    c = colonne(f.readline(), ["symbol", "timestamp", "local_timestamp", "type", "strike_price",
                               "expiration", "open_interest", "mark_iv", "underlying_price"],
                "options_chain")
    stato = {}
    for riga in f:
        v = riga.rstrip("\n").split(",")
        if int(v[c["local_timestamp"]]) > stop:
            break
        if int(v[c["timestamp"]]) <= limite:
            stato[v[c["symbol"]]] = v
    risposta.close()
    return (c, stato), foto_ora


def gex_asset(c, stato, asset, foto_ora):
    righe = [v for s, v in stato.items() if s.startswith(asset + "-")]
    iv_grezze = [float(v[c["mark_iv"]]) for v in righe if v[c["mark_iv"]] not in ("", "0")]
    scala = 100.0 if iv_grezze and statistics.median(iv_grezze) > 5 else 1.0   # percento o frazione
    tot = banda = entro7 = lorda_c = lorda_p = 0.0
    n, atm = 0, []
    for v in righe:
        try:
            oi, iv = float(v[c["open_interest"]] or 0), float(v[c["mark_iv"]] or 0) / scala
            S, K = float(v[c["underlying_price"]] or 0), float(v[c["strike_price"]])
        except ValueError:
            continue
        anni = (us(v[c["expiration"]]) - foto_ora).total_seconds() / 86400 / 365
        if oi <= 0 or iv <= 0 or S <= 0 or anni <= 0:
            continue
        g = gamma_bs(S, K, anni, iv) * oi * S * S * 0.01 / 1e6
        segno = 1 if v[c["type"]].lower().startswith("c") else -1
        tot += segno * g
        if abs(K / S - 1) <= BANDA:
            banda += segno * g
        if anni * 365 <= 7:
            entro7 += segno * g
        if segno > 0:
            lorda_c += g
        else:
            lorda_p += g
        n += 1
        atm.append((round(abs(anni * 365 - 30), 3), abs(K / S - 1), iv * 100))
    if n == 0:
        return None
    return {"gex_totale": round(tot, 4), "gex_banda30": round(banda, 4), "gex_entro7g": round(entro7, 4),
            "gamma_lorda_call": round(lorda_c, 4), "gamma_lorda_put": round(lorda_p, 4),
            "gex_norm": round(tot / (lorda_c + lorda_p), 4), "iv_atm_30g": round(min(atm)[2], 2),
            "n_opzioni": n}


def prezzi_orari(giorno, asset):
    """Ultimo prezzo del perpetuo alla fine di ogni ora; chiave = ora di fine (1..24)."""
    risposta, f = apri("trades", giorno, f"{asset}-PERPETUAL")
    if f is None:
        return {}
    c = colonne(f.readline(), ["timestamp", "price"], "trades")
    inizio = datetime(giorno.year, giorno.month, giorno.day, tzinfo=timezone.utc).timestamp() * 1e6
    ultimo = {}
    for riga in f:
        v = riga.rstrip("\n").split(",")
        ora = int((int(v[c["timestamp"]]) - inizio) // 3_600_000_000)   # 0..23
        if 0 <= ora < 24:
            ultimo[ora + 1] = float(v[c["price"]])
    risposta.close()
    return ultimo


def movimento(prezzi):
    ore = [h for h in range(ORA_FOTO, 25) if h in prezzi]
    if len(ore) < 20 or ORA_FOTO not in prezzi:
        return None
    serie = [prezzi[h] for h in ore]
    rend = [abs(math.log(b / a)) * 1e4 for a, b in zip(serie, serie[1:])]
    p0 = prezzi[ORA_FOTO]
    return {"spot_0100": p0, "ore_prezzo": len(ore), "mov_medio_bp": round(sum(rend) / len(rend), 3),
            "range_pct": round(100 * (max(serie) - min(serie)) / p0, 4),
            "rend_pct": round(100 * (serie[-1] / p0 - 1), 4)}


def main():
    a = argparse.ArgumentParser()
    a.add_argument("--anno", type=int, required=True)
    a.add_argument("--mesi", default="", help="es. '06' o '01 07'; vuoto = tutti")
    a.add_argument("--uscita", required=True)
    arg = a.parse_args()
    mesi = [int(m) for m in arg.mesi.split()] or list(range(1, 13))
    oggi = datetime.now(timezone.utc).date()
    righe = []
    for m in mesi:
        giorno = date(arg.anno, m, 1)
        if giorno < PRIMO_GIORNO or giorno >= oggi:
            continue
        t0 = time.time()
        foto, foto_ora = foto_catena(giorno)
        if foto is None:
            print(f"{giorno}: options_chain non disponibile")
            continue
        for asset in ["BTC", "ETH"]:
            g = gex_asset(*foto, asset, foto_ora)
            p = movimento(prezzi_orari(giorno, asset))
            if g is None or p is None:
                print(f"{giorno} {asset}: dati insufficienti (gex={g is not None}, prezzi={p is not None})")
                continue
            righe.append({"data": str(giorno), "asset": asset, **p, **g})
            print(f"{giorno} {asset}: {righe[-1]}")
        print(f"{giorno}: {time.time() - t0:.0f} s")
    with open(arg.uscita, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLONNE)
        w.writeheader()
        w.writerows(righe)
    print(f"{len(righe)} righe in {arg.uscita}")


if __name__ == "__main__":
    main()
