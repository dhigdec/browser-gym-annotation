"""Capture self-contained HTML snapshots of the gym's real pages for the
annotator platform's replay pane (M3 — "Captured frame · rendered DOM snapshot").

The gym renders with Tailwind (CDN, which injects a <style> into the live DOM)
plus a local /static/style.css. So a snapshot taken after load is nearly
self-contained: we inline the local CSS, keep Tailwind's injected <style>, strip
the CDN scripts (the generated CSS is already in the DOM) and the gym's internal
task banner, and inline same-origin images as data URIs.

Usage:
    BASE=http://localhost:8077 TOKEN=... OUT=/path/to/snapshots \
        .venv/bin/python -m eval.capture_review_snapshots
Assumes a gym server is already running (with HARNESS_TOKEN) at BASE.
"""

import asyncio
import json
import os
from pathlib import Path

import httpx
from playwright.async_api import async_playwright

BASE = os.environ.get("BASE", "http://localhost:8077")
TOKEN = os.environ.get("TOKEN", "")
OUT = Path(os.environ.get("OUT", "snapshots"))
SEED_TASK = os.environ.get("SEED_TASK", "M73/expired_card_checkout")

# key -> path. Reset seeds a cart + saved cards so these render realistically.
CAPTURES = [
    ("shop_home", "/"),
    ("shop_cart", "/cart"),
    ("shop_payments", "/account/payments"),
    ("market", "/market"),
    ("calendar", "/calendar"),
    ("mail", "/mail"),
]

# Runs in the page: inline resources, strip scripts + task banner, return HTML.
_SELF_CONTAIN = r"""
async (cssText) => {
  document.querySelectorAll('script').forEach(s => s.remove());
  document.querySelectorAll('link[rel="stylesheet"]').forEach(l => l.remove());
  const banner = document.querySelector('[data-test-id="task-banner"]');
  if (banner) banner.remove();
  const style = document.createElement('style');
  style.textContent = cssText;
  document.head.appendChild(style);
  // inline same-origin images as data URIs
  const imgs = [...document.querySelectorAll('img')];
  await Promise.all(imgs.map(async (img) => {
    try {
      const u = new URL(img.src, location.href);
      if (u.origin !== location.origin) return;
      const r = await fetch(u.href);
      const b = await r.blob();
      img.src = await new Promise((res) => { const fr = new FileReader(); fr.onload = () => res(fr.result); fr.readAsDataURL(b); });
    } catch (e) { /* leave as-is */ }
  }));
  return '<!doctype html>' + document.documentElement.outerHTML;
}
"""


async def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    headers = {"X-Harness-Token": TOKEN}
    # seed a realistic world (cart with items, saved cards, mail, calendar…)
    with httpx.Client() as c:
        c.post(f"{BASE}/_harness/reset", json={"task_id": SEED_TASK, "seed": 0}, headers=headers, timeout=30)
        css = c.get(f"{BASE}/static/style.css", timeout=30).text

    manifest = {}
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(viewport={"width": 1180, "height": 780})
        for key, path in CAPTURES:
            await page.goto(BASE + path, wait_until="networkidle")
            html = await page.evaluate(_SELF_CONTAIN, css)
            (OUT / f"{key}.html").write_text(html, encoding="utf-8")
            manifest[key] = f"{key}.html"
            print(f"  captured {key:16} <- {path}  ({len(html) // 1024} KB)")
        await browser.close()

    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"wrote {len(manifest)} snapshots + manifest.json to {OUT}")


if __name__ == "__main__":
    asyncio.run(main())
