# review_queue.py
# -*- coding: utf-8 -*-
"""
氏名認識の点検リスト。次の2種を原本の(pdf, ページ)キー付きで一覧化する。DB読み取りのみ。
  ①要確認(未確定)        … 児童が割り当てられていない行
  ②低スコア確定           … 自動確定されたがスコアが低い＝サイレント誤確定の疑い
これを見て原本PDFの該当ページを確認し、corrections.json に補正を書く流れ。

使い方:
  python review_queue.py                     # 全期間
  python review_queue.py --month 2026-05     # 月で絞る
  python review_queue.py --max-score 90      # 確定でもこの点未満は点検対象に含める（既定85）
  python review_queue.py --template          # child空欄の corrections_template.json を出力
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

try:  # 直接実行時にcp932コンソールが落ちないように
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

DB_PATH = Path("renrakucho.db")
OUT_DIR = Path("_reports")


def main() -> None:
    ap = argparse.ArgumentParser(description="氏名認識の点検リスト出力")
    ap.add_argument("--month", help="YYYY-MM で絞る")
    ap.add_argument("--max-score", type=float, default=85.0,
                    help="確定でもこのスコア未満は点検対象に含める（既定85）")
    ap.add_argument("--template", action="store_true",
                    help="corrections_template.json（child空欄）を書き出す")
    args = ap.parse_args()

    if not DB_PATH.exists():
        raise SystemExit(f"DB不在: {DB_PATH}")
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row

    where = "(match_confident=0 OR (match_confident=1 AND match_score < ?))"
    params: list = [args.max_score]
    if args.month:
        where += " AND entry_date LIKE ?"
        params.append(f"{args.month}-%")
    rows = [dict(r) for r in con.execute(
        f"SELECT * FROM entries WHERE {where} "
        f"ORDER BY match_confident, entry_date, source_pdf, source_page", params)]
    con.close()

    n_un = sum(1 for r in rows if not r["match_confident"])
    n_low = len(rows) - n_un
    print(f"点検対象 {len(rows)} 件（①要確認 {n_un} / ②低スコア確定 {n_low}・閾値<{args.max_score:.0f}）")
    print("-" * 88)
    for r in rows:
        kind = "①要確認" if not r["match_confident"] else "②低確定"
        name = r["child_kanji"] or r["child_kana"] or "（不明）"
        cm = (r.get("comment_home") or "").replace("\n", " ").strip()[:24]
        print(f"[{kind}] {r['entry_date']} score={r['match_score']:>5} "
              f"読={name} | {r['source_pdf']} p{r['source_page']} | {cm}")

    if args.template:
        OUT_DIR.mkdir(exist_ok=True)
        tmpl = [{
            "pdf": r["source_pdf"], "page": r["source_page"], "child": "",
            "note": f"{r['entry_date']} 読={r['child_kanji'] or r['child_kana']} score={r['match_score']}",
        } for r in rows]
        p = OUT_DIR / "corrections_template.json"
        p.write_text(json.dumps(tmpl, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nテンプレート: {p}")
        print("  child を名簿のかな氏名で埋め、不要な行は消して corrections.json にし、")
        print("  python apply_corrections.py で反映してください。")


if __name__ == "__main__":
    main()
