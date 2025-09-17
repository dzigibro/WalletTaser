#!/usr/bin/env python3
# ─────────────────────────────────────────────────────────────
#  #  (full report  + 12-month savings projection)
# ─────────────────────────────────────────────────────────────
"""
$ python3 finance.py
$ python3 finance.py -f bank.xlsx --fx 118 --sqlite --debug
Creates ./finance_report_<timestamp>/  with:
  totals.png, vendors_top.png, needs_wants.png,
  weekday_spend.png, hourly_spend.png (if data present),
  monthly_trends.png, rolling30_spend.png (or rolling7*),
  monthly_net.png, projected_net.png,
  projected_savings.png  ⟵ NEW
  full_enriched_dataset.csv  (+ wallettaser.db if --sqlite)
"""
from __future__ import annotations
import argparse, glob, logging, os, re, sqlite3, sys, textwrap
from datetime import datetime, timedelta
from itertools import cycle

import matplotlib.pyplot as plt
import pandas as pd

DEF_FX   = 117.0                       # default RSD → EUR
DEFAULT_USER = 'default'
CURRENT_TAGS: dict[str, str] = {}

from persistence import (
    DB_PATH,
    VendorTagRepository,
    apply_tagging_decisions,
)

# ─────────────────── logging ────────────────────
def setup_logging(debug: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if debug else logging.INFO,
        format='[%(levelname)s] %(message)s'
    )

# ─────────────────── helpers ─────────────────────
fmt  = lambda x: f'{x:,.2f}'
latest_xls = lambda: sorted(glob.glob('*.xls*'),
                            key=os.path.getmtime, reverse=True)[0]

# ─────────── vendor  patterns ──────────
PATTERNS = {
    'MAXI':['maxi'], 'TIDAL':['tidal'],
    'CAR GO':['car go','cargo'], 'APOTEKA':['apoteka'], 'LIDL':['lidl'],
    'EBAY':['ebay'], 'ALIEXPRESS':['aliexpress','ali express','ali'],
    'GO TECH':['go technologies'],
    'PAYPAL':['paypal'], 'WOLT':['wolt'], 'DEXPRESS':['dexpress'],
}
ADVANCED_PATTERNS = {
    'FOOD':['lidl','maxi','idea','tempo','shop&go'],
    'TRANSPORT':['car go','naxis','busplus'],
    'EDUCATION':['udemy','tryhackme','coursera','book'],
    'MEDICAL':['apoteka','pharmacy','dr'],
    'ENTERTAINMENT':['netflix','tidal','youtube','spotify'],
}
def vendor(opis:str)->str:
    low=opis.lower()
    for v,keys in PATTERNS.items():
        if any(k in low for k in keys): return v
    m=re.search(r'[A-Za-z]{4,}',opis)
    return m.group(0).upper() if m else 'OTHER'

# ─── categorisation ───
def _base_cat(r:pd.Series)->str:
    o,t,v=r['Opis'].lower(), r['Tip'].lower(), r['Iznos']
    if 'kupovina eur' in o:                                 return 'SAVINGS'
    if any(w in o for w in ('zarada','prilivi')) or 'uplata' in t:  return 'INCOME'
    if any(w in o for w in ('xtb','binance','bifinity','bit')):     return 'STOCKS/CRYPTO'
    if any(w in o for w in ('bankomat','isplata gotovine')):        return 'ATM_CASHOUT'
    if v>0: return 'INCOME'
    return 'SPENDING'

def _adv_cat(r:pd.Series)->str:
    l=r['Opis'].lower()
    for c,keys in ADVANCED_PATTERNS.items():
        if any(k in l for k in keys): return c
    return _base_cat(r)

