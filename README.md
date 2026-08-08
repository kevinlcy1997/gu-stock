# GU HK Stock Finder

Static GitHub Pages dashboard for GU Hong Kong women's sale items, with distinct price-tier and store filtering.

The scheduled workflow:

1. renders the GU sale listing with Playwright Firefox;
2. reads each product's active colour/size SKUs from GU's public product-detail API;
3. queries GU's public store-stock API with bounded concurrency;
4. aggregates both available-SKU counts and unit counts for each store; and
5. keeps the last good product inventory whenever any SKU request for that product fails.

No login, cookies, or private credentials are used. Inventory is a point-in-time snapshot and should be verified with GU before purchase.

## Publish

In repository **Settings → Pages**, choose **Deploy from a branch**, `main`, `/ (root)`.

The snapshot refreshes every six hours and can also be run manually from **Actions → Update GU snapshot**.
