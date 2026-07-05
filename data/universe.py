"""
data/universe.py
NSE stock universe — from NIFTY50 to ~750 liquid stocks.

Universe levels:
    "nifty50"          — 50 blue-chip stocks
    "nifty100"         — NIFTY50 + NIFTY_NEXT50  (≈100 total)
    "nifty200"         — nifty100 + NIFTY_MIDCAP  (≈200 total)
    "nifty500"         — nifty100 + NIFTY_MIDCAP150 + NIFTY_SMALLCAP250,
                         plus the legacy NIFTY_MIDCAP/NIFTY_SMALLCAP samples
                         for extra coverage (≈500 total, matches NSE's real
                         Nifty 500 = Nifty 100 + Midcap 150 + Smallcap 250)
    "niftytotalmarket" — nifty500 + NIFTY_MICROCAP250 (≈750 total, matches
                         NSE's real Nifty Total Market composition)
    "all"              — alias for niftytotalmarket

FIX UNI1 (this revision): NIFTY_MIDCAP150 and NIFTY_SMALLCAP250 were
hand-curated samples (96 and 30 tickers respectively) instead of the real
150/250-member index constituent lists, and NIFTY_MICROCAP250 (ranks
501-750) didn't exist at all. This meant get_universe("niftytotalmarket")
returned ~327-344 tickers instead of the documented ~750 — the root cause
of the Market Live / Top Picks / Tomorrow's Watchlist coverage gap. All
three lists have been replaced/added using NSE Indices' official constituent
CSVs (ind_niftymidcap150list.csv, ind_niftysmallcap250list.csv,
ind_niftymicrocap250_list.csv). get_universe("niftytotalmarket") now returns
745 deduplicated tickers.

Helpers:
    get_universe(level)         → List[str]
    resolve_ticker(query)       → "RELIANCE.NS" (accepts partial / no-suffix names)
    get_sector(ticker)          → str
    get_tickers_by_sector(sector) → List[str]

CHANGES in this revision
─────────────────────────
C_VEDANTA  Vedanta Ltd completed a four-way demerger effective 15-Jun-2026:
    the combined entity split into Vedanta Aluminium Metal Ltd (VAML.NS),
    Vedanta Oil & Gas Ltd (VOGL.NS, ex-Malco Energy), Vedanta Power Ltd
    (VEDPOWER.NS, ex-Talwandi Sabo Power), and Vedanta Iron & Steel Ltd
    (VISL.NS), with VEDL.NS continuing as the residual entity (critical
    minerals / Hindustan Zinc). None of the four new entities existed in
    this universe or in cache.py's STOCK_SEARCH_MAP before this fix, which
    is why "Vedanta Iron & Steel" (and the other three) couldn't be found
    by company-name search anywhere in the app. All four are now in
    NIFTY_NEXT50 and SECTOR_MAP below. Note: as very recent listings,
    Yahoo Finance (the app's price/history source) may still have thin or
    incomplete daily-bar history for these tickers for a while after
    listing — a "DATA_UNAVAILABLE" trend-quality score on these specific
    names can be a genuine upstream data-depth gap (e.g. SMA_200 needs
    ~200 trading days, which a stock listed in June 2026 simply doesn't
    have yet), not necessarily an app bug.
"""

from __future__ import annotations
from typing import Dict, List

# ─────────────────────────────────────────────────────────────────────────────
# NIFTY 50  (imported + re-exported for backward compat)
# ─────────────────────────────────────────────────────────────────────────────
from data.fetcher import NIFTY50_TICKERS

# ─────────────────────────────────────────────────────────────────────────────
# NIFTY NEXT 50  (stocks ranked 51-100 by market cap)
# ─────────────────────────────────────────────────────────────────────────────
NIFTY_NEXT50: List[str] = [
    # Financial Services
    "CHOLAFIN.NS", "MUTHOOTFIN.NS", "BAJAJHLDNG.NS", "HDFCAMC.NS",
    "ICICIGI.NS", "ICICIPRULI.NS", "SBICARD.NS", "ABCAPITAL.NS",
    # IT / Technology
    "PERSISTENT.NS", "COFORGE.NS", "MPHASIS.NS", "LTTS.NS",
    # Auto / Capital Goods / Industrials
    "BOSCHLTD.NS", "TVSMOTOR.NS", "BEL.NS", "SIEMENS.NS",
    "ABB.NS", "HAVELLS.NS", "VOLTAS.NS", "CUMMINSIND.NS",
    # Pharma / Healthcare
    "TORNTPHARM.NS", "AUROPHARMA.NS", "MANKIND.NS",
    # FMCG / Consumer
    "MARICO.NS", "DABUR.NS", "GODREJCP.NS", "COLPAL.NS",
    "UNITDSPR.NS", "TRENT.NS", "NYKAA.NS",
    # Cement / Real Estate
    "AMBUJACEM.NS", "ACC.NS", "OBEROIRLTY.NS", "DLF.NS",
    # Energy / Power / Infra
    "ADANIGREEN.NS", "TATAPOWER.NS", "PFC.NS", "RECLTD.NS",
    "CANBK.NS", "BANKBARODA.NS",
    # Metals / Chemicals
    "VEDL.NS", "PIDILITIND.NS", "BERGEPAINT.NS",
    # Telecom
    "INDUSTOWER.NS",
    # Consumer Discretionary
    "ZYDUSLIFE.NS", "LUPIN.NS", "LODHA.NS",
    "IRCTC.NS", "NAUKRI.NS", "ETERNAL.NS",
    # FIX C_VEDANTA — four entities from Vedanta Ltd's 15-Jun-2026 demerger.
    # VEDL.NS (above) continues as the residual critical-minerals entity.
    "VAML.NS",       # Vedanta Aluminium Metal Ltd
    "VOGL.NS",       # Vedanta Oil & Gas Ltd (ex-Malco Energy Ltd)
    "VEDPOWER.NS",   # Vedanta Power Ltd (ex-Talwandi Sabo Power Ltd)
    "VISL.NS",       # Vedanta Iron & Steel Ltd
]

