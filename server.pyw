#!/usr/bin/env python3
import csv, json, os, re, threading, time, uuid, urllib.request
from collections import Counter, defaultdict
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

ROOT = Path(__file__).resolve().parent
WEB = ROOT / "app"
UPLOADS = ROOT / "_uploads"
EXPORTS = ROOT / "_exports"
UPLOADS.mkdir(exist_ok=True)
EXPORTS.mkdir(exist_ok=True)
PORT = int(os.getenv("PORT", "8771"))
jobs = {}
lock = threading.Lock()

def load_env():
    p = ROOT / ".env"
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line=line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k,v=line.split("=",1)
        os.environ.setdefault(k.strip(),v.strip().strip('"').strip("'"))
load_env()

ALIASES={
 "sku":["sku","product_sku","item_sku","product_id","item_id","id","asin","external_id"],
 "name":["product_name","name","title","product_title","item_name","product"],
 "brand":["brand","manufacturer","vendor"],
 "category":["category","product_category","type","department"],
 "price":["price","sale_price","unit_price","product_price","price_current","selling_price","mrp"],
 "cost":["cost","unit_cost","cogs","purchase_price"],
 "stock":["stock","inventory","qty","quantity","inventory_qty","stock_qty"],
 "description":["description","product_description","desc","details"],
 "url":["url","product_url","link","product_link"]
}

def setjob(jid, **kw):
    with lock:
        jobs.setdefault(jid,{})
        jobs[jid].update(kw)

def norm(s):
    return re.sub(r'[^a-z0-9_]+','',re.sub(r'[\s\-/]+','_',str(s or '').strip().lower()))

def missing(v):
    return str(v or '').strip().lower() in {'','na','n/a','null','none','nan','missing','-','--'}

def num(v):
    if missing(v):
        return None
    s=re.sub(r'[$£€₹₨,%]','',str(v)).replace(',','').strip()
    try:
        x=float(s)
        return x if x==x else None
    except:
        return None

def titlecase(s):
    return re.sub(r'\s+',' ',str(s or '').strip()).title()

def auto_map(headers):
    nmap={norm(h):h for h in headers}
    out={}
    for k,opts in ALIASES.items():
        out[k]=''
        for o in opts:
            if norm(o) in nmap:
                out[k]=nmap[norm(o)]
                break
    return out

def sniff_text(path):
    raw=path.read_bytes()[:150000]
    enc='utf-8-sig'
    for e in ('utf-8-sig','utf-8','cp1252','latin-1'):
        try:
            raw.decode(e)
            enc=e
            break
        except:
            pass
    sample=raw.decode(enc,errors='replace')
    try:
        delim=csv.Sniffer().sniff(sample,delimiters=',\t;|').delimiter
    except:
        delim=max([',','\t',';','|'],key=lambda d:sample.count(d))
    return enc,delim

def read_rows(path, limit=50000):
    suffix=path.suffix.lower()
    if suffix in ('.xlsx','.xls'):
        import pandas as pd
        df=pd.read_excel(path,nrows=limit)
        df.columns=[str(c) for c in df.columns]
        df=df.fillna('')
        rows=[{str(k):str(v).strip() for k,v in rec.items()} for rec in df.to_dict('records')]
        return list(df.columns),rows,'excel','XLSX'

    enc,delim=sniff_text(path)
    with path.open('r',encoding=enc,errors='replace',newline='') as f:
        rd=csv.reader(f,delimiter=delim)
        try:
            heads=next(rd)
        except StopIteration:
            return [],[],enc,delim
        seen=Counter()
        headers=[]
        for i,h in enumerate(heads):
            h=(h or '').strip() or f'column_{i+1}'
            seen[h]+=1
            headers.append(h if seen[h]==1 else f'{h}_{seen[h]}')
        rows=[]
        for r in rd:
            if len(rows)>=limit:
                break
            if len(r)<len(headers):
                r+=['']*(len(headers)-len(r))
            if len(r)>len(headers):
                r=r[:len(headers)]
            rows.append({h:(r[i] or '').strip() for i,h in enumerate(headers)})
    return headers,rows,enc,('TAB' if delim=='\t' else delim)

def local_enrich(row,m):
    name=row.get(m.get('name',''),'').strip()
    brand=row.get(m.get('brand',''),'').strip()
    cat=row.get(m.get('category',''),'').strip()
    if not name:
        return {'seo_title':'','meta_description':'','ai_description':''}
    seo=(f'{brand} | ' if brand else '') + name + (f' – {cat.split(" > ")[-1]}' if cat else '')
    desc=f'{name}{(" by "+brand) if brand else ""}. {("Category: "+cat+". ") if cat else ""}Prepared for consistent e-commerce catalog publishing.'
    return {'seo_title':seo[:65],'meta_description':desc[:155],'ai_description':desc}

