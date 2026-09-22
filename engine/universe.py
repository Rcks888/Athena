"""Athena universes, de-duplicated and corrected.

V1-V5 inlined these lists in each runner. `run_backtest_v5.py:39`'s UNIVERSE_B
claimed 100 mid-caps but contained "FIVERR", which is not a ticker (FVRR, the
real one, was already listed), and duplicated RIVN and ROKU — 100 entries, 99
unique, and only 82 produced trades. The lists live here now so the corrections
cannot drift back, and so the runner can report attempted versus contributing.

Survivorship is NOT controlled for. Both lists were written in 2026 with
hindsight about which companies still exist and are liquid. That requires paid
point-in-time index membership to fix and is recorded as a known, unquantified
limitation of V6 rather than waved away.
"""

# Original universe, unchanged from V1-V5 so V6 is comparable on population.
UNIVERSE_A = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA", "BRK-B",
    "JPM", "V", "JNJ", "UNH", "WMT", "MA", "PG", "HD", "ORCL", "ABBV",
    "XOM", "CVX", "AMD", "NFLX", "CRM", "SNOW", "PLTR", "CRWD", "DDOG",
    "NET", "PANW", "NOW", "ADBE", "INTU", "ANET", "SNPS", "CDNS", "FTNT",
    "COIN", "PYPL", "GS", "MS", "SCHW", "UBER", "ABNB", "ROKU", "SNAP",
    "PINS", "DIS", "SBUX", "NKE", "LULU", "CMG", "BKNG", "LLY", "NVO",
    "MRK", "PFE", "TMO", "ABT", "DHR", "VRTX", "REGN", "ISRG", "CAT",
    "DE", "GE", "HON", "RTX", "BA", "LMT", "UNP", "COP", "SLB", "LIN",
    "FCX", "NEM", "FSLR", "NEE", "KO", "PEP", "MCD", "COST", "TGT",
    "IBM", "VZ", "AMT", "PLD", "BLK", "ICE", "CME", "SPY", "QQQ", "IWM",
    "XLF", "XLE", "XLK", "XLV", "SMH", "SHOP", "SOFI", "HOOD", "MARA",
    "RBLX", "TJX", "MAR", "RCL", "BMY", "GILD", "MRNA", "BIIB", "DXCM",
    "UPS", "FDX", "WM", "ETN", "EMR", "MPC", "PSX", "APD", "SHW", "ENPH",
    "CL", "MMM", "SO", "DUK", "AEP", "O", "SPGI", "AON", "MET", "PRU",
]

# Mid-cap sensitivity universe. "FIVERR" removed (not a ticker; FVRR retained),
# duplicate RIVN and ROKU removed.
UNIVERSE_B = [
    "BILL", "HUBS", "DKNG", "DASH", "RIVN", "LCID", "BROS", "CAVA",
    "DUOL", "IOT", "CELH", "BIRK", "TOST", "MNDY", "GLBE", "PCOR",
    "WDAY", "VEEV", "ZM", "DOCU", "OKTA", "TWLO", "ESTC", "MDB",
    "CFLT", "PATH", "GTLB", "ROKU", "LYFT", "OPEN", "UPST",
    "AFRM", "ASAN", "FVRR", "U", "RKLB", "SMCI", "ARM",
    "ONON", "DECK", "CROX", "LEVI", "GPS", "ANF", "URBN", "RL",
    "TPR", "CPRI", "CHEF", "WING", "SHAK", "DPZ", "TXRH", "JACK",
    "EAT", "DINE", "PLAY", "SIX", "FUN", "LUV", "DAL", "UAL",
    "AAL", "JBLU", "SAVE", "ALK", "HA", "SKYW", "MESA", "CPA",
    "CLF", "X", "NUE", "STLD", "RS", "ATI", "HAYN", "CMC",
    "AA", "CENX", "KALU", "TECK", "RIO", "BHP", "VALE", "MT",
    "PKX", "SCCO", "HBM", "ARLP", "BTU", "ARCH", "CEIX", "CNX",
    "FANG", "DVN", "OVV", "AR",
]

# Tickers that genuinely have no 5-year history from the data source, with the
# reason. This list is the ONLY way a symbol may be dropped from a run: the
# snapshot raises SnapshotIncomplete on anything missing that is not named here,
# so an exclusion is always a recorded decision and never an accident. Populated
# from the V6 snapshot; see data/snapshot_manifest.json for the authoritative
# attempted-versus-contributing counts.
KNOWN_UNAVAILABLE = {
    # Ten tickers returned an empty frame from yfinance on 2026-09-22 — Yahoo
    # answered and had no 5-year history. Each has since been retired by a
    # corporate action (merger, acquisition, bankruptcy or symbol change); the
    # specific cause is not asserted here, only that the source no longer serves
    # the history.
    "ARCH": "no data from source; ticker retired by corporate action",
    "CEIX": "no data from source; ticker retired by corporate action",
    "CFLT": "no data from source; ticker retired by corporate action",
    "GPS":  "no data from source; symbol change (Gap now trades as GAP)",
    "HA":   "no data from source; ticker retired by corporate action",
    "HAYN": "no data from source; ticker retired by corporate action",
    "MESA": "no data from source; ticker retired by corporate action",
    "SAVE": "no data from source; ticker retired by corporate action",
    "SIX":  "no data from source; ticker retired by corporate action",
    "X":    "no data from source; ticker retired by corporate action",
    # Answers, but only from 2026-05-05 — 96 bars, under the 100-bar floor. A
    # re-listing rather than a five-year history.
    "DINE": "only 96 bars (from 2026-05-05); under the 100-bar minimum",
}

# This list IS the survivorship measurement, and it is worth reading as evidence
# rather than as bookkeeping. Every excluded name is one the author put in the
# universe from memory in 2026 and that the data source has since purged. The
# backtest can therefore only ever trade companies that survived to 2026: the
# acquired, the merged and the bankrupt are silently absent, and their absence
# removes exactly the left tail a stop-loss strategy exists to handle.
# 11 of 227 names, ~4.8%, over five years. That is a floor on the bias, not an
# estimate of it — names dropped from the author's memory before the list was
# written never had a chance to appear at all. Fixing this needs paid
# point-in-time index membership.

ALL_SYMBOLS = sorted(set(UNIVERSE_A) | set(UNIVERSE_B))

def assert_unique():
    """Duplicates in a universe silently overweight a name. Fail loudly instead."""
    for name, syms in (("UNIVERSE_A", UNIVERSE_A), ("UNIVERSE_B", UNIVERSE_B)):
        dupes = sorted({s for s in syms if syms.count(s) > 1})
        if dupes:
            raise ValueError(f"{name} has duplicates: {dupes}")

assert_unique()