# ─── load & clean ───
def load_clean(path:str)->pd.DataFrame:
    raw=pd.read_excel(path,header=None,dtype=str)
    hdr=next(i for i in range(30) if sum(
        any(k in str(c).lower() for k in ('datum','tip','opis','iznos'))
        for c in raw.iloc[i])>=3)
    df=pd.read_excel(path,header=hdr,dtype=str)
    ren={}
    for c in df.columns:
        l=str(c).lower()
        if 'datum' in l: ren[c]='Datum'
        elif 'tip' in l: ren[c]='Tip'
        elif any(w in l for w in ('opis','naziv','det')): ren[c]='Opis'
        elif any(w in l for w in ('iznos','amount','suma')): ren[c]='Iznos'
    df=df.rename(columns=ren)[['Datum','Tip','Opis','Iznos']].dropna()
    df['Datum']=pd.to_datetime(df['Datum'],dayfirst=True,errors='coerce')
    df=df[df['Datum'].notna()].copy()
    df['Iznos']=(df['Iznos'].str.replace(r'[^0-9,.\-]','',regex=True)
                             .str.replace('.','',regex=False)
                             .str.replace(',', '.',regex=False)
                             .astype(float))
    df['CATEGORY']=df.apply(_base_cat,axis=1)
    df.loc[df.CATEGORY=='SAVINGS','Iznos']=df.loc[df.CATEGORY=='SAVINGS','Iznos'].abs()
    df['VENDOR'] = df['Opis'].apply(vendor)
    df['ADV_CAT']=df.apply(_adv_cat,axis=1)
    df['MONTH']=df.Datum.dt.to_period('M')
    df['YEAR_MONTH']=df['MONTH']; df['DAY']=df.Datum.dt.dayofweek
    df['HOUR']=df.Datum.dt.hour
    return df

# ─── NEEDS/WANTS tagging ───
def needs_wants(r:pd.Series)->str:
    if r['CATEGORY'] in ('SAVINGS','STOCKS/CRYPTO'): return 'TRANSFER'
    return CURRENT_TAGS.get(r['VENDOR'], 'WANTS')

# ─── core math ───
def project_savings(avg_save:float, months:int=12)->list[float]:
    return [round(avg_save*m,2) for m in range(1,months+1)]

def summary(df:pd.DataFrame):
    m=df['MONTH'].nunique() or 1
    s=lambda c:df[df.CATEGORY==c]['Iznos'].sum()
    income, spend, saves, stocks = s('INCOME'), s('SPENDING'), s('SAVINGS'), abs(s('STOCKS/CRYPTO'))
    ai, asp, asv, ast = income/m, spend/m, saves/m, stocks/m
    net=[0]; [net.append(net[-1]+ai-abs(asp)+asv+ast) for _ in range(12)]
    save_proj=project_savings(asv,12)
    return m, net, save_proj, asv, ai, asp, ast

# ─── plotting ───
def safe(fn):                # decorator
    def wrap(*a,**k):
        try:fn(*a,**k)
        except Exception as e: logging.warning('%s failed: %s',fn.__name__,e)
    return wrap

@safe
def plot_totals(folder,m,ai,asp,asv,ast):
    labels=['Spend','Save','Stocks','Income']
    vals=[abs(asp)*m,asv*m,ast*m,ai*m]
    plt.figure(figsize=(8,4))
    bars=plt.bar(labels,vals,color=['#e74c3c','#27ae60','#8e44ad','#3498db'])
    for b,v in zip(bars,vals): plt.text(b.get_x()+b.get_width()/2,v,fmt(v),
                                        ha='center',va='bottom',fontsize=9)
    plt.title('Totals by Category'); plt.ylabel('RSD')
    plt.tight_layout(); plt.savefig(f'{folder}/totals.png'); plt.close()

TOP_COLORS=cycle(['#e74c3c','#f1c40f','#27ae60'])
@safe
def plot_vendors(folder,df):
    top=(df[df.Iznos<0].groupby('VENDOR')['Iznos']
         .sum().abs().sort_values(ascending=False).head(10))
    colors=[next(TOP_COLORS) if i<3 else '#2980b9' for i in range(len(top))]
    plt.figure(figsize=(10,6))
    bars=plt.bar(top.index,top.values,color=colors)
    for b,v in zip(bars,top.values):
        plt.text(b.get_x()+b.get_width()/2,v,fmt(v),ha='center',va='bottom',fontsize=9)
    plt.title('Top Vendor Spend'); plt.ylabel('RSD'); plt.xticks(rotation=45)
    plt.tight_layout(); plt.savefig(f'{folder}/vendors_top.png'); plt.close()

