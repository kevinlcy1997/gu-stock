"""Refresh GU HK women's sale products and aggregate store inventory by size."""

from __future__ import annotations

import json
import os
import re
import threading
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse

LISTING_URL = "https://www.gu-global.com/hk/zh_HK/c/women-saleitems.html"
DETAIL_API = "https://d.gu-global.com/hk/p/product/detail"
STORE_STOCK_API = "https://d.gu-global.com/hk/p/store/site/stock"
DEFAULT_OUT = Path(__file__).parents[1] / "data/products.json"
OUT = Path(os.environ.get("GU_OUT", DEFAULT_OUT))
WORKERS = max(1, min(int(os.environ.get("GU_STOCK_WORKERS", "12")), 24))
PRODUCT_LIMIT = max(0, int(os.environ.get("GU_PRODUCT_LIMIT", "0")))
USE_EXISTING_SNAPSHOT = os.environ.get("GU_USE_EXISTING_SNAPSHOT") == "1"

SIZE_ORDER = {
    "XXS": 0,
    "XS": 1,
    "S": 2,
    "M": 3,
    "L": 4,
    "XL": 5,
    "XXL": 6,
    "3XL": 7,
    "4XL": 8,
}

_thread_local = threading.local()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def api_session():
    """Return one persistent requests session per worker thread."""
    session = getattr(_thread_local, "session", None)
    if session is not None:
        return session

    import requests
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry

    retry = Retry(
        total=2,
        connect=2,
        read=2,
        status=2,
        backoff_factor=0.6,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET", "POST"}),
        raise_on_status=False,
    )
    session = requests.Session()
    session.mount("https://", HTTPAdapter(max_retries=retry, pool_connections=1, pool_maxsize=1))
    session.headers.update(
        {
            "Accept": "application/json",
            "Accept-Language": "zh-HK,zh;q=0.9,en;q=0.7",
            "Origin": "https://www.gu-global.com",
            "Referer": "https://www.gu-global.com/hk/zh_HK/",
            "User-Agent": (
                "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:141.0) "
                "Gecko/20100101 Firefox/141.0"
            ),
            "langCode": "zh_HK",
        }
    )
    _thread_local.session = session
    return session


def api_json(method: str, url: str, **kwargs) -> dict:
    response = api_session().request(method, url, timeout=(10, 35), **kwargs)
    response.raise_for_status()
    body = response.json()
    if not isinstance(body, dict) or body.get("success") is not True:
        code = body.get("msgCode") if isinstance(body, dict) else "invalid-json"
        message = body.get("msg") if isinstance(body, dict) else type(body).__name__
        raise RuntimeError(f"GU API failed: {code or 'unknown'}: {message or 'no message'}")
    return body


def render_listing() -> tuple[list[dict], list[dict]]:
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
    from playwright.sync_api import sync_playwright

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
            response = page.goto(
                LISTING_URL, wait_until="domcontentloaded", timeout=90_000
            )
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
        diagnostics.append(
            {"engine": "playwright-firefox", "error": f"timeout: {exc}"[:500]}
        )
    except Exception as exc:
        diagnostics.append(
            {
                "engine": "playwright-firefox",
                "error": f"{type(exc).__name__}: {exc}"[:500],
            }
        )
    return rows, diagnostics


def parse_products(rows: list[dict]) -> dict[str, dict]:
    products: dict[str, dict] = {}
    for row in rows:
        text = re.sub(r"\s+", " ", row.get("text") or "").strip()
        prices = [
            float(value.replace(",", ""))
            for value in re.findall(
                r"HK\$\s*([0-9][0-9,]*(?:\.\d+)?)", text, re.I
            )
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
                if (match := re.match(r"^(.+?)\s+(\d{6})$", line))
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
                    r"HK\$|^(?:SALE|WOMEN|NEW|LIMITED|GU)$|"
                    r"^(?:女裝|男裝|男女通用)[,，]|商品編號|Item\s*No|^\d{5,}$",
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
            "image": row.get("image")
            or (
                "https://www.gu-global.com/hk/hmall/test/"
                f"{product_code}/main/first/561/1.jpg"
            ),
            "url": href,
            "stock": {},
            "stockUnits": {},
            "stockStatus": "pending",
        }
    return products


