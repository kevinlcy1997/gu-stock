"""Render GU HK's women's sale listing with Playwright Firefox."""

from __future__ import annotations

import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

URL = "https://www.gu-global.com/hk/zh_HK/c/women-saleitems.html"
OUT = Path(__file__).parents[1] / "data/products.json"
old = json.loads(OUT.read_text()) if OUT.exists() else {"products": []}
diagnostics: list[dict] = []
rows: list[dict] = []

try:
    with sync_playwright() as playwright:
        browser = playwright.firefox.launch(headless=True)
        page = browser.new_page(
            viewport={"width": 1440, "height": 1800},
            locale="zh-HK",
            timezone_id="Asia/Hong_Kong",
            user_agent=(
                "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:141.0) "
                "Gecko/20100101 Firefox/141.0"
            ),
        )

        response = page.goto(URL, wait_until="domcontentloaded", timeout=90_000)
        page.wait_for_timeout(8_000)

        previous = -1
        stable_rounds = 0
        counts: list[int] = []
        for _ in range(30):
            count = page.locator('a[href*="productCode=" i]').count()
            counts.append(count)
            stable_rounds = stable_rounds + 1 if count == previous else 0
            previous = count
            if count > 0 and stable_rounds >= 4:
                break
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(1_200)

        rows = page.evaluate(
            r"""
            () => {
              const out = [];
              const seen = new Set();

              for (const a of document.querySelectorAll('a[href]')) {
                let url;
                try { url = new URL(a.href, location.href); } catch { continue; }

                let productCode = "";
                for (const [key, value] of url.searchParams.entries()) {
                  if (key.toLowerCase() === "productcode") productCode = value;
                }
                if (!productCode || seen.has(productCode)) continue;

                let box = a.closest('li, article, [class*="product"], [class*="item"]')
                  || a.parentElement || a;
                for (let i = 0; i < 6 && box && !/HK\$\s*\d/i.test(box.innerText || ""); i++) {
                  box = box.parentElement;
                }

                const text = (box?.innerText || a.innerText || "").trim();
                if (!/HK\$\s*\d/i.test(text)) continue;

                const image = box?.querySelector("img") || a.querySelector("img");
                const imageUrl = image
                  ? (image.currentSrc || image.src || image.dataset.src
                    || image.dataset.original || image.getAttribute("data-lazy-src"))
                  : null;

                seen.add(productCode);
                out.push({
                  productCode,
                  href: url.href,
                  text,
                  image: imageUrl || null,
                });
              }
              return out;
            }
            """
        )

        diagnostics.append(
            {
                "engine": "playwright-firefox",
                "status": response.status if response else None,
                "finalUrl": page.url,
                "title": page.title(),
                "productLinkCounts": counts,
                "candidateProducts": len(rows),
                "bodyPreview": page.locator("body").inner_text()[:1200],
            }
        )
        browser.close()
except PlaywrightTimeoutError as exc:
    diagnostics.append({"engine": "playwright-firefox", "error": f"timeout: {exc}"[:500]})
except Exception as exc:
    diagnostics.append(
        {"engine": "playwright-firefox", "error": f"{type(exc).__name__}: {exc}"[:500]}
    )

products: dict[str, dict] = {}
for row in rows:
    text = re.sub(r"\s+", " ", row.get("text") or "").strip()
    prices = [
        float(value.replace(",", ""))
        for value in re.findall(r"HK\$\s*([0-9][0-9,]*(?:\.\d+)?)", text, re.I)
    ]
    if not prices:
        continue

    product_code = str(row.get("productCode") or "").strip()
    href = row.get("href") or ""
    if not product_code:
        query = parse_qs(urlparse(href).query)
        product_code = (query.get("productCode") or [""])[0]
    if not product_code:
        continue

    lines = [
        re.sub(r"\s+", " ", line).strip()
        for line in re.split(r"[\n\r]+", row.get("text") or "")
        if line.strip()
    ]
    item_line = next(
        (
            match
            for line in lines
            if (match := re.match(r"^(.+?)\\s+(\\d{6})$", line))
        ),
        None,
    )
    item_no = item_line.group(2) if item_line else None
    name = item_line.group(1) if item_line else next(
        (
            line
            for line in lines
            if len(line) > 2
            and not re.search(
                r"HK\\$|^(?:SALE|WOMEN|NEW|LIMITED|GU)$|"
                r"^(?:女裝|男裝|男女通用)[,，]|商品編號|Item\\s*No|^\\d{5,}$",
                line,
                re.I,
            )
        ),
        "GU 減價商品",
    )

    sale_price = min(prices)
    original_price = max(prices) if max(prices) > sale_price else None
    products[product_code] = {
        "id": item_no or product_code,
        "productCode": product_code,
        "itemNo": item_no,
        "name": name[:160],
        "price": sale_price,
        "originalPrice": original_price,
        "image": row.get("image") or (
            f"https://www.gu-global.com/hk/hmall/test/{product_code}/main/first/561/1.jpg"
        ),
        "url": href,
        "stock": {},
    }

price_tiers = Counter(
    str(int(product["price"]) if product["price"].is_integer() else product["price"])
    for product in products.values()
)
payload = {
    "updatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    "source": URL,
    "products": list(products.values()),
    "priceTiers": dict(sorted(price_tiers.items(), key=lambda item: float(item[0]))),
    "diagnostics": diagnostics,
}

if not products:
    payload["products"] = old.get("products", [])
    payload["priceTiers"] = old.get("priceTiers", {})
    payload["warning"] = (
        "Playwright Firefox exposed no recognised GU product cards; "
        "retained previous snapshot."
    )

OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
print(f"products={len(products)}")
print(f"priceTiers={payload['priceTiers']}")
for diagnostic in diagnostics:
    print(json.dumps(diagnostic, ensure_ascii=False))

if not products:
    raise SystemExit(1)