@safe
def plot_weekday(folder,df):
    wk=df[df.Iznos<0].groupby('DAY')['Iznos'].sum()
    plt.figure(figsize=(8,4)); wk.plot(kind='bar',color='#c0392b')
    plt.title('Spending by Weekday'); plt.ylabel('RSD')
    plt.xticks(range(7),['Mon','Tue','Wed','Thu','Fri','Sat','Sun'])
    plt.tight_layout(); plt.savefig(f'{folder}/weekday_spend.png'); plt.close()

@safe
def plot_hourly(folder,df):
    hr=df[df.Iznos<0].groupby('HOUR')['Iznos'].sum()
    if hr.sum()==0 or hr.nunique()<=1: return
    hr=hr.reindex(range(24),fill_value=0)
    plt.figure(figsize=(14,4)); hr.plot(kind='bar',color='#9b59b6')
    plt.grid(axis='y',alpha=.3); plt.title('Spending by Hour (0-23)')
    plt.xlabel('Hour'); plt.ylabel('RSD')
    plt.tight_layout(); plt.savefig(f'{folder}/hourly_spend.png'); plt.close()

@safe
def plot_monthly_trends(folder,df):
    m=(df.groupby(['YEAR_MONTH','ADV_CAT'])['Iznos']
         .sum().unstack().fillna(0))
    m.plot(kind='bar',stacked=True,figsize=(12,6))
    plt.title('Monthly Cash-flow by Advanced Category'); plt.ylabel('RSD')
    plt.xticks(rotation=45)
    plt.tight_layout(); plt.savefig(f'{folder}/monthly_trends.png'); plt.close()

@safe
def plot_rolling(folder,df):
    daily=(df[df.Iznos<0]
             .set_index('Datum').resample('D')['Iznos']
             .sum().abs())
    win=30 if len(daily)>=30 else 7
    daily.rolling(win).sum().plot(figsize=(12,5))
    plt.title(f'{win}-Day Rolling Spend'); plt.ylabel('RSD')
    plt.tight_layout(); plt.savefig(f'{folder}/rolling{win}_spend.png'); plt.close()

@safe
def plot_monthly_net(folder,df):
    netm=df.groupby('YEAR_MONTH')['Iznos'].sum()
    netm.plot(marker='o',figsize=(10,4))
    plt.axhline(0,color='gray',ls='--')
    plt.title('Monthly Net Δ'); plt.ylabel('RSD')
    plt.tight_layout(); plt.savefig(f'{folder}/monthly_net.png'); plt.close()

@safe
def plot_needs_wants(folder,df):
    s=(df[(df.Iznos<0)&(df.NEEDS_WANTS!='TRANSFER')]
         .groupby('NEEDS_WANTS')['Iznos'].sum().abs())
    s=s.reindex(['NEEDS','WANTS']).fillna(0)
    plt.figure(figsize=(7,5))
    bars=plt.bar(s.index,s.values,color=['#2ecc71','#e67e22'])
    for b,v in zip(bars,s.values):
        plt.text(b.get_x()+b.get_width()/2,v,fmt(v),ha='center',va='bottom',fontsize=10)
    plt.title('NEEDS vs WANTS'); plt.ylabel('RSD')
    plt.tight_layout(); plt.savefig(f'{folder}/needs_wants.png'); plt.close()

@safe
def plot_projected_net(folder,net):
    xs=list(range(len(net))); ys=net
    plt.figure(figsize=(10,5))
    plt.plot(xs,ys,marker='o',color='#1abc9c')
    plt.title('Projected Net Worth'); plt.xlabel('Months'); plt.ylabel('RSD')
    plt.grid(alpha=.3)
    plt.tight_layout(); plt.savefig(f'{folder}/projected_net.png'); plt.close()

@safe
def plot_projected_savings(folder,save_proj):
    xs=list(range(1,len(save_proj)+1))
    plt.figure(figsize=(10,5))
    plt.plot(xs,save_proj,marker='o',color='#e67e22')
    plt.title('Projected Savings Only (12 mo)')
    plt.xlabel('Months'); plt.ylabel('RSD')
    plt.grid(alpha=.3)
    plt.tight_layout(); plt.savefig(f'{folder}/projected_savings.png'); plt.close()