def fetch_detail(product_code: str) -> tuple[str, list[dict]]:
    body = api_json(
        "GET",
        DETAIL_API,
        params={
            "productCode": product_code,
            "distribution": "EXPRESS",
            "type": "DETAIL",
        },
    )
    response_rows = body.get("resp") or []
    if not response_rows:
        raise RuntimeError("GU detail response had no product")
    rows = (response_rows[0].get("spuInfo") or {}).get("rows") or []
    skus: list[dict] = []
    seen: set[str] = set()
    for row in rows:
        sku_code = str(row.get("productId") or "")
        if row.get("enabledFlag") != "Y" or not sku_code or sku_code in seen:
            continue
        seen.add(sku_code)
        skus.append(
            {
                "skuCode": sku_code,
                "color": row.get("styleText") or row.get("style"),
                "size": row.get("sizeText") or row.get("size"),
            }
        )
    if not skus:
        raise RuntimeError("GU detail response had no active SKUs")
    return product_code, skus


def fetch_store_stock(product_code: str, sku_code: str) -> tuple[str, str, list[dict]]:
    body = api_json(
        "POST",
        STORE_STOCK_API,
        json={"state": "", "city": "", "district": "", "skuCode": sku_code},
    )
    stores = body.get("resp")
    if not isinstance(stores, list) or not stores:
        raise RuntimeError("GU store stock response had no stores")
    return product_code, sku_code, stores


def non_negative_int(value) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def size_sort_key(size: str) -> tuple[int, str]:
    normalized = str(size or "其他").strip().upper()
    return SIZE_ORDER.get(normalized, 100), normalized


def enrich_inventory(
    products: list[dict], old_by_code: dict[str, dict]
) -> tuple[list[dict], list[dict], dict]:
    started = time.monotonic()
    detail_errors: dict[str, str] = {}
    stock_error_samples: list[dict] = []
    skus_by_product: dict[str, list[dict]] = {}
    stock_counts: dict[str, Counter] = defaultdict(Counter)
    stock_units: dict[str, Counter] = defaultdict(Counter)
    stock_by_size: dict = defaultdict(
        lambda: defaultdict(
            lambda: defaultdict(
                lambda: {"skuCount": 0, "units": 0, "colors": Counter()}
            )
        )
    )
    completed_skus: Counter = Counter()
    failed_skus: Counter = Counter()
    store_meta: dict[str, dict] = {}

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        detail_futures = {
            pool.submit(fetch_detail, product["productCode"]): product["productCode"]
            for product in products
        }
        for future in as_completed(detail_futures):
            product_code = detail_futures[future]
            try:
                code, skus = future.result()
                skus_by_product[code] = skus
            except Exception as exc:
                detail_errors[product_code] = f"{type(exc).__name__}: {exc}"[:400]

        stock_futures = {}
        for product_code, skus in skus_by_product.items():
            for sku in skus:
                future = pool.submit(
                    fetch_store_stock, product_code, sku["skuCode"]
                )
                stock_futures[future] = (product_code, sku["skuCode"])

        sku_meta = {
            product_code: {sku["skuCode"]: sku for sku in skus}
            for product_code, skus in skus_by_product.items()
        }

        for future in as_completed(stock_futures):
            product_code, sku_code = stock_futures[future]
            try:
                _, _, stores = future.result()
                completed_skus[product_code] += 1
                for store in stores:
                    site_code = str(store.get("siteCode") or "")
                    site_name = str(store.get("siteName") or site_code)
                    if not site_code or not site_name:
                        continue
                    units = non_negative_int(store.get("siteStock"))
                    stock_counts[product_code].setdefault(site_name, 0)
                    stock_units[product_code].setdefault(site_name, 0)
                    if units > 0:
                        stock_counts[product_code][site_name] += 1
                        sku = sku_meta.get(product_code, {}).get(sku_code, {})
                        size = str(sku.get("size") or "其他").strip() or "其他"
                        color = (
                            str(sku.get("color") or "其他顏色").strip()
                            or "其他顏色"
                        )
                        size_bucket = stock_by_size[product_code][site_name][size]
                        size_bucket["skuCount"] += 1
                        size_bucket["units"] += units
                        size_bucket["colors"][color] += units
                    stock_units[product_code][site_name] += units
                    store_meta[site_code] = {
                        "siteCode": site_code,
                        "siteName": site_name,
                        "districtName": store.get("districtName"),
                    }
            except Exception as exc:
                failed_skus[product_code] += 1
                if len(stock_error_samples) < 20:
                    stock_error_samples.append(
                        {
                            "productCode": product_code,
                            "skuCode": sku_code,
                            "error": f"{type(exc).__name__}: {exc}"[:400],
                        }
                    )

    refreshed_at = utc_now()
    complete_products = 0
    stale_products = 0
    unavailable_products = 0
    total_skus = sum(len(skus) for skus in skus_by_product.values())
    total_stock_errors = sum(failed_skus.values())

    for product in products:
        code = product["productCode"]
        old_product = old_by_code.get(code) or {}
        expected = len(skus_by_product.get(code, []))
        product["skuCount"] = expected or old_product.get("skuCount", 0)
        if (
            expected > 0
            and completed_skus[code] == expected
            and failed_skus[code] == 0
        ):
            product["stock"] = dict(sorted(stock_counts[code].items()))
            product["stockUnits"] = dict(sorted(stock_units[code].items()))
            product["stockBySize"] = {
                store_name: {
                    size: {
                        "skuCount": int(values["skuCount"]),
                        "units": int(values["units"]),
                        "colors": dict(sorted(values["colors"].items())),
                    }
                    for size, values in sorted(
                        sizes.items(), key=lambda item: size_sort_key(item[0])
                    )
                }
                for store_name, sizes in sorted(stock_by_size[code].items())
            }
            product["stockStatus"] = "complete"
            product["stockUpdatedAt"] = refreshed_at
            complete_products += 1
            continue

        product["stock"] = old_product.get("stock", {})
        product["stockUnits"] = old_product.get("stockUnits", {})
        product["stockBySize"] = old_product.get("stockBySize", {})
        product["stockUpdatedAt"] = old_product.get("stockUpdatedAt")
        if product["stock"]:
            product["stockStatus"] = "stale"
            stale_products += 1
        else:
            product["stockStatus"] = "unavailable"
            unavailable_products += 1
        product["stockWarning"] = detail_errors.get(code) or (
            f"completed {completed_skus[code]}/{expected} SKU requests"
        )

    stores = sorted(store_meta.values(), key=lambda store: store["siteCode"])
    if not stores:
        stores = old_by_code.get("__stores__", [])
    summary = {
        "workers": WORKERS,
        "detailRequests": len(products),
        "detailErrors": len(detail_errors),
        "skuRequests": total_skus,
        "skuErrors": total_stock_errors,
        "completeProducts": complete_products,
        "staleProducts": stale_products,
        "unavailableProducts": unavailable_products,
        "storeCount": len(stores),
        "durationSeconds": round(time.monotonic() - started, 1),
        "detailErrorSamples": [
            {"productCode": code, "error": error}
            for code, error in list(detail_errors.items())[:20]
        ],
        "stockErrorSamples": stock_error_samples,
    }
    return products, stores, summary


