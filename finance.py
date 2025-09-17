#!/usr/bin/env python3
# ─────────────────────────────────────────────────────────────
#  #  (full report  + 12-month savings projection)
# ─────────────────────────────────────────────────────────────
"""
$ python3 finance.py
$ python3 finance.py -f bank.xlsx --fx 118 --sqlite --debug
Stores a manifest containing:
  totals.png/json, vendors_top.png/json, needs_wants.png/json,
  weekday_spend.png/json, hourly_spend.png/json (if data present),
  monthly_trends.png/json, rolling30/7_spend.png/json,
  monthly_net.png/json, projected_net.png/json,
  projected_savings.png/json,
  full_enriched_dataset.csv  (+ transactions.db if --sqlite)
"""
from __future__ import annotations
import argparse, csv, glob, logging, os, re, sqlite3, sys, textwrap
from datetime import datetime, timedelta
from io import BytesIO
from itertools import cycle
from typing import Dict

import matplotlib.pyplot as plt
import pandas as pd

from storage import Storage, get_storage

TAG_FILE = 'vendor_tags.csv'           # persistent NEEDS/WANTS map
DEF_FX   = 117.0                       # default RSD → EUR

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
try:
    with open(TAG_FILE, newline='') as f:
        TAGS = {r['VENDOR']: r['CLASS'] for r in csv.DictReader(f)}
except FileNotFoundError: TAGS = {}

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
def tag_new_vendors(df:pd.DataFrame)->None:
    global TAGS
    freq=(df['VENDOR'].value_counts()
          .loc[lambda s:s>=3].index.difference(TAGS))
    if not freq.empty:
        print('\n► Tag vendors: NEEDS (n) / WANTS (w)')
    for v in freq:
        while True:
            ans=input(f'  {v}: n/w? ').strip().lower()
            if ans in ('n','w'):
                TAGS[v]='NEEDS' if ans=='n' else 'WANTS'; break
    if freq.any():
        with open(TAG_FILE,'w',newline='') as f:
            w=csv.DictWriter(f,fieldnames=['VENDOR','CLASS'])
            w.writeheader(); [w.writerow({'VENDOR':k,'CLASS':v}) for k,v in TAGS.items()]

def needs_wants(r:pd.Series)->str:
    if r['CATEGORY'] in ('SAVINGS','STOCKS/CRYPTO'): return 'TRANSFER'
    return TAGS.get(r['VENDOR'],'WANTS')

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
        try:
            return fn(*a,**k)
        except Exception as e:
            logging.warning('%s failed: %s',fn.__name__,e)
            return None
    return wrap


def _finalize_plot(fig) -> bytes:
    buf = BytesIO()
    fig.savefig(buf, format='png')
    plt.close(fig)
    buf.seek(0)
    return buf.getvalue()


@safe
def chart_totals(m,ai,asp,asv,ast):
    labels=['Spend','Save','Stocks','Income']
    vals=[abs(asp)*m,asv*m,ast*m,ai*m]
    fig, ax = plt.subplots(figsize=(8,4))
    bars=ax.bar(labels,vals,color=['#e74c3c','#27ae60','#8e44ad','#3498db'])
    for b,v in zip(bars,vals):
        ax.text(b.get_x()+b.get_width()/2,v,fmt(v),ha='center',va='bottom',fontsize=9)
    ax.set_title('Totals by Category'); ax.set_ylabel('RSD')
    fig.tight_layout()
    return _finalize_plot(fig), {'labels':labels,'values':[float(v) for v in vals],'months':m}


TOP_COLORS=['#e74c3c','#f1c40f','#27ae60']


@safe
def chart_vendors(df:pd.DataFrame):
    top=(df[df.Iznos<0].groupby('VENDOR')['Iznos']
         .sum().abs().sort_values(ascending=False).head(10))
    if top.empty:
        return None
    palette=cycle(TOP_COLORS)
    colors=[next(palette) if i<len(TOP_COLORS) else '#2980b9' for i in range(len(top))]
    fig, ax = plt.subplots(figsize=(10,6))
    bars=ax.bar(top.index,top.values,color=colors)
    for b,v in zip(bars,top.values):
        ax.text(b.get_x()+b.get_width()/2,v,fmt(v),ha='center',va='bottom',fontsize=9)
    ax.set_title('Top Vendor Spend'); ax.set_ylabel('RSD'); ax.set_xticklabels(top.index,rotation=45)
    fig.tight_layout()
    data={'vendors':list(top.index),'values':[float(v) for v in top.values]}
    return _finalize_plot(fig), data


