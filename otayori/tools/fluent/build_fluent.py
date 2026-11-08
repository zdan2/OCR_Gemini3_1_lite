"""pick.txt で選んだ Fluent Emoji（Flat）を取ってきて、工房のイラストの形
（キー → [分類, 名前, 48×48 の SVG 断片]）にした static/illust_fluent.js を作る。

SVG は図形と塗りだけを残す（スクリプトや外への参照は入れない）。
元は 32×32 なので、scale(1.5) で 48×48 にそろえる。
"""
import collections
import concurrent.futures as cf
import json
import re
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT_JS = HERE.parent.parent / "static" / "illust_fluent.js"
OUT_LICENSE = HERE.parent.parent / "static" / "fluent-LICENSE.txt"
RAW = "https://raw.githubusercontent.com/microsoft/fluentui-emoji/main/"
SVG_NS = "{http://www.w3.org/2000/svg}"

ALLOWED = {"svg", "g", "path", "circle", "ellipse", "rect", "line", "polyline", "polygon",
           "defs", "linearGradient", "radialGradient", "stop", "clipPath"}
ATTRS = {"d", "cx", "cy", "r", "rx", "ry", "x", "y", "x1", "y1", "x2", "y2", "fx", "fy", "width", "height",
         "points", "fill", "stroke", "stroke-width", "stroke-linecap", "stroke-linejoin", "stroke-miterlimit",
         "opacity", "fill-opacity", "stroke-opacity", "fill-rule", "clip-rule", "transform", "id",
         "offset", "stop-color", "stop-opacity", "gradientUnits", "gradientTransform", "clip-path"}
SAFE_URL = re.compile(r"^url\(#[A-Za-z0-9_\-]+\)$")


def slug(name):
    return "f_" + re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def read_pick():
    rows, seen = [], set()
    for line in (HERE / "pick.txt").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        folder, ja, group = [x.strip() for x in line.split("|")]
        if folder in seen:
            continue
        seen.add(folder)
        rows.append((folder, ja, group))
    return rows


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "otayori-kobo-build"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8")


def clean(svg_text, prefix):
    """許した要素と属性だけで組み直す。id は衝突しないよう prefix を付ける。"""
    root = ET.fromstring(svg_text)
    dropped = set()

    def walk(el):
        tag = el.tag.replace(SVG_NS, "")
        if tag not in ALLOWED:
            dropped.add(tag)
            return ""
        attrs = []
        for k, v in el.attrib.items():
            k = k.replace(SVG_NS, "")
            if k not in ATTRS:
                continue
            v = v.strip()
            if "url(" in v:
                if not SAFE_URL.match(v):
                    continue
                v = v.replace("url(#", "url(#" + prefix)
            if k == "id":
                v = prefix + v
            if any(c in v for c in '<>"') or "javascript" in v.lower():
                continue
            attrs.append(f'{k}="{v}"')
        inner = "".join(walk(c) for c in el)
        if tag == "svg":
            return inner
        a = (" " + " ".join(attrs)) if attrs else ""
        return f"<{tag}{a}>{inner}</{tag}>" if inner else f"<{tag}{a}/>"

    body = walk(root)
    vb = root.attrib.get("viewBox", "0 0 32 32").split()
    w = float(vb[2]) if len(vb) == 4 else 32.0
    scale = 48.0 / w
    return f'<g transform="scale({scale:g})">{body}</g>', dropped


def flat_paths():
    """Fluent Emoji の Flat 版 SVG の置き場所（フォルダ名 → パス）。肌の色ちがいは Default を使う。"""
    cache = HERE / "flat_paths.json"
    if cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))
    tree = json.loads(fetch("https://api.github.com/repos/microsoft/fluentui-emoji/git/trees/main?recursive=1"))
    by = collections.OrderedDict()
    for e in tree["tree"]:
        parts = e["path"].split("/")
        if len(parts) == 4 and parts[2] == "Flat" and parts[3].endswith("_flat.svg"):
            by.setdefault(parts[1], e["path"])
        elif len(parts) == 5 and parts[2] == "Default" and parts[3] == "Flat" and parts[4].endswith(".svg"):
            by.setdefault(parts[1], e["path"])
    cache.write_text(json.dumps(by, ensure_ascii=False), encoding="utf-8")
    return by


def main():
    paths = flat_paths()
    rows = read_pick()
    missing = [r[0] for r in rows if r[0] not in paths]
    if missing:
        print("見つからない:", missing)
    rows = [r for r in rows if r[0] in paths]

    def job(row):
        folder, ja, group = row
        url = RAW + urllib.parse.quote(paths[folder])
        return row, fetch(url)

    out, drops, fails = collections.OrderedDict(), collections.Counter(), []
    with cf.ThreadPoolExecutor(max_workers=8) as ex:
        results = list(ex.map(lambda r: _safe(job, r), rows))
    for res in results:
        if isinstance(res, tuple) and res[0] == "ERR":
            fails.append(res[1]); continue
        (folder, ja, group), text = res
        key = slug(folder)
        frag, dropped = clean(text, key + "_")
        for d in dropped:
            drops[d] += 1
        out[key] = [group, ja, frag]

    OUT_LICENSE.write_text(fetch(RAW + "LICENSE"), encoding="utf-8")
    js = ["/* Fluent Emoji（Flat）から選んだイラスト。工房の ILL に足す。",
          "   Copyright (c) Microsoft Corporation. MIT License（全文は fluent-LICENSE.txt）。",
          "   https://github.com/microsoft/fluentui-emoji",
          "   作りなおすときは tools/fluent/build_fluent.py（選んだ一覧は pick.txt）。 */",
          "(function () {",
          "var F = " + json.dumps(out, ensure_ascii=False, separators=(",", ":")) + ";",
          "for (var k in F){ if (!ILL[k]){ ILL[k] = F[k]; ILL_KEYS.push(k); } }",
          "})();", ""]
    OUT_JS.write_text("\n".join(js), encoding="utf-8", newline="\n")
    sizes = sum(len(v[2]) for v in out.values())
    print(f"illustrations: {len(out)} | fragment bytes: {sizes} | file: {OUT_JS.stat().st_size} B")
    print("dropped tags:", dict(drops) or "none", "| failed:", fails or "none")
    groups = collections.Counter(v[0] for v in out.values())
    print("groups:", dict(groups))


def _safe(fn, row):
    try:
        return fn(row)
    except Exception as exc:  # noqa: BLE001
        return ("ERR", f"{row[0]}: {exc}")


if __name__ == "__main__":
    main()