# ─── CLI ───
P=argparse.ArgumentParser(
    description='Balkan Schizo Finance – Wallet Taser',
    formatter_class=argparse.RawDescriptionHelpFormatter,
    epilog=textwrap.dedent('''
      Examples:
        python3 finance.py
        python3 finance.py -f bank.xlsx --fx 118 --sqlite --debug'''))
P.add_argument('-f','--file',help='bank statement (.xls/.xlsx)')
P.add_argument('--fx',type=float,help=f'RSD→EUR (default {DEF_FX})')
P.add_argument('--sqlite',action='store_true',help='append rows to wallettaser.db')
P.add_argument('--debug',action='store_true',help='verbose logging')
P.add_argument('--user',default=DEFAULT_USER,help='user id for tagging scope')
P.add_argument(
    '--tag',
    action='append',
    default=[],
    help='predefine vendor tags as VENDOR=CLASS (NEEDS/WANTS)'
)

# ─── main ───
def main():
    a=P.parse_args(); setup_logging(a.debug)
    path=a.file or (logging.info('Using statement %s',latest_xls()) or latest_xls())
    fx=a.fx or float(input(f'RSD→EUR rate (Enter for {DEF_FX}): ') or DEF_FX)

    df=load_clean(path)
    repo = VendorTagRepository()
    repo.migrate_from_csv(user_id=a.user)
    decisions = {}
    for item in a.tag:
        if '=' in item:
            vendor, cls = item.split('=', 1)
            decisions[vendor.strip().upper()] = cls.strip().upper()
    global CURRENT_TAGS
    CURRENT_TAGS = apply_tagging_decisions(
        df,
        repo,
        a.user,
        decisions=decisions
    )
    df['NEEDS_WANTS']=df.apply(needs_wants,axis=1)
    df['USER_ID']=a.user

    months, net, save_proj, asv, ai, asp, ast = summary(df)
    folder=f'finance_report_{datetime.now():%Y%m%d_%H%M%S}'; os.makedirs(folder,exist_ok=True)

    # plots
    plot_totals(folder,months,ai,asp,asv,ast)
    plot_vendors(folder,df); plot_needs_wants(folder,df); plot_weekday(folder,df)
    plot_hourly(folder,df); plot_monthly_trends(folder,df)
    plot_rolling(folder,df); plot_monthly_net(folder,df)
    plot_projected_net(folder,net); plot_projected_savings(folder,save_proj)

    df.to_csv(f'{folder}/full_enriched_dataset.csv',index=False)
    if a.sqlite:
        with sqlite3.connect(DB_PATH) as con:
            df.to_sql('transactions',con,if_exists='append',index=False)

    # console summary
    today=pd.Timestamp.today().normalize()
    last7=abs(df[(df.Datum>=today-timedelta(days=7)) & (df.Iznos<0)]['Iznos'].sum())
    prev7=abs(df[(df.Datum>=today-timedelta(days=14)) & (df.Datum<today-timedelta(days=7)) & (df.Iznos<0)]['Iznos'].sum())
    delta=last7-prev7
    total_spend=df[df.Iznos<0]['Iznos'].abs().sum()
    vampires=(df[df.Iznos<0].groupby('VENDOR')['Iznos'].sum().abs()/total_spend)\
             .loc[lambda s:s>0.05].index.tolist()

    print(f'\nMonths: {months} | Avg save: {fmt(asv)} RSD'
          f' | Net 12 mo: {fmt(net[-1])} RSD ({fmt(net[-1]/fx)} €)')
    print(f'Last 7-day spend: {fmt(last7)} RSD (Δ {fmt(delta)} vs prev 7 d)')
    if vampires: print('Consider cutting:', ', '.join(vampires))
    print('Projected pure savings (12 mo):')
    for i,v in enumerate(save_proj,1):
        print(f'  +{i:02d} mo → {fmt(v)} RSD ({fmt(v/fx)} €)')
    print('Charts + CSV saved →', folder)

if __name__ == '__main__':
    main()
