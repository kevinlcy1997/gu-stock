"""Render GU HK's dynamic sale listing and publish a conservative snapshot."""
import hashlib, json, re, time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from selenium import webdriver
from selenium.webdriver.chrome.options import Options

URLS=[
 "https://www.gu-global.com/hk/zh_HK/c/women-saleitems.html",
 "https://m.gu-global.com/hk/home/c_mobile/women-saleitems",
 "https://www.gu-global.com/hk/zh_HK/c/women-saleitems-tops.html",
 "https://www.gu-global.com/hk/zh_HK/c/women-saleitems-bottoms.html",
]
OUT=Path(__file__).parents[1]/"data/products.json"
old=json.loads(OUT.read_text()) if OUT.exists() else {"products":[]}
options=Options()
for flag in ("--headless=new","--no-sandbox","--disable-dev-shm-usage","--disable-http2","--window-size=1440,1800","--lang=zh-HK"):
    options.add_argument(flag)
options.set_capability("goog:loggingPrefs",{"performance":"ALL"})
driver=webdriver.Chrome(options=options)
rows=[]; diagnostics=[]; network=[]; page_meta=[]
try:
  for source in URLS:
    try:
      driver.get(source); time.sleep(8)
      for _ in range(8):
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight)"); time.sleep(1)
      html=driver.page_source
      body_text=driver.execute_script("return document.body ? document.body.innerText : ''") or ""
      srcs=re.findall(r'<script[^>]+src=["\\\']([^"\\\']+)',html,re.I)
      inline=[]
      for m in re.finditer(r'<script(?![^>]+src=)[^>]*>(.*?)</script>',html,re.I|re.S):
        s=m.group(1)
        if re.search(r'api|product|search|stock|inventory|catalog|category',s,re.I):
          inline.append(re.sub(r"\\s+"," ",s)[:2200])
          if len(inline)>=8: break
      page_meta.append({"url":driver.current_url,"bodyText":body_text[:5000],"scripts":srcs[:80],"inlineHints":inline})
      cards=driver.execute_script(r"""
        const seen=new Set(), out=[];
        for (const a of document.querySelectorAll('a[href]')) {
          let box=a.closest('li,article,[class*="product"],[class*="item"]')||a.parentElement||a;
          for(let i=0;i<4 && box && !/HK\\$\\s*\\d/i.test(box.innerText||'');i++) box=box.parentElement;
          const text=(box?.innerText||a.innerText||'').trim();
          if(!/HK\\$\\s*\\d/i.test(text)) continue;
          const img=box?.querySelector('img')||a.querySelector('img');
          const key=a.href+'|'+text.slice(0,80);
          if(seen.has(key)) continue; seen.add(key);
          out.push({href:a.href,text,image:img?(img.currentSrc||img.src||img.getAttribute('data-src')):null});
        }
        return out;
      """)
      diagnostics.append({"requested":source,"finalUrl":driver.current_url,"title":driver.title,
        "bodyChars":len(driver.page_source),"candidateLinks":len(cards)})
      rows.extend(cards)
      if len(cards)>=5: break
    except Exception as e:
      diagnostics.append({"requested":source,"error":str(e)[:240]})
finally:
  driver.quit()

products={}
for row in rows:
  text=re.sub(r"\s+"," ",row.get("text") or "").strip()
  prices=[float(x.replace(",","")) for x in re.findall(r"HK\$\s*([0-9][0-9,]*(?:\.\d+)?)",text,re.I)]
  if not prices: continue
  href=row.get("href") or ""
  q=parse_qs(urlparse(href).query)
  pid=(q.get("productCode") or q.get("productcode") or [None])[0]
  if not pid:
    m=re.search(r"(?:product|item)[^0-9]*([0-9]{5,})",href,re.I); pid=m.group(1) if m else hashlib.sha1(href.encode()).hexdigest()[:12]
  bits=[x.strip() for x in re.split(r"[\n\r]+",row.get("text") or "") if x.strip()]
  name=next((x for x in bits if "HK$" not in x and len(x)>2 and x.upper() not in {"SALE","WOMEN"}),"GU 減價商品")
  products[str(pid)]={"id":str(pid),"name":name[:160],"price":min(prices),
    "originalPrice":max(prices) if max(prices)>min(prices) else None,
    "image":row.get("image"),"url":href,"stock":{}}

payload={"updatedAt":datetime.now(timezone.utc).isoformat(timespec="seconds"),"source":URLS[0],
 "products":list(products.values()),"diagnostics":diagnostics,"network":network[:80],"pageMeta":page_meta}
if not products:
  payload["products"]=old.get("products",[])
  payload["warning"]="Rendered pages exposed no recognised product cards; retained previous snapshot."
OUT.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+"\n")
