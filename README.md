# GU HK Stock Finder

Static GitHub Pages dashboard for GU Hong Kong sale items, with distinct price-tier filtering and a low-frequency snapshot workflow.

The site never invents store inventory. If GU does not expose stock in supported public structured data, items remain `待同步` and link back to GU for verification.

## Publish

In repository **Settings → Pages**, choose **Deploy from a branch**, `main`, `/ (root)`.

The scheduled workflow refreshes the source snapshot every six hours and can also be run manually from **Actions**.