def live_ai_enrich(provider,row,m):
    name=row.get(m.get('name',''),'').strip()
    brand=row.get(m.get('brand',''),'').strip()
    cat=row.get(m.get('category',''),'').strip()
    price=row.get(m.get('price',''),'').strip()
    if not name:
        return local_enrich(row,m)
    prompt=f"""Create concise factual e-commerce catalog content.
Product: {name}
Brand: {brand}
Category: {cat}
Price: {price}
Return JSON only:
{{"seo_title":"<=65 chars","meta_description":"<=155 chars","ai_description":"1-2 factual sentences"}}
Never invent specifications."""
    if provider=='openai':
        key=os.getenv('OPENAI_API_KEY','').strip()
        if not key:
            raise RuntimeError('OPENAI_API_KEY not configured')
        body={
            'model':os.getenv('OPENAI_MODEL','gpt-5.6-luna'),
            'input':prompt,
            'text':{'format':{'type':'json_object'}}
        }
        req=urllib.request.Request(
            'https://api.openai.com/v1/responses',
            data=json.dumps(body).encode(),
            headers={'Authorization':f'Bearer {key}','Content-Type':'application/json'},
            method='POST'
        )
        with urllib.request.urlopen(req,timeout=90) as r:
            raw=json.loads(r.read().decode())
        texts=[]
        for it in raw.get('output',[]):
            if it.get('type')=='message':
                for c in it.get('content',[]):
                    if c.get('type') in ('output_text','text') and c.get('text'):
                        texts.append(c['text'])
        return json.loads('\n'.join(texts))
    if provider=='claude':
        key=os.getenv('ANTHROPIC_API_KEY','').strip()
        if not key:
            raise RuntimeError('ANTHROPIC_API_KEY not configured')
        body={
            'model':os.getenv('ANTHROPIC_MODEL','claude-sonnet-4-5'),
            'max_tokens':400,
            'messages':[{'role':'user','content':prompt}]
        }
        req=urllib.request.Request(
            'https://api.anthropic.com/v1/messages',
            data=json.dumps(body).encode(),
            headers={'x-api-key':key,'anthropic-version':'2023-06-01','content-type':'application/json'},
            method='POST'
        )
        with urllib.request.urlopen(req,timeout=90) as r:
            raw=json.loads(r.read().decode())
        txt=''.join(c.get('text','') for c in raw.get('content',[]) if c.get('type')=='text')
        mo=re.search(r'\{.*\}',txt,re.S)
        return json.loads(mo.group(0) if mo else txt)
    return local_enrich(row,m)

def build_summary(rows,m):
    bycat=defaultdict(lambda:{'products':0,'stock':0.0,'price_sum':0.0,'price_n':0})
    cat_h=m.get('category')
    for r in rows:
        cat=(r.get(cat_h,'').strip() if cat_h else '') or 'Uncategorized'
        x=bycat[cat]
        x['products']+=1
        s=num(r.get(m.get('stock',''),''))
        p=num(r.get(m.get('price',''),''))
        if s is not None:
            x['stock']+=s
        if p is not None:
            x['price_sum']+=p
            x['price_n']+=1
    total=max(1,len(rows))
    out=[]
    for k,v in sorted(bycat.items(),key=lambda kv:kv[1]['products'],reverse=True)[:20]:
        out.append({
            'category':k,
            'products':v['products'],
            'pct':round(v['products']/total*100,1),
            'total_stock':round(v['stock'],2),
            'avg_price':round(v['price_sum']/v['price_n'],2) if v['price_n'] else None
        })
    return out

def quality_metrics(rows,headers,m):
    cells=max(1,len(rows)*len(headers))
    miss=sum(1 for r in rows for h in headers if missing(r.get(h,'')))
    seen=set(); dup=0
    for r in rows:
        sig='\x1f'.join(str(r.get(h,'')) for h in headers)
        if sig in seen:
            dup+=1
        else:
            seen.add(sig)
    mapped=sum(1 for v in m.values() if v)
    completeness=100-(miss/cells*100)
    uniqueness=100-(dup/max(1,len(rows))*100)
    mapping_score=mapped/max(1,len(m))*100
    score=round(max(0,min(100,completeness*.55+uniqueness*.25+mapping_score*.20)),1)
    return {'missing_cells':miss,'duplicate_rows':dup,'mapped_fields':mapped,'quality_score':score,'completeness':round(completeness,1)}