# ─────────────────────────────────────────────────────────────────────────────
# NIFTY MIDCAP 100  (popular midcap stocks)
# ─────────────────────────────────────────────────────────────────────────────
NIFTY_MIDCAP: List[str] = [
    # Banking / NBFC
    "IDFCFIRSTB.NS", "FEDERALBNK.NS", "BANDHANBNK.NS", "AUBANK.NS",
    "KARURVYSYA.NS", "LICHSGFIN.NS", "SUNDARMFIN.NS", "PNB.NS",
    "UNIONBANK.NS", "IDBI.NS", "RBLBANK.NS",
    # IT / Tech Services
    "KPITTECH.NS", "TATAELXSI.NS", "CYIENT.NS", "MASTEK.NS",
    "TANLA.NS", "ANGELONE.NS", "360ONE.NS",
    # Auto Ancillaries
    "BALKRISIND.NS", "EXIDEIND.NS", "SUNDRMFAST.NS",
    "TIINDIA.NS", "MOTHERSON.NS", "ASHOKLEY.NS", "ESCORTS.NS",
    # Pharma / Healthcare
    "ALKEM.NS", "GLENMARK.NS", "GRANULES.NS", "LAURUSLABS.NS",
    "IPCALAB.NS", "GLAXO.NS", "NATCOPHARM.NS",
    # FMCG / Consumer / Retail
    "VBL.NS", "RADICO.NS", "EMAMILTD.NS", "JYOTHYLAB.NS",
    "DMART.NS", "TATACONSUM.NS", "GODREJIND.NS",
    "INDIAMART.NS", "CARTRADE.NS",
    # Cement / Building Materials
    "RAMCOCEM.NS", "JKCEMENT.NS", "ASTRAL.NS", "APLAPOLLO.NS",
    # Capital Goods / Infra / Defence
    "BHEL.NS", "RVNL.NS", "KEC.NS", "THERMAX.NS",
    "NBCC.NS", "CONCOR.NS", "IRFC.NS",
    # Energy / Oil & Gas
    "IGL.NS", "MGL.NS", "PETRONET.NS", "GAIL.NS",
    "NHPC.NS", "SJVN.NS", "NLCINDIA.NS", "HINDPETRO.NS", "IOC.NS",
    # Metals / Mining
    "HINDZINC.NS", "NMDC.NS", "SAIL.NS", "MOIL.NS",
    # Real Estate
    "GODREJPROP.NS", "PHOENIXLTD.NS", "PRESTIGE.NS", "SOBHA.NS",
    # Chemicals / Specialty
    "AARTIIND.NS", "DEEPAKNTR.NS", "SRF.NS", "GNFC.NS",
    # Financial Services (exchanges, AMC)
    "CDSL.NS", "BSE.NS", "MCX.NS", "CAMS.NS", "HDFCAMC.NS",
    # Healthcare Services
    "LALPATHLAB.NS", "METROPOLIS.NS", "RAINBOW.NS", "FORTIS.NS",
    # Hotels / Travel
    "INDHOTEL.NS",
    # Textiles
    "TRIDENT.NS", "VTL.NS",
    # Others
    "MFSL.NS", "PIIND.NS", "POLYCAB.NS", "DIXON.NS",
]

# ─────────────────────────────────────────────────────────────────────────────
# NIFTY SMALLCAP  (selected liquid small-caps)
# ─────────────────────────────────────────────────────────────────────────────
NIFTY_SMALLCAP: List[str] = [
    # Finance
    "MANAPPURAM.NS", "UJJIVANSFB.NS", "JMFINANCIL.NS", "IIFL.NS",
    # IT
    "NIITLTD.NS", "BSOFT.NS",
    # Pharma
    "ABBOTINDIA.NS", "SOLARA.NS",
    # Consumer
    "BATAINDIA.NS", "SAFARI.NS", "WHIRLPOOL.NS", "SYMPHONY.NS",
    "HONASA.NS", "KALYANKJIL.NS",
    # Infra / Capital Goods
    "HUDCO.NS", "HFCL.NS", "RITES.NS",
    # Energy
    "RENUKA.NS", "SUZLON.NS",
    # Chemicals
    "VINATIORGA.NS", "FLUOROCHEM.NS", "NOCIL.NS",
    # Auto
    "ARE&M.NS",
    # Others
    "PAGEIND.NS", "MRF.NS", "SCHAEFFLER.NS", "SOLARINDS.NS",
    "VBL.NS", "JUBLFOOD.NS", "TATACOMM.NS", "SUNTV.NS",
]

