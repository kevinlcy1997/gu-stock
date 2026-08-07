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
for flag in ("--headless=new","--no-sandbox","--disable-dev-shm-usage","--window-size=1440,1800","--lang=zh-HK"):
    options.add_argument(flag)
options.set_capability("goog:loggingPrefs",{"performance":"ALL"})
driver=webdriver.Chrome(options=options)
rows=[]; diagnostics=[]; network=[]
try:
  for source in URLS:
    try:
      driver.get(source); time.sleep(8)
      for _ in range(8):
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight)"); time.sleep(1)
      cards=driver.execute_script(r"""
        const good = h => /product-detail|productcode|\/product\/|\/products\//i.test(h);
        return [...document.querySelectorAll('a[href]')].filter(a=>good(a.href)).map(a=>{
          const box=a.closest('li,article,[class*="product"],[class*="item"]')||a;
          const img=box.querySelector('img');
          return {href:a.href,text:(box.innerText||a.innerText||'').trim(),
            image:img?(img.currentSrc||img.src||img.getAttribute('data-src')):null};
        });
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
 "products":list(products.values()),"diagnostics":diagnostics,"network":network[:80]}
if not products:
  payload["products"]=old.get("products",[])
  payload["warning"]="Rendered pages exposed no recognised product cards; retained previous snapshot."
OUT.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+"\n")