def process(jid,path,name,provider):
    try:
        setjob(jid,status='running',stage='Loading vendor data',progress=10,message='Reading file and detecting schema…')
        headers,rows,enc,delim=read_rows(path)
        if not rows:
            raise RuntimeError('No data rows found.')
        original_preview=[dict(r) for r in rows[:20]]
        m=auto_map(headers)
        q_before=quality_metrics(rows,headers,m)

        setjob(jid,stage='Standardizing',progress=28,message='Cleaning text, categories, prices and stock values…')
        changes=0
        for r in rows:
            for h in headers:
                old=str(r[h] or '')
                nv=re.sub(r'\s+',' ',old.strip())
                if nv!=old:
                    r[h]=nv
                    changes+=1
            for k in ('name','brand'):
                h=m.get(k)
                if h and not missing(r[h]):
                    nv=titlecase(r[h])
                    if nv!=r[h]:
                        r[h]=nv
                        changes+=1
            h=m.get('category')
            if h and not missing(r[h]):
                nv=titlecase(re.sub(r'[>/]+',' > ',r[h]))
                if nv!=r[h]:
                    r[h]=nv
                    changes+=1
            for k in ('price','cost','stock'):
                h=m.get(k)
                if h and not missing(r[h]):
                    n=num(r[h])
                    if n is not None:
                        nv=str(round(n,2))
                        if nv!=r[h]:
                            r[h]=nv
                            changes+=1

        setjob(jid,stage='Applying formulas',progress=45,message='Creating calculated catalog fields…')
        for r in rows:
            p=num(r.get(m.get('price',''),''))
            c=num(r.get(m.get('cost',''),''))
            s=num(r.get(m.get('stock',''),''))
            r['stock_status']='Out of stock' if s==0 else ('Low stock' if s is not None and s<10 else ('In stock' if s is not None else 'Unknown'))
            r['margin_pct']=round(((p-c)/p)*100,2) if p not in (None,0) and c is not None else ''

        setjob(jid,stage='Building pivot summary',progress=60,message='Creating category-level Pivot-style summary…')
        pivot=build_summary(rows,m)

        setjob(jid,stage='AI enrichment',progress=72,message=f'Generating content using {provider.title()} mode…')
        for h in ('seo_title','meta_description','ai_description'):
            if h not in headers:
                headers.append(h)
        sample_limit=min(len(rows),50 if provider in ('openai','claude') else len(rows))
        ai_errors=0
        enriched=0
        for i,r in enumerate(rows[:sample_limit]):
            try:
                out=live_ai_enrich(provider,r,m)
            except Exception:
                ai_errors+=1
                out=local_enrich(r,m)
            for k in ('seo_title','meta_description','ai_description'):
                r[k]=str(out.get(k,''))
            enriched+=1
            if i and i%10==0:
                setjob(jid,progress=min(87,72+int((i/max(1,sample_limit))*15)),message=f'Enriched {i:,}/{sample_limit:,} rows…')

        setjob(jid,stage='Preparing exports',progress=91,message='Building cleaned CSV and Excel workbook…')
        final_headers=list(dict.fromkeys(headers+['stock_status','margin_pct']))
        outcsv=EXPORTS/f'{jid}_cleaned_catalog.csv'
        with outcsv.open('w',encoding='utf-8-sig',newline='') as f:
            w=csv.DictWriter(f,fieldnames=final_headers,extrasaction='ignore')
            w.writeheader()
            w.writerows(rows)

        xlsx_name=''
        try:
            import pandas as pd
            xlsx=EXPORTS/f'{jid}_catalog_workbook.xlsx'
            df=pd.DataFrame(rows)
            piv=pd.DataFrame(pivot)
            qa=pd.DataFrame([q_before])
            pipeline=pd.DataFrame([
                {'step':1,'operation':'Load vendor data','status':'Complete'},
                {'step':2,'operation':'Standardize fields','status':'Complete'},
                {'step':3,'operation':'Calculated formula fields','status':'Complete'},
                {'step':4,'operation':'Pivot summary','status':'Complete'},
                {'step':5,'operation':f'Content enrichment ({provider})','status':'Complete'},
                {'step':6,'operation':'Export catalog','status':'Complete'}
            ])
            with pd.ExcelWriter(xlsx,engine='openpyxl') as writer:
                df.to_excel(writer,index=False,sheet_name='Cleaned_Catalog')
                piv.to_excel(writer,index=False,sheet_name='Pivot_Summary')
                qa.to_excel(writer,index=False,sheet_name='Data_Quality')
                pipeline.to_excel(writer,index=False,sheet_name='Pipeline')
            xlsx_name=xlsx.name
        except Exception:
            pass

        q_after=quality_metrics(rows,[h for h in final_headers if h in rows[0]],m)
        result={
            'filename':name,
            'rows':len(rows),
            'columns':len(final_headers),
            'encoding':enc,
            'delimiter':delim,
            'mapping':m,
            'changes':changes,
            'provider':provider,
            'ai_rows':enriched,
            'ai_errors':ai_errors,
            'pivot':pivot,
            'before_preview':original_preview,
            'after_preview':rows[:20],
            'headers':final_headers,
            'csv_file':outcsv.name,
            'xlsx_file':xlsx_name,
            'quality_before':q_before,
            'quality_after':q_after
        }
        setjob(jid,status='complete',stage='Complete',progress=100,message='Catalog automation complete.',result=result)
    except Exception as e:
        setjob(jid,status='error',stage='Error',progress=100,message=str(e),error=str(e))