# ─────────────────────────────────────────────────────────────────────────────
# NIFTY MIDCAP 150  (ranks 101-250 by free-float market cap)
# FIX UNI1 — replaced a hand-curated 96-ticker sample with the full 150-ticker
# official constituent list (NSE Indices, ind_niftymidcap150list.csv). The old
# sample was ~54 tickers short of the real index and was the primary cause of
# Market Live scanning ~327 stocks instead of the documented ~750: this list
# alone was silently missing over a third of its members, and the same problem
# was even worse in NIFTY_SMALLCAP250 and the (missing) microcap tier below.
# ─────────────────────────────────────────────────────────────────────────────
NIFTY_MIDCAP150: List[str] = [
    "360ONE.NS", "3MINDIA.NS", "ACC.NS", "AIAENG.NS",
    "APLAPOLLO.NS", "AUBANK.NS", "AWL.NS", "ABBOTINDIA.NS",
    "ATGL.NS", "ABCAPITAL.NS", "AJANTPHARM.NS", "ALKEM.NS",
    "ANTHEM.NS", "APARINDS.NS", "APOLLOTYRE.NS", "ASHOKLEY.NS",
    "ASTRAL.NS", "AUROPHARMA.NS", "AIIL.NS", "BSE.NS",
    "BAJAJHFL.NS", "BALKRISIND.NS", "BANKINDIA.NS", "MAHABANK.NS",
    "BERGEPAINT.NS", "BDL.NS", "BHARATFORG.NS", "BHEL.NS",
    "BHARTIHEXA.NS", "GROWW.NS", "BIOCON.NS", "BLUESTARCO.NS",
    "CRISIL.NS", "COCHINSHIP.NS", "COFORGE.NS", "COLPAL.NS",
    "CONCOR.NS", "COROMANDEL.NS", "DABUR.NS", "DALBHARAT.NS",
    "DIXON.NS", "ENDURANCE.NS", "ESCORTS.NS", "EXIDEIND.NS",
    "NYKAA.NS", "FEDERALBNK.NS", "FORTIS.NS", "GVT&D.NS",
    "GMRAIRPORT.NS", "GICRE.NS", "GLAXO.NS", "GLENMARK.NS",
    "MEDANTA.NS", "GODFRYPHLP.NS", "GODREJIND.NS", "GODREJPROP.NS",
    "FLUOROCHEM.NS", "HDBFS.NS", "HAVELLS.NS", "HEROMOTOCO.NS",
    "HEXT.NS", "HINDPETRO.NS", "POWERINDIA.NS", "HONAUT.NS",
    "HUDCO.NS", "ICICIGI.NS", "ICICIAMC.NS", "ICICIPRULI.NS",
    "IDFCFIRSTB.NS", "ITCHOTELS.NS", "INDIANB.NS", "IRCTC.NS",
    "IREDA.NS", "INDUSTOWER.NS", "INDUSINDBK.NS", "NAUKRI.NS",
    "IPCALAB.NS", "JKCEMENT.NS", "JSWENERGY.NS", "JSWINFRA.NS",
    "JSL.NS", "JUBLFOOD.NS", "KPRMILL.NS", "KEI.NS",
    "KPITTECH.NS", "KALYANKJIL.NS", "LTF.NS", "LTTS.NS",
    "LGEINDIA.NS", "LICHSGFIN.NS", "LAURUSLABS.NS", "LENSKART.NS",
    "LICI.NS", "LINDEINDIA.NS", "LLOYDSME.NS", "LUPIN.NS",
    "MRF.NS", "M&MFIN.NS", "MANKIND.NS", "MARICO.NS",
    "MFSL.NS", "MOTILALOFS.NS", "MPHASIS.NS", "MCX.NS",
    "NHPC.NS", "NLCINDIA.NS", "NMDC.NS", "NTPCGREEN.NS",
    "NATIONALUM.NS", "NAM-INDIA.NS", "OBEROIRLTY.NS", "OIL.NS",
    "PAYTM.NS", "OFSS.NS", "POLICYBZR.NS", "PIIND.NS",
    "PAGEIND.NS", "PATANJALI.NS", "PERSISTENT.NS", "PETRONET.NS",
    "PHOENIXLTD.NS", "POLYCAB.NS", "PREMIERENE.NS", "PRESTIGE.NS",
    "RADICO.NS", "RVNL.NS", "SBICARD.NS", "SJVN.NS",
    "SRF.NS", "SCHAEFFLER.NS", "SAIL.NS", "SUNDARMFIN.NS",
    "SUPREMEIND.NS", "SUZLON.NS", "SWIGGY.NS", "TATACOMM.NS",
    "TATAELXSI.NS", "TATAINVEST.NS", "NIACL.NS", "THERMAX.NS",
    "TORNTPOWER.NS", "TIINDIA.NS", "UNOMINDA.NS", "UPL.NS",
    "UBL.NS", "VMM.NS", "IDEA.NS", "VOLTAS.NS",
    "WAAREEENER.NS", "YESBANK.NS",
]

