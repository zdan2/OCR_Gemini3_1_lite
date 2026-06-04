# reapply_aliases.py
# -*- coding: utf-8 -*-
"""
別名辞書(alias.json)を「既存DBの要確認行」に再適用する。

なぜ必要か:
  alias.json はOCR取り込みの瞬間にしか参照されない。よって alias.json を直しても、
  既にDBに入っている要確認(match_confident=0)の行は自動では直らない（再OCRしない限り古いまま）。
  このスクリプトは要確認行の「読み取り名」を現在の alias で再照合し、
  **aliasで確定できるものだけ**をDB上で確定化する。
  曖昧(fuzzy)照合では確定しない＝誤った子に勝手に紐付けない安全側の設計。

特徴: 冪等・実行前にDB自動バックアップ・影響日の日次CSVを再生成・API呼び出しなし。
watch_folder が取り込み直後に毎回呼ぶので、alias.json を直せば次スキャンで既存の要確認にも反映される。

使い方:
  python reapply_aliases.py --dry-run     # 直る予定だけ表示（DB未変更）
  python reapply_aliases.py               # 反映
  python reapply_aliases.py --roster "…名簿.xlsx" --aliases /data/alias.json
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

try:  # 直接実行時にcp932コンソールが落ちないように
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import build_daily_report as bdr
import roster_match as rm


def find_roster(arg: str | None) -> str:
    if arg:
        return arg
    hits = sorted(glob.glob("*名簿*.xlsx"))
    if not hits:
        raise SystemExit("名簿xlsxが見つかりません。--roster で指定してください。")
    return hits[0]


def load_aliases(path: str | None) -> dict:
    p = Path(path) if path else Path("alias.json")
    if not p.exists():
        raise SystemExit(f"alias辞書が見つかりません: {p}")
    data = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise SystemExit("alias.json はオブジェクト形式({...})で書いてください。")
    return data


def main() -> None:
    ap = argparse.ArgumentParser(description="alias.jsonを既存の要確認行に再適用")
    ap.add_argument("--roster", help="名簿xlsx（既定: カレントの *名簿*.xlsx）")
    ap.add_argument("--aliases", help="alias辞書JSON（既定: alias.json）")
    ap.add_argument("--dry-run", action="store_true", help="DBを変えず内容だけ表示")
    args = ap.parse_args()

    if not bdr.DB_PATH.exists():
        raise SystemExit(f"DB不在: {bdr.DB_PATH}")
    roster_xlsx = find_roster(args.roster)
    aliases = load_aliases(args.aliases)

    if not args.dry_run:
        bak = bdr.DB_PATH.with_name(
            bdr.DB_PATH.name + f".bak_before_reapply_aliases_{dt.datetime.now():%Y%m%d_%H%M%S}")
        shutil.copy2(bdr.DB_PATH, bak)
        print(f"[再適用] DBバックアップ: {bak.name}")

    con = sqlite3.connect(bdr.DB_PATH)
    con.row_factory = sqlite3.Row
    rows = [dict(r) for r in con.execute("SELECT rowid,* FROM entries WHERE match_confident=0")]
    print(f"[再適用] 要確認 {len(rows)} 行を alias({len(aliases)}件) で再照合")

    roster_cache: dict = {}
    affected: set[str] = set()
    applied = skipped = 0

    for r in rows:
        raw = r["child_kanji"] or ""
        date = r["entry_date"]
        try:
            mo = int(date.split("-")[1])
            sheet = f"{mo}月"
        except Exception:
            continue
        if sheet not in roster_cache:
            try:
                roster_cache[sheet] = rm.load_roster(roster_xlsx, sheet)
            except Exception as e:
                print(f"  名簿 {sheet} 読込失敗: {e}")
                roster_cache[sheet] = []
        res = rm.match_child(raw, roster_cache[sheet], aliases=aliases)
        # aliasで確定できたものだけ採用（fuzzyの自動確定はしない＝安全側）
        if not (res.matched_by == "alias" and res.confident and res.child):
            continue
        child = res.child
        clash = con.execute(
            "SELECT rowid FROM entries WHERE child_kana=? AND entry_date=? AND rowid<>?",
            (child.name_kana, date, r["rowid"])).fetchone()
        if clash:
            print(f"  [衝突] {child.name_kanji} の {date} は既に別行あり(rowid={clash['rowid']}) → スキップ")
            skipped += 1
            continue
        if args.dry_run:
            print(f"  (dry) {date} p{r['source_page']}: '{raw}' -> {child.name_kanji}（{child.class_name}）")
        else:
            con.execute(
                "UPDATE entries SET child_kanji=?, child_kana=?, class_name=?, "
                "match_confident=1, match_score=100 WHERE rowid=?",
                (child.name_kanji, child.name_kana, child.class_name, r["rowid"]))
            print(f"  確定: {date} p{r['source_page']}: '{raw}' -> {child.name_kanji}（{child.class_name}）")
        affected.add(date)
        applied += 1

    if not args.dry_run:
        con.commit()
        for d in sorted(affected):
            drows = bdr.fetch_date_rows(con, d)
            bdr.write_daily_csv(drows, d, bdr.OUT_DIR)
            print(f"  CSV再生成: {d}（当日DB {len(drows)}件）")
    con.close()
    tail = "（dry-run・DB未変更）" if args.dry_run else ""
    print(f"[再適用] 確定 {applied} / スキップ {skipped}{tail}")


if __name__ == "__main__":
    main()