class H(SimpleHTTPRequestHandler):
    def translate_path(self,path):
        rel=path.split('?',1)[0].lstrip('/') or 'index.html'
        return str(WEB/rel)

    def js(self,obj,status=200):
        b=json.dumps(obj).encode()
        self.send_response(status)
        self.send_header('Content-Type','application/json; charset=utf-8')
        self.send_header('Content-Length',str(len(b)))
        self.send_header('Cache-Control','no-store')
        self.end_headers()
        self.wfile.write(b)

    def do_POST(self):
        if self.path!='/api/upload':
            return self.js({'ok':False,'error':'not found'},404)
        try:
            n=int(self.headers.get('Content-Length','0'))
            name=self.headers.get('X-Filename','catalog.csv')
            provider=self.headers.get('X-Provider','template')
            if n<=0 or n>500*1024*1024:
                raise RuntimeError('Invalid file size.')
            safe=re.sub(r"[^A-Za-z0-9._ -]","_",name)
            jid=uuid.uuid4().hex
            path=UPLOADS/f'{jid}_{safe}'
            setjob(jid,status='uploading',stage='Uploading',progress=2,message='Receiving file…')
            done=0
            with path.open('wb') as f:
                while done<n:
                    ch=self.rfile.read(min(1024*1024,n-done))
                    if not ch:
                        break
                    f.write(ch)
                    done+=len(ch)
                    setjob(jid,progress=min(8,2+int(done/n*6)),message=f'Uploaded {done/1024/1024:.1f} MB…')
            threading.Thread(target=process,args=(jid,path,name,provider),daemon=True).start()
            self.js({'ok':True,'job_id':jid})
        except Exception as e:
            self.js({'ok':False,'error':str(e)},400)

    def do_GET(self):
        if self.path=='/api/health':
            return self.js({'ok':True,'service':'CatalogFlow AI','version':'4.0'})
        m=re.search(r'id=([a-f0-9]+)',self.path)
        if self.path.startswith('/api/status?') and m:
            with lock:
                j=dict(jobs.get(m.group(1),{}))
            if not j:
                return self.js({'ok':False,'error':'Unknown job'},404)
            j.pop('result',None)
            return self.js({'ok':True,'job':j})
        if self.path.startswith('/api/result?') and m:
            with lock:
                j=dict(jobs.get(m.group(1),{}))
            if j.get('status')!='complete':
                return self.js({'ok':False,'error':'not complete'},409)
            return self.js({'ok':True,'result':j['result']})
        if self.path.startswith('/download/'):
            fn=Path(self.path.split('/download/',1)[1]).name
            p=EXPORTS/fn
            if not p.exists():
                return self.send_error(404)
            b=p.read_bytes()
            self.send_response(200)
            self.send_header('Content-Type','application/octet-stream')
            self.send_header('Content-Disposition',f'attachment; filename="{fn}"')
            self.send_header('Content-Length',str(len(b)))
            self.end_headers()
            self.wfile.write(b)
            return
        return super().do_GET()

    def log_message(self,*a):
        pass

def make_server(port):
    for p in range(port,port+30):
        try:
            return ThreadingHTTPServer(('127.0.0.1',p),H),p
        except OSError:
            pass
    raise OSError('No free local port.')

if __name__=='__main__':
    os.chdir(ROOT)
    srv,p=make_server(PORT)
    (ROOT/'.port').write_text(str(p),encoding='utf-8')
    srv.serve_forever()