@safe
def chart_weekday(df:pd.DataFrame):
    wk=df[df.Iznos<0].groupby('DAY')['Iznos'].sum()
    if wk.empty:
        return None
    fig, ax = plt.subplots(figsize=(8,4))
    wk.plot(kind='bar',color='#c0392b',ax=ax)
    ax.set_title('Spending by Weekday'); ax.set_ylabel('RSD')
    ax.set_xticks(range(7))
    ax.set_xticklabels(['Mon','Tue','Wed','Thu','Fri','Sat','Sun'])
    fig.tight_layout()
    data={'days':['Mon','Tue','Wed','Thu','Fri','Sat','Sun'],
          'values':[float(wk.reindex(range(7),fill_value=0).iloc[i]) for i in range(7)]}
    return _finalize_plot(fig), data


@safe
def chart_hourly(df:pd.DataFrame):
    hr=df[df.Iznos<0].groupby('HOUR')['Iznos'].sum()
    if hr.sum()==0 or hr.nunique()<=1:
        return None
    hr=hr.reindex(range(24),fill_value=0)
    fig, ax = plt.subplots(figsize=(14,4))
    hr.plot(kind='bar',color='#9b59b6',ax=ax)
    ax.grid(axis='y',alpha=.3); ax.set_title('Spending by Hour (0-23)')
    ax.set_xlabel('Hour'); ax.set_ylabel('RSD')
    fig.tight_layout()
    data={'hours':list(range(24)),'values':[float(v) for v in hr.values]}
    return _finalize_plot(fig), data


@safe
def chart_monthly_trends(df:pd.DataFrame):
    m=(df.groupby(['YEAR_MONTH','ADV_CAT'])['Iznos']
         .sum().unstack().fillna(0))
    if m.empty:
        return None
    fig, ax = plt.subplots(figsize=(12,6))
    m.plot(kind='bar',stacked=True,ax=ax)
    ax.set_title('Monthly Cash-flow by Advanced Category'); ax.set_ylabel('RSD')
    ax.set_xticklabels([str(i) for i in m.index],rotation=45)
    fig.tight_layout()
    data={'months':[str(i) for i in m.index],
          'series':{col:[float(v) for v in m[col].tolist()] for col in m.columns}}
    return _finalize_plot(fig), data


@safe
def chart_rolling(df:pd.DataFrame):
    daily=(df[df.Iznos<0]
             .set_index('Datum').resample('D')['Iznos']
             .sum().abs())
    if daily.empty:
        return None
    win=30 if len(daily)>=30 else 7
    rolled=daily.rolling(win).sum()
    fig, ax = plt.subplots(figsize=(12,5))
    rolled.plot(ax=ax)
    ax.set_title(f'{win}-Day Rolling Spend'); ax.set_ylabel('RSD')
    fig.tight_layout()
    data={'window':win,
          'series':[{'date':d.strftime('%Y-%m-%d'),'value':float(v)} for d,v in rolled.dropna().items()]}
    return _finalize_plot(fig), data


@safe
def chart_monthly_net(df:pd.DataFrame):
    netm=df.groupby('YEAR_MONTH')['Iznos'].sum()
    if netm.empty:
        return None
    fig, ax = plt.subplots(figsize=(10,4))
    netm.plot(marker='o',ax=ax)
    ax.axhline(0,color='gray',ls='--')
    ax.set_title('Monthly Net Δ'); ax.set_ylabel('RSD')
    fig.tight_layout()
    data={'months':[str(i) for i in netm.index],'values':[float(v) for v in netm.values]}
    return _finalize_plot(fig), data


@safe
def chart_needs_wants(df:pd.DataFrame):
    s=(df[(df.Iznos<0)&(df.NEEDS_WANTS!='TRANSFER')]
         .groupby('NEEDS_WANTS')['Iznos'].sum().abs())
    s=s.reindex(['NEEDS','WANTS']).fillna(0)
    if s.sum()==0:
        return None
    fig, ax = plt.subplots(figsize=(7,5))
    bars=ax.bar(s.index,s.values,color=['#2ecc71','#e67e22'])
    for b,v in zip(bars,s.values):
        ax.text(b.get_x()+b.get_width()/2,v,fmt(v),ha='center',va='bottom',fontsize=10)
    ax.set_title('NEEDS vs WANTS'); ax.set_ylabel('RSD')
    fig.tight_layout()
    data={'categories':list(s.index),'values':[float(v) for v in s.values]}
    return _finalize_plot(fig), data


