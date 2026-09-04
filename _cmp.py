# -*- coding: utf-8 -*-
"""比較：listing API 輕量判定 vs 詳情頁 productNumber 判定"""
import json
import time
import urllib.error
import urllib.request

from scraper import search_api as sa

OUT = r"d:\AiProject\SpiderCard\_cmp.txt"
lines = []


def listing_check(cid):
    url = f"https://snkrdunk.com/v1/apparels/{cid}/used?conditionIds=&page=1&perPage=1"
    req = urllib.request.Request(url, headers=sa._HEADERS)
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, context=sa._SSL_CTX, timeout=10) as resp:
            body = resp.read().decode("utf-8", errors="replace")
        return resp.status, len(body), body, time.time() - t0
    except urllib.error.HTTPError as e:
        return e.code, 0, "", time.time() - t0
    except Exception as e:
        return "ERR", 0, repr(e), time.time() - t0


def page_check(cid):
    url = sa.DETAIL_URL.format(id=cid)
    req = urllib.request.Request(url, headers=sa._HEADERS)
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, context=sa._SSL_CTX, timeout=12) as resp:
            html = resp.read().decode("utf-8", errors="replace")
        text = sa._decode_rsc_text(html)
        has = ('"productNumber"' in text) or ('"conditionId"' in html)
        return resp.status, len(html), has, time.time() - t0
    except urllib.error.HTTPError as e:
        return e.code, 0, False, time.time() - t0
    except Exception as e:
        return "ERR", 0, False, time.time() - t0


for cid in ("730968", "100063", "1", "100540"):
    st, ln, body, dt = listing_check(cid)
    has_pn = False
    if st == 200:
        has_pn = '"productNumber"' in body
    lines.append(f"LISTING {cid}: status={st} len={ln} has_productNumber={has_pn} dt={dt:.1f}s")

for cid in ("730968", "100063", "1", "100540"):
    st, ln, has, dt = page_check(cid)
    lines.append(f"PAGE    {cid}: status={st} len={ln} has_product={has} dt={dt:.1f}s")

with open(OUT, "w", encoding="utf-8") as f:
    f.write("\n".join(lines))