# ─────────────────────────────────────────────────────────────────────────────
# NIFTY SMALLCAP 250  (ranks 251-500 by free-float market cap)
# FIX UNI1 — replaced a 30-ticker sample with the full 250-ticker official
# constituent list (NSE Indices, ind_niftysmallcap250list.csv).
# ─────────────────────────────────────────────────────────────────────────────
NIFTY_SMALLCAP250: List[str] = [
    "ACMESOLAR.NS", "AADHARHFC.NS", "AARTIIND.NS", "AAVAS.NS",
    "ACE.NS", "ACUTAAS.NS", "ABFRL.NS", "ABLBL.NS",
    "ABREL.NS", "ABSLAMC.NS", "CPPLUS.NS", "AEGISLOG.NS",
    "AEGISVOPAK.NS", "AFCONS.NS", "AFFLE.NS", "ABDL.NS",
    "ARE&M.NS", "AMBER.NS", "ANANDRATHI.NS", "ANANTRAJ.NS",
    "ANGELONE.NS", "ANURAS.NS", "APTUS.NS", "ASAHIINDIA.NS",
    "ASTERDM.NS", "ATHERENERG.NS", "ATUL.NS", "BEML.NS",
    "BLS.NS", "BALRAMCHIN.NS", "BANDHANBNK.NS", "BATAINDIA.NS",
    "BAYERCROP.NS", "BELRISE.NS", "BIKAJI.NS", "BSOFT.NS",
    "BLUEDART.NS", "BLUEJET.NS", "BBTC.NS", "FIRSTCRY.NS",
    "BRIGADE.NS", "MAPMYINDIA.NS", "CCL.NS", "CESC.NS",
    "CIEINDIA.NS", "CANFINHOME.NS", "CANHLIFE.NS", "CAPLIPOINT.NS",
    "CGCL.NS", "CARBORUNIV.NS", "CARTRADE.NS", "CASTROLIND.NS",
    "CEATLTD.NS", "CEMPRO.NS", "CENTRALBK.NS", "CDSL.NS",
    "CHALET.NS", "CHAMBLFERT.NS", "CHENNPETRO.NS", "CHOICEIN.NS",
    "CHOLAHLDNG.NS", "CUB.NS", "CLEAN.NS", "COHANCE.NS",
    "CAMS.NS", "CONCORDBIO.NS", "CRAFTSMAN.NS", "CREDITACC.NS",
    "CROMPTON.NS", "CYIENT.NS", "DCMSHRIRAM.NS", "DOMS.NS",
    "DATAPATTNS.NS", "DEEPAKFERT.NS", "DEEPAKNTR.NS", "DELHIVERY.NS",
    "DEVYANI.NS", "LALPATHLAB.NS", "EIDPARRY.NS", "EIHOTEL.NS",
    "ELECON.NS", "ELGIEQUIP.NS", "EMAMILTD.NS", "EMCURE.NS",
    "EMMVEE.NS", "ENGINERSIN.NS", "ERIS.NS", "FACT.NS",
    "FINCABLES.NS", "FSL.NS", "FIVESTAR.NS", "FORCEMOT.NS",
    "GABRIEL.NS", "GALLANTT.NS", "GRSE.NS", "GILLETTE.NS",
    "GLAND.NS", "GODIGIT.NS", "GPIL.NS", "GRANULES.NS",
    "GRAPHITE.NS", "GRAVITA.NS", "GESHIP.NS", "GMDCLTD.NS",
    "HEG.NS", "HBLENGINE.NS", "HFCL.NS", "HSCL.NS",
    "HINDCOPPER.NS", "HOMEFIRST.NS", "HONASA.NS", "IDBI.NS",
    "IFCI.NS", "IIFL.NS", "IRB.NS", "IRCON.NS",
    "ITI.NS", "INDGN.NS", "INDIACEM.NS", "INDIAMART.NS",
    "IEX.NS", "IOB.NS", "IGL.NS", "INOXWIND.NS",
    "INTELLECT.NS", "IGIL.NS", "IKS.NS", "JBCHEPHARM.NS",
    "JBMA.NS", "JKTYRE.NS", "JMFINANCIL.NS", "JSWCEMENT.NS",
    "JSWDULUX.NS", "JAINREC.NS", "JPPOWER.NS", "J&KBANK.NS",
    "JINDALSAW.NS", "JUBLINGREA.NS", "JUBLPHARMA.NS", "JWL.NS",
    "JYOTICNC.NS", "KAJARIACER.NS", "KPIL.NS", "KARURVYSYA.NS",
    "KAYNES.NS", "KEC.NS", "KFINTECH.NS", "KIRLOSENG.NS",
    "KIMS.NS", "LTFOODS.NS", "LATENTVIEW.NS", "THELEELA.NS",
    "LEMONTREE.NS", "MMTC.NS", "MGL.NS", "MANAPPURAM.NS",
    "MRPL.NS", "MEESHO.NS", "MINDACORP.NS", "MSUMI.NS",
    "NATCOPHARM.NS", "NBCC.NS", "NCC.NS", "NSLNISP.NS",
    "NH.NS", "NAVA.NS", "NAVINFLUOR.NS", "NETWEB.NS",
    "NEULANDLAB.NS", "NEWGEN.NS", "NIVABUPA.NS", "NUVAMA.NS",
    "NUVOCO.NS", "OLAELEC.NS", "OLECTRA.NS", "ONESOURCE.NS",
    "PCBL.NS", "PGEL.NS", "PNBHOUSING.NS", "PTCIL.NS",
    "PVRINOX.NS", "PARADEEP.NS", "PFIZER.NS", "PWL.NS",
    "PINELABS.NS", "PIRAMALFIN.NS", "PPLPHARMA.NS", "POLYMED.NS",
    "POONAWALLA.NS", "RRKABEL.NS", "RBLBANK.NS", "RHIM.NS",
    "RITES.NS", "RAILTEL.NS", "RAINBOW.NS", "RKFORGE.NS",
    "REDINGTON.NS", "RPOWER.NS", "SBFC.NS", "SAGILITY.NS",
    "SAILIFE.NS", "SAMMAANCAP.NS", "SAPPHIRE.NS", "SARDAEN.NS",
    "SAREGAMA.NS", "SCHNEIDER.NS", "SCI.NS", "SHYAMMETL.NS",
    "SIGNATURE.NS", "SOBHA.NS", "SONACOMS.NS", "SONATSOFTW.NS",
    "STARHEALTH.NS", "SUMICHEM.NS", "SUNTV.NS", "SPLPETRO.NS",
    "SWANCORP.NS", "SYNGENE.NS", "SYRMA.NS", "TBOTEK.NS",
    "TATACHEM.NS", "TATATECH.NS", "TTML.NS", "TECHNOE.NS",
    "TEGA.NS", "TEJASNET.NS", "TENNIND.NS", "RAMCOCEM.NS",
    "TIMKEN.NS", "TITAGARH.NS", "TARIL.NS", "TRAVELFOOD.NS",
    "TRIDENT.NS", "TRITURBINE.NS", "UCOBANK.NS", "UTIAMC.NS",
    "URBANCO.NS", "USHAMART.NS", "VTL.NS", "VIJAYA.NS",
    "WELCORP.NS", "WELSPUNLIV.NS", "WHIRLPOOL.NS", "WOCKPHARMA.NS",
    "ZFCVINDIA.NS", "ZEEL.NS", "ZENTEC.NS", "ZENSARTECH.NS",
    "ZYDUSWELL.NS", "ECLERX.NS",
]

