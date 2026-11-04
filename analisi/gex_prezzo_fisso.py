"""
GEX a prezzo fisso per BTC ed ETH, dai file per strike in data/strike/.

Il GEX "vero" cambia anche solo perche' si muove il prezzo. Qui lo si ricalcola ogni ora con
OI e IV di quell'ora ma con un prezzo di riferimento: la mediana dello spot delle 168 ore
(7 giorni) precedenti, cosi' ogni valore usa solo dati gia' disponibili in quel momento.
Il forward di ogni scadenza viene spostato in proporzione (stesso rapporto forward/indice).

Poi applica il test fissato in IPOTESI_DA_TESTARE.md: GEX a prezzo fisso alle 08:01 UTC
contro il movimento medio orario delle 24 ore successive, separando i giorni di scoperta
da quelli di verifica.

Uso (dalla cartella principale del repo, serve pandas):
    python3 analisi/gex_prezzo_fisso.py
Scrive anche analisi/gex_prezzo_fisso_orario.csv con la serie oraria.
"""
import glob
import numpy as np
import pandas as pd

INIZIO_VERIFICA = pd.Timestamp("2026-11-05", tz="UTC")   # vedi IPOTESI_DA_TESTARE.md
ORE_RIFERIMENTO = 168
PERMUTAZIONI = 20000


def gamma_bs(S, K, T, iv):
    s = iv / 100
    d1 = (np.log(S / K) + 0.5 * s * s * T) / (s * np.sqrt(T))
    return np.exp(-0.5 * d1 * d1) / np.sqrt(2 * np.pi) / (S * s * np.sqrt(T))


def gex(S, k):
    """GEX netto (milioni di $ per 1%) di ogni riga di k con forward S; call +, put -."""
    iv_c = k.iv_call.fillna(k.iv_put)
    iv_p = k.iv_put.fillna(k.iv_call)
    gc = np.where(k.oi_call > 0, gamma_bs(S, k.strike, k.anni, iv_c), 0) * k.oi_call
    gp = np.where(k.oi_put > 0, gamma_bs(S, k.strike, k.anni, iv_p), 0) * k.oi_put
    return (gc - gp) * S * S * 0.01 / 1e6


def carica():
    k = pd.concat(pd.read_csv(f) for f in sorted(glob.glob("data/strike/strike_*.csv")))
    k["t"] = pd.to_datetime(k.ora_utc, utc=True)
    scad = pd.to_datetime(k.scadenza, utc=True) + pd.Timedelta(hours=8)   # Deribit: 08:00 UTC
    k["anni"] = (scad - k.t).dt.total_seconds() / 86400 / 365
    k = k[k.anni > 0]
    r = pd.read_csv("data/gex_orario.csv")
    r["t"] = pd.to_datetime(r.ora_utc, utc=True)
    return k.merge(r[["t", "asset", "spot", "dvol"]], on=["t", "asset"]), r


def serie_oraria(k, r):
    out = []
    for asset, ka in k.groupby("asset"):
        ra = r[r.asset == asset].set_index("t").sort_index()
        ref = ra.spot.rolling(f"{ORE_RIFERIMENTO}h", closed="left").median()
        ka = ka.assign(ref=ka.t.map(ref))
        ka = ka.assign(gex_vero=gex(ka.sottostante, ka),
                       gex_fisso=gex(ka.sottostante * ka.ref / ka.spot, ka))
        h = ka.groupby("t").agg(spot=("spot", "first"), ref=("ref", "first"), dvol=("dvol", "first"),
                                gex_vero=("gex_vero", "sum"), gex_fisso=("gex_fisso", "sum"))
        h.insert(0, "asset", asset)
        out.append(h)
    return pd.concat(out)


def osservazioni_giornaliere(h):
    """Una riga al giorno alle 08:xx UTC, con il movimento medio orario delle 24 ore dopo."""
    righe = []
    for asset, ha in h.groupby("asset"):
        ha = ha.resample("1h").last()
        rend = np.log(ha.spot).diff().abs() * 1e4
        for t in ha.index[ha.index.hour == 8]:
            dopo, prima = rend[t + pd.Timedelta(hours=1): t + pd.Timedelta(hours=24)], rend[t - pd.Timedelta(hours=23): t]
            riga = ha.loc[t]
            # servono il prezzo di riferimento (7 giorni pieni di storia) e quasi tutte le ore
            if pd.isna(riga.gex_fisso) or pd.isna(riga.ref) or dopo.count() < 22 or prima.count() < 22:
                continue
            righe.append(dict(giorno=t, asset=asset, gex_fisso=riga.gex_fisso, gex_vero=riga.gex_vero,
                              dvol=riga.dvol, vol_passata=prima.mean(), mov_24h=dopo.mean()))
    return pd.DataFrame(righe)


def spearman_perm(x, y, rng):
    rx, ry = pd.Series(x).rank().values, pd.Series(y).rank().values
    rho = np.corrcoef(rx, ry)[0, 1]
    perm = np.array([np.corrcoef(rx, rng.permutation(ry))[0, 1] for _ in range(PERMUTAZIONI)])
    return rho, np.mean(perm <= rho)            # p a una coda: correlazione attesa negativa


def coef_gex(d):
    X = np.c_[np.ones(len(d)), d.gex_fisso, d.dvol, d.vol_passata]
    return np.linalg.lstsq(X, d.mov_24h, rcond=None)[0][1]


def main():
    k, r = carica()
    h = serie_oraria(k, r)
    h.to_csv("analisi/gex_prezzo_fisso_orario.csv", float_format="%.4f")
    rng = np.random.default_rng(0)
    for asset, ha in h.groupby("asset"):
        dv, df = ha.gex_vero.diff(24), ha.gex_fisso.diff(24)
        ret = np.log(ha.spot).diff(24)
        print(f"{asset}: {len(ha)} ore. Correlazione delle variazioni a 24h con il rendimento: "
              f"GEX vero {dv.corr(ret):.2f}, a prezzo fisso {df.corr(ret):.2f}")
    d = osservazioni_giornaliere(h)
    if d.empty:
        print("\nNessun giorno con 7 giorni di storia per il prezzo di riferimento: troppo presto per il test.")
        return
    d["campione"] = np.where(d.giorno >= INIZIO_VERIFICA, "verifica", "scoperta")
    for (asset, camp), g in d.groupby(["asset", "campione"]):
        if len(g) < 5:
            print(f"\n{asset} / {camp}: {len(g)} giorni, troppo pochi per il test.")
            continue
        rho, p = spearman_perm(g.gex_fisso, g.mov_24h, rng)
        print(f"\n{asset} / {camp}: {len(g)} giorni")
        print(f"  Spearman GEX a prezzo fisso / movimento 24h: {rho:.2f}  (p a una coda {p:.3f})")
        if len(g) >= 10:
            print(f"  coefficiente del GEX con DVOL e volatilita' passata come controlli: {coef_gex(g):.4f}")
    n = (d.campione == "verifica").groupby(d.asset).sum()
    print(f"\nGiorni di verifica finora: {n.to_dict()} (il test si valuta da 40 in su)")


if __name__ == "__main__":
    main()
