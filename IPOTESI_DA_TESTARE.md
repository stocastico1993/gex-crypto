# Ipotesi da testare (fissate prima di guardare i dati nuovi)

Scritte il 04/11/2026. Le regole qui sotto vanno applicate **così come sono**: cambiarle dopo aver
visto i risultati rende il test inutile.

Script: `python3 analisi/gex_prezzo_fisso.py`, dalla cartella principale del repo; serve pandas.

## Perché il GEX a prezzo fisso

Sul GEX totale salvato in `data/gex_orario.csv` si è visto (3–27/10/2026) che:
- su BTC segue quasi solo il prezzo: correlazione livello/spot 0,93, variazioni a 24h/rendimento 0,97;
- non anticipa la volatilità successiva meglio del DVOL o della volatilità passata.

Il GEX a prezzo fisso si ricalcola ogni ora con **OI e IV di quell'ora**, ma con un **prezzo di
riferimento**: la mediana dello spot delle 168 ore (7 giorni) precedenti. Il forward di ogni
scadenza viene spostato nella stessa proporzione. Così il valore cambia per posizioni, IV e tempo
alla scadenza, non perché il prezzo si è mosso, e usa solo dati già disponibili in quel momento.

Nella prima settimana di dati per strike (28/10 – 04/11/2026) la correlazione tra variazioni a 24h
e rendimento a 24h scende da 0,89 a 0,02 su BTC e da 0,54 a −0,25 su ETH.

## H1: un GEX a prezzo fisso alto anticipa 24 ore più calme

**Idea.** Più gamma positiva hanno i dealer, più comprano sui ribassi e vendono sui rialzi, e il
prezzo si muove meno.

**Cosa si è visto nei giorni di scoperta (28/10 – 04/11/2026, 6 giorni).**
Questi giorni hanno generato l'ipotesi e **non** valgono come prova.

| asset | giorni | Spearman GEX a prezzo fisso / movimento 24h | p (permutazioni, una coda) |
|---|---|---|---|
| BTC | 6 | −0,83 | 0,03 |
| ETH | 6 | −0,89 | 0,02 |

Sono 6 punti in una settimana in cui il mercato si è calmato mentre il GEX saliva: una
coincidenza è del tutto possibile.

### Regole del test

- **Campione di verifica:** solo i giorni **dal 05/11/2026 in poi**.
- **Quando:** a partire da circa **40 giorni di verifica** (indicativamente metà dicembre 2026).
  Prima solo controlli descrittivi, senza conclusioni.
- **Un'osservazione al giorno per asset**, alle 08:01 UTC, subito dopo le scadenze Deribit delle 08:00.
- **Segnale:** GEX a prezzo fisso alle 08:01 (somma di `gex_netto` ricalcolato al prezzo di
  riferimento, strike entro ±30% come nel collettore).
- **Esito:** media del valore assoluto dei rendimenti orari nelle 24 ore successive, in bp.
- **Giorni esclusi:** quelli con meno di 22 ore valide nelle 24 ore prima o dopo.
- **Test principale:** Spearman tra segnale ed esito, attesa negativa, p da 20.000 permutazioni a
  una coda. **BTC** è il test principale (α = 0,05); ETH è una conferma separata.
- **Controllo:** regressione dell'esito su segnale + DVOL + volatilità media delle 24 ore prima.
  Il coefficiente del GEX deve restare negativo: serve a capire se il GEX aggiunge qualcosa a ciò
  che già dicono volatilità implicita e passata.
- **Ipotesi confermata se:** il test principale su BTC è significativo **e** il coefficiente del
  controllo resta negativo.
- **Verifica di robustezza (non decisiva):** stesso test escludendo i giorni di scadenza mensile
  Deribit (ultimo venerdì del mese), quando l'OI cambia di colpo.

### Limiti noti

- **Segno:** assume dealer lunghi sulle call e corti sulle put. Su Deribit molti clienti vendono
  call coperte, quindi la convenzione può essere sbagliata.
- **Banda ±30%:** su ETH la parte fuori banda pesa molto sul GEX netto (il 28/10: 2,0 dentro la
  banda contro 5,7 di totale). Se il test dipende da ETH, conviene allargare la banda del collettore.
- **Scadenze:** le scadenze grandi spostano molto il GEX. Il 30/10/2026 l'OI call di BTC dentro la
  banda è sceso da circa 197.000 a 129.000.
- **Un solo periodo di mercato:** la scoperta copre una settimana.

## Idee secondarie

- **Flusso di posizioni:** variazione a 24h del GEX a prezzo fisso come misura di posizioni aperte e
  chiuse, da confrontare con la direzione del prezzo. Da sviluppare.