@safe
def chart_projected_net(net:list[float]):
    if not net:
        return None
    xs=list(range(len(net))); ys=net
    fig, ax = plt.subplots(figsize=(10,5))
    ax.plot(xs,ys,marker='o',color='#1abc9c')
    ax.set_title('Projected Net Worth'); ax.set_xlabel('Months'); ax.set_ylabel('RSD')
    ax.grid(alpha=.3)
    fig.tight_layout()
    data={'months':xs,'values':[float(v) for v in ys]}
    return _finalize_plot(fig), data


@safe
def chart_projected_savings(save_proj:list[float]):
    if not save_proj:
        return None
    xs=list(range(1,len(save_proj)+1))
    fig, ax = plt.subplots(figsize=(10,5))
    ax.plot(xs,save_proj,marker='o',color='#e67e22')
    ax.set_title('Projected Savings Only (12 mo)')
    ax.set_xlabel('Months'); ax.set_ylabel('RSD')
    ax.grid(alpha=.3)
    fig.tight_layout()
    data={'months':xs,'values':[float(v) for v in save_proj]}
    return _finalize_plot(fig), data

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
P.add_argument('--sqlite',action='store_true',help='append rows to transactions.db')
P.add_argument('--user',default=os.getenv('WALLETTASER_USER_ID','default'),
               help='user identifier for storage segregation')
P.add_argument('--storage-backend',choices=['local','s3'],
               help='override storage backend (default env WALLETTASER_STORAGE_BACKEND)')
P.add_argument('--debug',action='store_true',help='verbose logging')

# ─── main ───
def main():
    a=P.parse_args(); setup_logging(a.debug)
    path=a.file or (logging.info('Using statement %s',latest_xls()) or latest_xls())
    fx=a.fx or float(input(f'RSD→EUR rate (Enter for {DEF_FX}): ') or DEF_FX)

    df=load_clean(path)
    tag_new_vendors(df)
    df['NEEDS_WANTS']=df.apply(needs_wants,axis=1)

    months, net, save_proj, asv, ai, asp, ast = summary(df)

    storage:Storage=get_storage(a.storage_backend)
    user_id=a.user
    metadata={'source_file':os.path.basename(path),'fx_rate':fx,
              'generated_at':f'{datetime.now():%Y-%m-%dT%H:%M:%S}'}
    result_id=storage.start_result(user_id,metadata=metadata)

    chart_index:Dict[str,Dict[str,str]]={}

    def store_chart(name:str, generator):
        res=generator()
        if not res:
            return
        image_bytes, data=res
        img_uri=storage.save_artifact(user_id,result_id,f'{name}.png',image_bytes,'image/png',
                                      metadata={'type':'chart','name':name})
        data_uri=storage.save_json(user_id,result_id,f'{name}.json',data,
                                   metadata={'type':'chart-data','name':name})
        chart_index[name]={'image':img_uri,'data':data_uri}

    store_chart('totals',lambda:chart_totals(months,ai,asp,asv,ast))
    store_chart('vendors_top',lambda:chart_vendors(df))
    store_chart('needs_wants',lambda:chart_needs_wants(df))
    store_chart('weekday_spend',lambda:chart_weekday(df))
    store_chart('hourly_spend',lambda:chart_hourly(df))
    store_chart('monthly_trends',lambda:chart_monthly_trends(df))
    store_chart('rolling_spend',lambda:chart_rolling(df))
    store_chart('monthly_net',lambda:chart_monthly_net(df))
    store_chart('projected_net',lambda:chart_projected_net(net))
    store_chart('projected_savings',lambda:chart_projected_savings(save_proj))

    csv_bytes=df.to_csv(index=False).encode('utf-8')
    csv_uri=storage.save_artifact(user_id,result_id,'full_enriched_dataset.csv',csv_bytes,
                                  'text/csv',metadata={'rows':len(df)})

    if a.sqlite:
        with sqlite3.connect('transactions.db') as con:
            df.to_sql('tx',con,if_exists='append',index=False)

    manifest={'result_id':result_id,'user_id':user_id,'csv_uri':csv_uri,
              'charts':chart_index,'generated_at':metadata['generated_at']}
    storage.save_json(user_id,result_id,'manifest.json',manifest,metadata={'type':'manifest'})

    summary_payload={'months':months,'avg_savings':asv,'avg_income':ai,'avg_spend':asp,
                     'avg_stocks':ast,'projected_net_12m':net[-1] if net else 0,
                     'csv_uri':csv_uri,'charts':chart_index}
    storage.finalize_result(result_id,summary_payload)
    storage.enforce_retention(user_id)

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
    print('Result stored →', result_id)
    print('CSV URI →', csv_uri)
    if chart_index:
        print('Charts manifest:')
        for name,info in chart_index.items():
            print(f'  {name}: image={info["image"]} data={info["data"]}')

if __name__ == '__main__':
    main()