# ─────────────────────────────────────────────────────────────────────────────
# NIFTY MICROCAP 250  (ranks 501-750; the missing tier)
# FIX UNI1 — this tier didn't exist at all before this fix. NSE's own Nifty
# Total Market index = Nifty 500 (Nifty 100 + Midcap 150 + Smallcap 250, i.e.
# 100+150+250=500) + Nifty Microcap 250 (ranks 501-750) = 750 stocks. Without
# this list, get_universe("niftytotalmarket") had a hard ceiling around 400-450
# tickers no matter how complete the other lists were, because a whole 250-stock
# tier of the index was never represented in this file at all.
# ─────────────────────────────────────────────────────────────────────────────
NIFTY_MICROCAP250: List[str] = [
    "ASKAUTOLTD.NS", "AXISCADES.NS", "AARTIDRUGS.NS", "AARTIPHARM.NS",
    "AVL.NS", "ADVENZYMES.NS", "AEQUS.NS", "AETHER.NS",
    "AHLUCONT.NS", "AKUMS.NS", "APLLTD.NS", "ALIVUS.NS",
    "ALKYLAMINE.NS", "ALOKINDS.NS", "APOLLO.NS", "ACI.NS",
    "ARVINDFASN.NS", "ARVIND.NS", "ASHAPURMIN.NS", "ASHOKA.NS",
    "ASTRAMICRO.NS", "ATLANTAELE.NS", "AURIONPRO.NS", "AVALON.NS",
    "AVANTIFEED.NS", "CCAVENUE.NS", "AWFIS.NS", "AZAD.NS",
    "BAJAJELEC.NS", "BALAMINES.NS", "BALUFORGE.NS", "BANCOINDIA.NS",
    "BIRLACORPN.NS", "BBOX.NS", "BLACKBUCK.NS", "BLUESTONE.NS",
    "BORORENEW.NS", "CMSINFO.NS", "CORONA.NS", "CSBBANK.NS",
    "CAMPUS.NS", "CRAMC.NS", "CAPILLARY.NS", "CELLO.NS",
    "CENTURYPLY.NS", "CERA.NS", "CRIZAC.NS", "CUPID.NS",
    "DCBBANK.NS", "DATAMATICS.NS", "DIACABS.NS", "DBL.NS",
    "AGARWALEYE.NS", "DYNAMATECH.NS", "EPL.NS", "EDELWEISS.NS",
    "EMIL.NS", "ELECTCAST.NS", "ELLEN.NS", "EMBDL.NS",
    "ENTERO.NS", "EIEL.NS", "EQUITASBNK.NS", "ETHOSLTD.NS",
    "EUREKAFORB.NS", "FEDFINA.NS", "FIEMIND.NS", "FINPIPE.NS",
    "UTLSOLAR.NS", "GHCL.NS", "GMMPFAUDLR.NS", "GMRP&UI.NS",
    "GRWRHITECH.NS", "GODREJAGRO.NS", "GOKEX.NS", "GOKULAGRO.NS",
    "GREAVESCOT.NS", "GAEL.NS", "GNFC.NS", "GPPL.NS",
    "GSFC.NS", "HGINFRA.NS", "HAPPSTMNDS.NS", "HCG.NS",
    "HEMIPROP.NS", "HERITGFOOD.NS", "HCC.NS", "IFBIND.NS",
    "IIFLCAPS.NS", "INOXINDIA.NS", "INDIAGLYCO.NS", "INDIASHLTR.NS",
    "IMFA.NS", "INDIGOPNTS.NS", "ICIL.NS", "INOXGREEN.NS",
    "IONEXCHANG.NS", "JKLAKSHMI.NS", "JKPAPER.NS", "JAIBALAJI.NS",
    "JAMNAAUTO.NS", "JSFB.NS", "JAYNECOIND.NS", "JSLL.NS",
    "JLHL.NS", "JUSTDIAL.NS", "JYOTHYLAB.NS", "KNRCON.NS",
    "KPIGREEN.NS", "KRBL.NS", "KRN.NS", "KSB.NS",
    "KANSAINER.NS", "KTKBANK.NS", "KSCL.NS", "KIRLOSBROS.NS",
    "KIRLPNU.NS", "KITEX.NS", "LXCHEM.NS", "IXIGO.NS",
    "LLOYDSENGG.NS", "LLOYDSENT.NS", "LUMAXTECH.NS", "MOIL.NS",
    "MSTCLTD.NS", "MTARTECH.NS", "MAHSCOOTER.NS", "MAHSEAMLES.NS",
    "MANORAMA.NS", "MARKSANS.NS", "MASTEK.NS", "MEDPLUS.NS",
    "METROPOLIS.NS", "MIDHANI.NS", "BECTORFOOD.NS", "NEOGEN.NS",
    "NESCO.NS", "NFL.NS", "NAZARA.NS", "NETWORK18.NS",
    "OPTIEMUS.NS", "ORIENTCEM.NS", "ORKLAINDIA.NS", "OSWALPUMPS.NS",
    "PNGJL.NS", "PCJEWELLER.NS", "PNCINFRA.NS", "PTC.NS",
    "PARAS.NS", "PARKHOSPS.NS", "PGIL.NS", "PICCADIL.NS",
    "POWERMECH.NS", "PRAJIND.NS", "PRICOLLTD.NS", "PFOCUS.NS",
    "PRSMJOHNSN.NS", "PRIVISCL.NS", "PRUDENT.NS", "PURVA.NS",
    "QPOWER.NS", "QUESS.NS", "RAIN.NS", "RALLIS.NS",
    "RCF.NS", "RATEGAIN.NS", "RATNAMANI.NS", "RTNINDIA.NS",
    "RTNPOWER.NS", "RAYMONDLSL.NS", "REDTAPE.NS", "REFEX.NS",
    "RELAXO.NS", "RELIGARE.NS", "RBA.NS", "ROUTE.NS",
    "RUBICON.NS", "SKFINDUS.NS", "SKFINDIA.NS", "SKYGOLD.NS",
    "SMLMAH.NS", "SHRIPISTON.NS", "SAATVIKGL.NS", "SAFARI.NS",
    "SAMHI.NS", "SANDUMA.NS", "SANOFICONR.NS", "SANSERA.NS",
    "SENCO.NS", "STYL.NS", "SHAILY.NS", "SHAKTIPUMP.NS",
    "SHARDACROP.NS", "SHAREINDIA.NS", "SFL.NS", "SHILPAMED.NS",
    "RENUKA.NS", "SKIPPER.NS", "SMARTWORKS.NS", "SOUTHBANK.NS",
    "LOTUSDEV.NS", "STARCEMENT.NS", "SWSOLAR.NS", "STLTECH.NS",
    "STAR.NS", "STYRENIX.NS", "SUBROS.NS", "SUDARSCHEM.NS",
    "SUDEEPPHRM.NS", "SPARC.NS", "SUNTECK.NS", "SUPRIYA.NS",
    "SURYAROSNI.NS", "TARC.NS", "TDPOWERSYS.NS", "TSFINV.NS",
    "TVSSCS.NS", "TMB.NS", "TANLA.NS", "TEXRAIL.NS",
    "THANGAMAYL.NS", "ANUP.NS", "THOMASCOOK.NS", "THYROCARE.NS",
    "TI.NS", "TIMETECHNO.NS", "TIPSMUSIC.NS", "TRANSRAILL.NS",
    "TRIVENI.NS", "UJJIVANSFB.NS", "VGUARD.NS", "VMART.NS",
    "VIPIND.NS", "V2RETAIL.NS", "WABAG.NS", "VAIBHAVGBL.NS",
    "DBREALTY.NS", "VARROC.NS", "MANYAVAR.NS", "VIKRAMSOLR.NS",
    "VIYASH.NS", "VOLTAMP.NS", "WAAREERTL.NS", "WAKEFIT.NS",
    "WEWORK.NS", "WEBELSOLAR.NS", "WELENT.NS", "WESTLIFE.NS",
    "YATHARTH.NS", "ZAGGLE.NS",
]