def main() -> None:
    old = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {"products": []}
    old_products = old.get("products", [])
    old_by_code = {
        product.get("productCode"): product
        for product in old_products
        if product.get("productCode")
    }
    old_by_code["__stores__"] = old.get("stores", [])

    diagnostics: list[dict]
    if USE_EXISTING_SNAPSHOT:
        products = [dict(product) for product in old_products]
        diagnostics = [{"engine": "existing-snapshot", "candidateProducts": len(products)}]
    else:
        rows, diagnostics = render_listing()
        products = list(parse_products(rows).values())

    if PRODUCT_LIMIT:
        products = products[:PRODUCT_LIMIT]

    if not products:
        payload = dict(old)
        payload["diagnostics"] = diagnostics
        payload["warning"] = (
            "Playwright Firefox exposed no recognised GU product cards; "
            "retained previous snapshot."
        )
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
        raise SystemExit(1)

    products, stores, stock_summary = enrich_inventory(products, old_by_code)
    price_tiers = Counter(
        str(int(product["price"]) if float(product["price"]).is_integer() else product["price"])
        for product in products
    )
    payload = {
        "updatedAt": utc_now(),
        "stockUpdatedAt": max(
            (product.get("stockUpdatedAt") or "" for product in products), default=""
        )
        or None,
        "source": LISTING_URL,
        "products": products,
        "stores": stores,
        "priceTiers": dict(
            sorted(price_tiers.items(), key=lambda item: float(item[0]))
        ),
        "stockSummary": stock_summary,
        "diagnostics": diagnostics,
    }
    if stock_summary["completeProducts"] < len(products):
        payload["warning"] = (
            "Some products kept their previous inventory because one or more "
            "GU API requests failed."
        )

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"products={len(products)}")
    print(f"priceTiers={payload['priceTiers']}")
    print(f"stockSummary={json.dumps(stock_summary, ensure_ascii=False)}")
    for diagnostic in diagnostics:
        print(json.dumps(diagnostic, ensure_ascii=False))

    minimum_complete = max(1, int(len(products) * 0.8))
    if stock_summary["completeProducts"] < minimum_complete:
        raise SystemExit(
            "insufficient fresh stock coverage: "
            f"{stock_summary['completeProducts']}/{len(products)} products"
        )


if __name__ == "__main__":
    main()
