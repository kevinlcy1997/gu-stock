"""Low-frequency GU sale listing snapshot.

The retailer may change its page schema. This deliberately emits no fabricated
stock when store inventory is not present in public page data.
"""
import json, re
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

URL="https://m.gu-global.com/hk/home/c_mobile/women-saleitems"
OUT=Path(__file__).parents[1]/"data/products.json"
req=Request(URL,headers={"User-Agent":"Mozilla/5.0 (compatible; GU-HK-Stock-Finder/1.0; low-frequency research dashboard)","Accept-Language":"zh-HK,zh;q=0.9,en;q=0.7"})
html=urlopen(req,timeout=30).read().decode("utf-8","replace")
products=[]

# Prefer structured Product JSON-LD when the storefront exposes it.
for raw in re.findall(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',html,re.I|re.S):
    try: nodes=json.loads(raw); nodes=nodes if isinstance(nodes,list) else [nodes]
    except Exception: continue
    for node in nodes:
        if not isinstance(node,dict) or node.get("@type")!="Product": continue
        offer=node.get("offers") or {}; offer=offer[0] if isinstance(offer,list) and offer else offer
        try: price=float(offer.get("price"))
        except Exception: continue
        url=node.get("url") or URL
        products.append({"id":str(node.get("sku") or node.get("productID") or len(products)+1),"name":node.get("name") or "GU 減價商品","price":price,"originalPrice":None,"image":(node.get("image") or [None])[0] if isinstance(node.get("image"),list) else node.get("image"),"url":url if url.startswith("http") else "https://m.gu-global.com"+url,"stock":{}})

payload={"updatedAt":datetime.now(timezone.utc).isoformat(timespec="seconds"),"source":URL,"products":list({p["id"]:p for p in products}.values())}
if not payload["products"] and OUT.exists():
    old=json.loads(OUT.read_text()); payload["products"]=old.get("products",[]); payload["warning"]="GU page contained no supported structured product data; retained previous snapshot."
OUT.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+"\n")