# ─────────────────────────────────────────────────────────────────────────────
# SECTOR MAP  (ticker → sector string)
# ─────────────────────────────────────────────────────────────────────────────
_SECTOR_ASSIGNMENTS: Dict[str, List[str]] = {
    "IT": [
        "TCS.NS", "INFY.NS", "WIPRO.NS", "HCLTECH.NS", "TECHM.NS",
        "LTIM.NS", "PERSISTENT.NS", "COFORGE.NS", "MPHASIS.NS", "LTTS.NS",
        "KPITTECH.NS", "TATAELXSI.NS", "CYIENT.NS", "MASTEK.NS",
        "NIITLTD.NS", "BSOFT.NS", "TANLA.NS", "RATEGAIN.NS", "ROUTE.NS",
        "INTELLECT.NS", "ZENSAR.NS", "HEXAWARE.NS", "HAPPSTMNDS.NS",
        "NEWGEN.NS", "BIRLASOFT.NS", "DATAMATICS.NS", "SAKSOFT.NS", "OFSS.NS",
    ],
    "Banking": [
        "HDFCBANK.NS", "ICICIBANK.NS", "SBIN.NS", "KOTAKBANK.NS", "AXISBANK.NS",
        "INDUSINDBK.NS", "IDFCFIRSTB.NS", "FEDERALBNK.NS", "BANDHANBNK.NS",
        "AUBANK.NS", "KARURVYSYA.NS", "PNB.NS", "UNIONBANK.NS",
        "IDBI.NS", "CANBK.NS", "BANKBARODA.NS", "RBLBANK.NS",
        "JKBANK.NS", "DCBBANK.NS", "SOUTHBANK.NS", "EQUITASBNK.NS",
        "CREDITACC.NS",
    ],
    "Finance": [
        "BAJFINANCE.NS", "BAJAJFINSV.NS", "SHRIRAMFIN.NS", "CHOLAFIN.NS",
        "MUTHOOTFIN.NS", "BAJAJHLDNG.NS", "HDFCAMC.NS", "ICICIGI.NS",
        "ICICIPRULI.NS", "SBICARD.NS", "ABCAPITAL.NS", "SUNDARMFIN.NS",
        "LICHSGFIN.NS", "MANAPPURAM.NS", "UJJIVANSFB.NS", "MFSL.NS",
        "JMFINANCIL.NS", "IIFL.NS", "ANGELONE.NS", "360ONE.NS",
        "CDSL.NS", "BSE.NS", "MCX.NS", "CAMS.NS",
        "EDELWEISS.NS", "MOTILALOFS.NS", "NUVAMA.NS", "POONAWALLA.NS",
        "HOMEFIRST.NS", "APTUS.NS", "AAVAS.NS",
        "POLICYBZR.NS", "PAYTM.NS", "SBFC.NS", "UGROCAP.NS",
        "SPANDANA.NS", "ARMANFIN.NS", "CRISIL.NS", "ICRA.NS", "CARERATING.NS",
    ],
    "Pharma": [
        "SUNPHARMA.NS", "DRREDDY.NS", "CIPLA.NS", "DIVISLAB.NS",
        "TORNTPHARM.NS", "AUROPHARMA.NS", "MANKIND.NS", "LUPIN.NS",
        "ALKEM.NS", "GLENMARK.NS", "GRANULES.NS", "LAURUSLABS.NS",
        "IPCALAB.NS", "GLAXO.NS", "NATCOPHARM.NS", "ABBOTINDIA.NS",
        "ZYDUSLIFE.NS", "ERIS.NS", "MARKSANS.NS", "JB.NS",
        "GLAND.NS", "NEULANDLAB.NS", "IOLCP.NS", "SEQUENT.NS",
        "CAPLIPOINT.NS", "WINDLAS.NS", "LXCHEM.NS", "JUBLPHARMA.NS",
        "SOLARA.NS",
    ],
    "Healthcare": [
        "APOLLOHOSP.NS", "MAXHEALTH.NS", "FORTIS.NS",
        "LALPATHLAB.NS", "METROPOLIS.NS", "RAINBOW.NS",
        "MEDANTA.NS", "NARAYANA.NS", "YATHARTH.NS",
    ],
    "Auto": [
        "MARUTI.NS", "TMCV.NS", "BAJAJ-AUTO.NS", "EICHERMOT.NS",
        "HEROMOTOCO.NS", "TVSMOTOR.NS", "ASHOKLEY.NS", "ESCORTS.NS",
        "BALKRISIND.NS", "EXIDEIND.NS", "SUNDRMFAST.NS", "TIINDIA.NS",
        "MOTHERSON.NS", "BOSCHLTD.NS", "ARE&M.NS", "SCHAEFFLER.NS",
        "OLECTRA.NS", "SUPRAJIT.NS", "GABRIEL.NS", "SUBROS.NS",
        "LUMAXIND.NS", "SANDHAR.NS", "ENDURANCE.NS", "MINDA.NS",
        "FIEM.NS", "ROLEX.NS",
    ],
    "FMCG": [
        "HINDUNILVR.NS", "ITC.NS", "NESTLEIND.NS", "BRITANNIA.NS",
        "TATACONSUM.NS", "MARICO.NS", "DABUR.NS", "GODREJCP.NS",
        "COLPAL.NS", "UNITDSPR.NS", "EMAMILTD.NS", "JYOTHYLAB.NS",
        "BIKAJI.NS", "RADICO.NS", "VBL.NS", "JUBLFOOD.NS",
        "BATAINDIA.NS", "VSTIND.NS", "GODFRYPHLP.NS", "GILLETTE.NS",
        "ZYDUSWELL.NS", "BAJAJCON.NS", "HAWKINCOOK.NS",
    ],
    "Energy": [
        "RELIANCE.NS", "ONGC.NS", "BPCL.NS", "NTPC.NS", "POWERGRID.NS",
        "TATAPOWER.NS", "ADANIGREEN.NS", "ADANITRANS.NS", "PFC.NS",
        "RECLTD.NS", "NHPC.NS", "SJVN.NS", "NLCINDIA.NS",
        "IGL.NS", "MGL.NS", "PETRONET.NS", "GAIL.NS",
        "HINDPETRO.NS", "IOC.NS", "SUZLON.NS", "RPOWER.NS",
        # FIX C_VEDANTA — oil & gas and power businesses spun out of VEDL.NS
        "VOGL.NS", "VEDPOWER.NS",
    ],
    "Metal": [
        "TATASTEEL.NS", "JSWSTEEL.NS", "HINDALCO.NS",
        "HINDZINC.NS", "NMDC.NS", "SAIL.NS", "MOIL.NS",
        "VEDL.NS", "RATNAMANI.NS", "APARINDS.NS", "JINDALSAW.NS",
        "SHYAMMETL.NS", "SUNFLAG.NS", "TATAMETALI.NS",
        # FIX C_VEDANTA — aluminium and iron/steel businesses spun out of VEDL.NS
        "VAML.NS", "VISL.NS",
    ],
    "Chemicals": [
        "PIDILITIND.NS", "AARTIIND.NS", "DEEPAKNTR.NS",
        "SRF.NS", "GNFC.NS", "VINATIORGA.NS", "FLUOROCHEM.NS", "NOCIL.NS",
        "SOLARINDS.NS", "CLEAN.NS", "TATACHEM.NS", "ALKYLAMINE.NS",
        "FINEORG.NS", "NAVINFLUOR.NS", "SUDARSCHEM.NS", "BALAMINES.NS",
        "EPIGRAL.NS", "AETHER.NS", "LXCHEM.NS",
    ],
    "CapitalGoods": [
        "LT.NS", "BEL.NS", "SIEMENS.NS", "ABB.NS", "HAVELLS.NS",
        "VOLTAS.NS", "CUMMINSIND.NS", "BHEL.NS", "RVNL.NS",
        "KEC.NS", "THERMAX.NS", "NBCC.NS", "CONCOR.NS",
        "IRFC.NS", "HUDCO.NS", "RITES.NS", "POLYCAB.NS",
        "DIXON.NS", "HFCL.NS", "TITAGARH.NS", "GRINDWELL.NS",
        "KAYNES.NS", "SYRMA.NS", "TEJASNET.NS", "IRCON.NS",
        "RAILTEL.NS", "VGUARD.NS", "FINOLEX.NS", "ELGIEQUIP.NS",
        "PARAS.NS", "WELSPUNLIV.NS",
    ],
    "Cement": [
        "ULTRACEMCO.NS", "SHREECEM.NS", "AMBUJACEM.NS", "ACC.NS",
        "RAMCOCEM.NS", "JKCEMENT.NS", "HEIDELBERG.NS", "INDIACEM.NS",
        "STARCEMENT.NS", "NUVOCO.NS",
    ],
    "RealEstate": [
        "DLF.NS", "GODREJPROP.NS", "OBEROIRLTY.NS", "PHOENIXLTD.NS",
        "PRESTIGE.NS", "SOBHA.NS", "LODHA.NS",
        "MAHLIFE.NS", "KOLTEPATIL.NS", "BRIGADE.NS", "SUNTECK.NS",
        "ASHIANA.NS", "IBREALEST.NS", "ELDECO.NS",
    ],
    "Telecom": [
        "BHARTIARTL.NS", "INDUSTOWER.NS", "TATACOMM.NS",
    ],
    "Retail": [
        "TRENT.NS", "DMART.NS", "NYKAA.NS", "INDIAMART.NS",
        "KALYANKJIL.NS", "CARTRADE.NS", "SAFARI.NS", "WHIRLPOOL.NS",
        "CAMPUS.NS", "DEVYANI.NS", "WESTLIFE.NS", "SAPPHIRE.NS",
        "VMART.NS",
    ],
    "Conglomerate": [
        "ADANIENT.NS", "ADANIPORTS.NS", "GRASIM.NS",
        "TITAN.NS", "ASIANPAINT.NS", "BERGEPAINT.NS", "M&M.NS",
        "GODREJIND.NS",
    ],
    "Media": [
        "SUNTV.NS", "ZEEL.NS", "PVRINOX.NS", "NAZARA.NS",
    ],
    "Textiles": [
        "TRIDENT.NS", "VTL.NS", "KPRMILL.NS", "RAYMOND.NS",
        "SIYARAM.NS", "NITIN.NS", "GARFIBRES.NS",
    ],
    "Hospitality": [
        "INDHOTEL.NS", "CHALET.NS", "WONDERLA.NS", "TAJGVK.NS",
    ],
    "Shipping": [
        "GESHIP.NS", "SCI.NS", "COCHINSHIP.NS", "MAZDOCK.NS",
    ],
    "Consumer": [
        "SYMPHONY.NS", "HONASA.NS", "BAJAJELEC.NS",
        "HAWKINCOOK.NS", "JUBLPHARMA.NS",
    ],
}

