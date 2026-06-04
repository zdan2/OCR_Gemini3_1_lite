# apply_corrections.py
# -*- coding: utf-8 -*-
"""
氏名認識の手動補正ステージ。corrections.json を読み、(source_pdf, source_page) で行を特定して
正しい児童に振り直す（確定化）。再OCRで上書きされても、このステージを毎回流せば補正が復活する
（watch_folder が build_daily_report の直後に呼ぶ）。DBを書き換える前に必ずバックアップを取る。
API呼び出しなし＝コストゼロ。

設計方針:
  - 人が原本PDFを見て決めた対応だけを反映する（AIに是非判断はさせない）。
  - キーは全行が持つ (source_pdf, source_page)＝再OCRしても安定。
  - 氏名の振り直しは PRIMARY KEY(child_kana, entry_date) を変えるため、衝突時は
    勝手に上書きせずスキップして警告（人が確認）。

corrections.json の形式（配列。1要素=1ページの補正）:
[
  {"pdf": "20260507どんぐり@家庭での生活.pdf", "page": 9,
   "child": "まるやまちゅうや",      // 名簿のかな氏名（または漢字氏名）
   "note": "原本確認 2026-06-04"}    // 任意・監査用メモ（DBには入れない）
]

使い方:
  python apply_corrections.py                          # corrections.json を適用
  python apply_corrections.py --file x.json --dry-run  # 試算（DB未変更）
  python apply_corrections.py --roster "…名簿.xlsx"    # 名簿を明示
"""

from __future__ import annotations

import argparse
import datetime as dt
import glob
import json
import shutil
import sqlite3
import sys
from pathlib import Path

try:  # 直接実行時に絵文字等でcp932コンソールが落ちないように
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import build_daily_report as bdr
import roster_match as rm

CORR_FILE = Path("corrections.json")


def find_roster(arg: str | None) -> str:
    if arg:
        return arg
    hits = sorted(glob.glob("*名簿*.xlsx"))
    if not hits:
        raise SystemExit("名簿xlsxが見つかりません。--roster で指定してください。")
    return hits[0]


def find_child(roster: list, child_key: str):
    """名簿から児童を探す。かな氏名・漢字氏名のどちらの表記でも引ける。"""
    q = rm._norm_kana(child_key)
    qraw = rm._norm_raw(child_key)
    for c in roster:
        if c.name_kana == q or rm._norm_raw(c.name_kanji) == qraw:
            return c
    return None


def main() -> None:
    ap = argparse.ArgumentParser(description="氏名認識の手動補正をDBに適用")
    ap.add_argument("--file", default=str(CORR_FILE), help=f"補正JSON（既定: {CORR_FILE}）")
    ap.add_argument("--roster", help="名簿xlsx（既定: カレントの *名簿*.xlsx）")
    ap.add_argument("--dry-run", action="store_true", help="DBを変えず内容だけ表示")
    args = ap.parse_args()

    corr_path = Path(args.file)
    if not corr_path.exists():
        print(f"[補正] {corr_path} が無いので何もしません。")
        return
    try:
        corrections = json.loads(corr_path.read_text(encoding="utf-8"))
    except Exception as e:
        raise SystemExit(f"[補正] {corr_path} の読込失敗: {e}")
    if not isinstance(corrections, list):
        raise SystemExit("[補正] corrections.json は配列([])で書いてください。")
    corrections = [c for c in corrections if isinstance(c, dict)]
    if not corrections:
        print("[補正] 補正項目が空です。")
        return

    if not bdr.DB_PATH.exists():
        raise SystemExit(f"DB不在: {bdr.DB_PATH}")
    roster_xlsx = find_roster(args.roster)

    if not args.dry_run:
        bak = bdr.DB_PATH.with_name(
            bdr.DB_PATH.name + f".bak_before_corrections_{dt.datetime.now():%Y%m%d_%H%M%S}")
        shutil.copy2(bdr.DB_PATH, bak)
        print(f"[補正] DBバックアップ: {bak.name}")

    con = sqlite3.connect(bdr.DB_PATH)
    con.row_factory = sqlite3.Row
    roster_cache: dict = {}
    affected_dates: set[str] = set()
    applied = skipped = 0

    for i, c in enumerate(corrections, 1):
        pdf = (c.get("pdf") or "").strip()
        page = c.get("page")
        child_key = (c.get("child") or "").strip()
        if not pdf or page is None or not child_key:
            print(f"  [{i}] スキップ: pdf / page / child は必須です -> {c}")
            skipped += 1
            continue
        base = Path(pdf).name
        row = con.execute(
            "SELECT rowid,* FROM entries WHERE source_pdf=? AND source_page=?",
            (base, int(page))).fetchone()
        if not row:
            print(f"  [{i}] スキップ: 該当行なし pdf={base} p{page}")
            skipped += 1
            continue
        date = row["entry_date"]
        try:
            mo = int(date.split("-")[1])
            sheet = f"{mo}月"
        except Exception:
            print(f"  [{i}] スキップ: 日付からシート決定不可 date={date}")
            skipped += 1
            continue
        if sheet not in roster_cache:
            try:
                roster_cache[sheet] = rm.load_roster(roster_xlsx, sheet)
            except Exception as e:
                print(f"  [{i}] 名簿 {sheet} 読込失敗: {e}")
                roster_cache[sheet] = []
        child = find_child(roster_cache[sheet], child_key)
        if not child:
            print(f"  [{i}] スキップ: 児童 {child_key!r} が {sheet} 名簿に居ません")
            skipped += 1
            continue
        if row["child_kana"] == child.name_kana and row["match_confident"] == 1:
            print(f"  [{i}] 変更なし: {base} p{page} は既に {child.name_kanji}")
            continue
        # 氏名振り直しは PK(child_kana, entry_date) を変える。衝突は勝手に潰さずスキップ警告。
        clash = con.execute(
            "SELECT rowid FROM entries WHERE child_kana=? AND entry_date=? AND rowid<>?",
            (child.name_kana, date, row["rowid"])).fetchone()
        if clash:
            print(f"  [{i}] [衝突] {child.name_kanji} の {date} は既に別行あり(rowid={clash['rowid']})。"
                  f"人の確認が要るのでスキップ。")
            skipped += 1
            continue
        old = row["child_kanji"]
        if args.dry_run:
            print(f"  [{i}] (dry) {base} p{page}: {old!r} -> "
                  f"{child.name_kanji}/{child.name_kana}（{child.class_name}）")
        else:
            con.execute(
                "UPDATE entries SET child_kanji=?, child_kana=?, class_name=?, "
                "match_confident=1, match_score=100 WHERE rowid=?",
                (child.name_kanji, child.name_kana, child.class_name, row["rowid"]))
            print(f"  [{i}] 補正: {base} p{page}: {old!r} -> {child.name_kanji}（{child.class_name}）")
        affected_dates.add(date)
        applied += 1

    if not args.dry_run:
        con.commit()
        # 補正で内容が変わった日の日次CSVをDB全件で再生成（report段の出力が古くなるため）
        for d in sorted(affected_dates):
            rows = bdr.fetch_date_rows(con, d)
            p = bdr.write_daily_csv(rows, d, bdr.OUT_DIR)
            print(f"  CSV再生成: {p}（当日DB {len(rows)}件）")
    con.close()
    tail = "（dry-run・DB未変更）" if args.dry_run else ""
    print(f"[補正] 適用 {applied} / スキップ {skipped}{tail}")


if __name__ == "__main__":
    main()
