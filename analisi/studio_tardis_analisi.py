"""
Analisi dello studio storico Tardis (studio/tardis_giornaliero.csv, un primo del mese per riga).

Domanda: il GEX alle 01:00 UTC dice qualcosa sul movimento del prezzo nelle 23 ore dopo
(mov_medio_bp = media dei |rendimenti orari|, in bp), oltre a quello che dice gia' la IV ATM 30g?

1) Correlazioni di Spearman, semplici e parziali (a parita' di IV e tempo: il GEX cresce negli
   anni insieme al mercato, mentre la volatilita' cala), con p da permutazioni a una coda.
   Si fanno 6 test (3 misure x 2 asset): soglia di Bonferroni circa 0,008.
2) Previsione fuori campione: ogni mese, dal venticinquesimo in poi, si stima una regressione di
   log(mov_medio_bp) solo sui mesi precedenti e si prevede il mese; si confronta l'errore di
   "solo IV" con "IV + GEX".

Uso (dalla cartella principale del repo, serve pandas):
    python3 analisi/studio_tardis_analisi.py
"""
import numpy as np
import pandas as pd

TABELLA = "studio/tardis_giornaliero.csv"
PERMUTAZIONI = 20000
MESI_INIZIALI = 24                       # usati solo per stimare il primo modello
MISURE = ["gex_norm", "gex_totale", "gex_entro7g"]
MODELLI = {"media": [], "IV": ["iv_atm_30g"], "IV + GEX norm": ["iv_atm_30g", "gex_norm"],
           "IV + GEX norm + breve": ["iv_atm_30g", "gex_norm", "gex_entro7g_rel"]}


def rango(v):
    return pd.Series(v).rank().values


def corr_perm(x, y, rng):
    """Correlazione e p a una coda (attesa negativa) da permutazioni."""
    r = np.corrcoef(x, y)[0, 1]
    return r, np.mean([np.corrcoef(x, rng.permutation(y))[0, 1] <= r for _ in range(PERMUTAZIONI)])


def correlazioni(g, rng):
    X = np.c_[np.ones(len(g)), rango(g.iv_atm_30g), rango(g.t)]
    residuo = lambda v: v - X @ np.linalg.lstsq(X, v, rcond=None)[0]
    y = rango(g.mov_medio_bp)
    for col in MISURE:
        r, p = corr_perm(rango(g[col]), y, rng)
        rp, pp = corr_perm(residuo(rango(g[col])), residuo(y), rng)
        print(f"  {col:12s} semplice {r:+.2f} (p {p:.3f}) | a parita' di IV e tempo {rp:+.2f} (p {pp:.3f})")
    print(f"  {'iv_atm_30g':12s} semplice {np.corrcoef(rango(g.iv_atm_30g), y)[0, 1]:+.2f}")
    for col in ["gex_totale", "iv_atm_30g"]:
        terzili = pd.qcut(g[col].rank(method="first"), 3, labels=["basso", "medio", "alto"])
        print(f"  movimento medio (bp) per terzile di {col}:",
              g.groupby(terzili, observed=True).mov_medio_bp.mean().round(1).to_dict())
    meta = len(g) // 2
    for s in (g.iloc[:meta], g.iloc[meta:]):
        Xs = np.c_[np.ones(len(s)), rango(s.iv_atm_30g), rango(s.t)]
        res = lambda v: v - Xs @ np.linalg.lstsq(Xs, v, rcond=None)[0]
        ys = res(rango(s.mov_medio_bp))
        print(f"  {s.data.iloc[0]} .. {s.data.iloc[-1]}: parziale gex_norm "
              f"{np.corrcoef(res(rango(s.gex_norm)), ys)[0, 1]:+.2f}, gex_totale "
              f"{np.corrcoef(res(rango(s.gex_totale)), ys)[0, 1]:+.2f}")


def previsione(g, rng):
    y = np.log(g.mov_medio_bp.values)
    err = {k: [] for k in MODELLI}
    for i in range(MESI_INIZIALI, len(g)):
        for k, cols in MODELLI.items():
            X = np.c_[np.ones(i), g.loc[:i - 1, cols].values]
            b = np.linalg.lstsq(X, y[:i], rcond=None)[0]
            err[k].append((y[i] - np.r_[1, g.loc[i, cols].values] @ b) ** 2)
    err = {k: np.array(v) for k, v in err.items()}
    print(f"  previsioni fuori campione: {len(err['IV'])} mesi ({g.data[MESI_INIZIALI]} .. {g.data.iloc[-1]})")
    for k, v in err.items():
        print(f"  {k:22s} errore {v.mean():.4f}   rispetto a solo IV: {100 * (1 - v.mean() / err['IV'].mean()):+.1f}%")
    for k in ["IV + GEX norm", "IV + GEX norm + breve"]:
        d = err["IV"] - err[k]
        p = np.mean([(d * rng.choice([-1, 1], len(d))).mean() >= d.mean() for _ in range(PERMUTAZIONI)])
        print(f"  {k} migliora solo IV? p a una coda {p:.3f}")


def main():
    d = pd.read_csv(TABELLA).sort_values(["asset", "data"])
    d["t"] = pd.to_datetime(d.data).map(pd.Timestamp.toordinal)
    d["gex_entro7g_rel"] = d.gex_entro7g / (d.gamma_lorda_call + d.gamma_lorda_put)
    rng = np.random.default_rng(0)
    for asset, g in d.groupby("asset"):
        g = g.reset_index(drop=True)
        print(f"\n=== {asset}: {len(g)} giorni ({g.data.min()} .. {g.data.max()}), "
              f"GEX negativo in {(g.gex_totale < 0).sum()}")
        correlazioni(g, rng)
        previsione(g, rng)


if __name__ == "__main__":
    main()