# Build flat SECTOR_MAP: ticker → sector
SECTOR_MAP: Dict[str, str] = {}
for _sector, _tickers in _SECTOR_ASSIGNMENTS.items():
    for _t in _tickers:
        SECTOR_MAP[_t] = _sector

# ─────────────────────────────────────────────────────────────────────────────
# Company name lookup (upper-stripped base name → .NS ticker)
# ─────────────────────────────────────────────────────────────────────────────
def _build_name_map() -> Dict[str, str]:
    """Build lookup: "RELIANCE" → "RELIANCE.NS",  "BAJAJ-AUTO" → "BAJAJ-AUTO.NS" """
    m: Dict[str, str] = {}
    for t in get_universe("niftytotalmarket"):
        base = t.replace(".NS", "").replace(".BO", "")
        m[base.upper()] = t
    return m

_NAME_MAP: Dict[str, str] = {}   # populated lazily

# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def get_universe(level: str = "nifty50") -> List[str]:
    """
    Return the ticker list for the requested universe level.

    level:
        "nifty50"          →  50 tickers
        "nifty100"         → 100 tickers
        "nifty200"         → ~200 tickers
        "nifty500"         → ~500 tickers
        "niftytotalmarket" → ~745 tickers  (recommended for Market Live broad scan)
        "all"              → alias for niftytotalmarket
    """
    level = level.lower().strip()

    if level == "nifty50":
        return list(NIFTY50_TICKERS)

    if level == "nifty100":
        seen, result = set(), []
        for t in list(NIFTY50_TICKERS) + NIFTY_NEXT50:
            if t not in seen:
                seen.add(t); result.append(t)
        return result

    if level == "nifty200":
        seen, result = set(), []
        for t in list(NIFTY50_TICKERS) + NIFTY_NEXT50 + NIFTY_MIDCAP:
            if t not in seen:
                seen.add(t); result.append(t)
        return result

    if level == "nifty500":
        # FIX UNI1 — this used to be nifty200 + NIFTY_SMALLCAP only, which never
        # included NIFTY_MIDCAP150 / NIFTY_SMALLCAP250 at all. The real Nifty 500
        # = Nifty 100 + Nifty Midcap 150 + Nifty Smallcap 250 (100+150+250=500).
        # NIFTY_MIDCAP / NIFTY_SMALLCAP (the older, shorter hand lists) are kept
        # in the union too so nothing that was previously covered is dropped.
        seen, result = set(), []
        for t in (list(NIFTY50_TICKERS) + NIFTY_NEXT50 + NIFTY_MIDCAP
                  + NIFTY_SMALLCAP + NIFTY_MIDCAP150 + NIFTY_SMALLCAP250):
            if t not in seen:
                seen.add(t); result.append(t)
        return result

    if level in ("niftytotalmarket", "all"):
        # FIX UNI1 — Nifty Total Market = Nifty 500 + Nifty Microcap 250
        # (ranks 501-750). NIFTY_MICROCAP250 previously didn't exist in this
        # file, so this tier — and ~250 stocks — were missing entirely.
        seen, result = set(), []
        for t in (list(NIFTY50_TICKERS) + NIFTY_NEXT50 + NIFTY_MIDCAP
                  + NIFTY_SMALLCAP + NIFTY_MIDCAP150 + NIFTY_SMALLCAP250
                  + NIFTY_MICROCAP250):
            if t not in seen:
                seen.add(t); result.append(t)
        return result

    # fallback — treat unknown level as nifty500
    seen, result = set(), []
    for t in list(NIFTY50_TICKERS) + NIFTY_NEXT50 + NIFTY_MIDCAP + NIFTY_SMALLCAP:
        if t not in seen:
            seen.add(t); result.append(t)
    return result


