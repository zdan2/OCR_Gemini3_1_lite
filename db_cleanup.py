# db_cleanup.py
# -*- coding: utf-8 -*-
"""
renrakucho.db の既存データを一度きりで整理する（API不要・無料）。

やること:
  1. DBをタイムスタンプ付きでバックアップ。
  2. 各行の entry_date を source_pdf のファイル名(YYYYMMDD)から付け直す
     （日付OCR誤読で 2023/2025/3月 等に飛んだ迷子レコードを正しい日に戻す）。
  3. (source_pdf, source_page) が重複する行を1つに集約
     （照合失敗→成功でキーが変わり古い失敗行が残った 05-28 の膨張を解消）。
     残す優先順位: 確定(match_confident=1) > 新しい(created_at)。
  4. (child_kana, entry_date) が重複する行を1つに集約
     （同じ子・同じ日が複数PDFに跨った重複を解消。主キー制約も満たす）。
  5. テーブルを作り直して整理後の行を入れ直す。
  6. _reports/ の日次CSVを作り直す（古い迷子CSVは削除）。

実行: .venv/Scripts/python.exe db_cleanup.py
"""

from __future__ import annotations

import datetime as dt
import shutil
import sqlite3
from pathlib import Path

from build_daily_report import (
    DB_PATH, OUT_DIR, SCHEMA_SQL, date_from_filename, write_daily_csv,
)

# 整理後のテーブルに入れる列（_cost等の一時キーは除く、created_atまで）
COLS = [
    "child_kanji", "child_kana", "class_name", "entry_date",
    "match_score", "match_confident", "source_pdf", "source_page",
    "sleep_home_start", "sleep_home_end", "sleep_home_min",
    "nap_start", "nap_end", "nap_min",
    "temp_home", "temp_en_am", "temp_en_pm",
    "meal_dinner", "meal_breakfast", "meal_en",
    "meal_dinner_text", "meal_breakfast_text", "meal_en_text",
    "stool_present_home", "stool_type_home", "stool_present_en", "stool_type_en",
    "comment_home", "comment_en", "uncertain_notes",
    "absence_notice", "absence_hits", "created_at",
]


def _priority(row: dict):
    """残す行の優先度。大きいほど優先: 確定>未確定, created_atが新しいほど優先。"""
    return (int(row.get("match_confident") or 0), row.get("created_at") or "")


def main() -> None:
    if not DB_PATH.exists():
        raise SystemExit(f"DB不在: {DB_PATH}")

    # 1) バックアップ
    ts = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = DB_PATH.with_suffix(f".db.bak_{ts}")
    shutil.copy2(DB_PATH, bak)
    print(f"[バックアップ] {bak}")

    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    rows = [dict(r) for r in con.execute(f"SELECT {','.join(COLS)} FROM entries")]
    before = len(rows)
    print(f"[読込] {before} 行")

    # 2) entry_date をファイル名から付け直す
    redated = 0
    for r in rows:
        fd = date_from_filename(r.get("source_pdf") or "")
        if fd:
            iso = fd.isoformat()
            if r.get("entry_date") != iso:
                redated += 1
            r["entry_date"] = iso
    print(f"[再日付] ファイル名から付け直し: {redated} 行を変更")

    # 3) (source_pdf, source_page) で集約
    by_page: dict[tuple, dict] = {}
    for r in rows:
        key = (r.get("source_pdf"), r.get("source_page"))
        cur = by_page.get(key)
        if cur is None or _priority(r) > _priority(cur):
            by_page[key] = r
    step3 = list(by_page.values())
    print(f"[集約1] (PDF,ページ)重複を解消: {len(rows)} -> {len(step3)} 行")

    # 4) (child_kana, entry_date) で集約（主キー制約を満たす）
    by_child: dict[tuple, dict] = {}
    for r in step3:
        key = (r.get("child_kana"), r.get("entry_date"))
        cur = by_child.get(key)
        if cur is None or _priority(r) > _priority(cur):
            by_child[key] = r
    final = list(by_child.values())
    print(f"[集約2] (児童かな,日付)重複を解消: {len(step3)} -> {len(final)} 行")

    # 5) テーブル再作成
    con.execute("DROP TABLE IF EXISTS entries")
    con.execute(SCHEMA_SQL)
    placeholders = ",".join("?" for _ in COLS)
    con.executemany(
        f"INSERT INTO entries ({','.join(COLS)}) VALUES ({placeholders})",
        [[r.get(c) for c in COLS] for r in final],
    )
    con.commit()
    print(f"[書込] {len(final)} 行を再投入 (削除: {before - len(final)} 行)")

    # 6) CSV作り直し（古い日次CSVを削除してから）
    if OUT_DIR.exists():
        removed = 0
        for p in OUT_DIR.glob("日次報告_*.csv"):
            p.unlink()
            removed += 1
        print(f"[CSV] 古い日次CSVを削除: {removed} 件")
    by_date: dict[str, list] = {}
    for r in final:
        by_date.setdefault(r["entry_date"], []).append(r)
    for date, drows in sorted(by_date.items()):
        write_daily_csv(drows, date, OUT_DIR)
    print(f"[CSV] {len(by_date)} 日分を出力: {sorted(by_date)}")

    con.close()
    print("\n完了。問題があればバックアップから戻せます:")
    print(f"  copy {bak.name} {DB_PATH.name}")


if __name__ == "__main__":
    main()