def resolve_ticker(query: str) -> str:
    """
    Resolve a user query to a canonical .NS ticker.

    Accepts:
        "RELIANCE"         → "RELIANCE.NS"
        "reliance"         → "RELIANCE.NS"
        "RELIANCE.NS"      → "RELIANCE.NS"
        "Bajaj Auto"       → "BAJAJ-AUTO.NS"
        "TCS.BO"           → "TCS.NS"   (BSE to NSE)

    Raises ValueError with suggestions if not found.
    """
    global _NAME_MAP
    if not _NAME_MAP:
        _NAME_MAP = _build_name_map()

    q = query.strip().upper().replace(".BO", "").replace(".NS", "")
    q = q.replace(" ", "").replace("&", "&")   # normalise spaces

    # 1. Exact match
    if q in _NAME_MAP:
        return _NAME_MAP[q]

    # 2. Partial match — q is substring of any key
    matches = [k for k in _NAME_MAP if q in k or k in q]
    if len(matches) == 1:
        return _NAME_MAP[matches[0]]
    if len(matches) > 1:
        # prefer exact prefix match
        prefix = [m for m in matches if m.startswith(q)]
        if prefix:
            return _NAME_MAP[prefix[0]]
        raise ValueError(
            f"'{query}' is ambiguous. Did you mean: "
            + ", ".join(_NAME_MAP[m] for m in matches[:5])
        )

    # 3. Accept as-is with .NS suffix (might be a valid ticker not in our list)
    candidate = q + ".NS"
    return candidate   # fetcher will raise if invalid


def get_sector(ticker: str) -> str:
    """Return sector for a ticker. Returns 'Other' if not in map."""
    t = ticker.upper()
    if not t.endswith(".NS"):
        t += ".NS"
    return SECTOR_MAP.get(t, "Other")


def get_tickers_by_sector(sector: str) -> List[str]:
    """Return all tickers in a given sector across the full universe."""
    return [t for t, s in SECTOR_MAP.items() if s == sector]


def list_sectors() -> List[str]:
    """Return all unique sector names in the universe."""
    return sorted(set(SECTOR_MAP.values()))
