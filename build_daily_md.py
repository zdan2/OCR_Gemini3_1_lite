# build_daily_md.py
# -*- coding: utf-8 -*-
"""
連絡帳パイプライン（日次・読み物版のたたき台）:
  renrakucho.db を読み、指定日の「日次報告」を人が読みやすいMarkdownで出力する。

既存の日次CSV（build_daily_report.py が出す 日次報告_YYYY-MM-DD.csv）は
一覧・並べ替え向き。こちらはコメント全文まで含めて1日分を通して読む読み物版。

集計のみ。OCR・API呼び出しはしない（DBの数値を読むだけ）。
要確認(confident=0)の行も出すが印を付ける。精度はテスト段階のため不問。

実行:
  .venv/Scripts/python.exe build_daily_md.py --date 2026-05-29
  # --date 省略時は DB にある全日付を出力
"""

from __future__ import annotations

import argparse
import sqlite3
from collections import defaultdict
from pathlib import Path
from typing import Optional

from build_daily_report import DB_PATH, OUT_DIR, fmt_minutes


def _t(v: Optional[float]) -> str:
    return f"{v:.1f}" if v is not None else "-"


def _stool(present, typ) -> str:
    if present is None:
        return "-"
    base = "有" if present else "無"
    return f"{base}/{typ}" if (present and typ) else base


def _meal(amount: Optional[str], text: Optional[str]) -> str:
    a = (amount or "").strip()
    t = (text or "").strip()
    if a and t:
        return f"{a}（{t}）"
    return a or t or "-"


def all_dates(con: sqlite3.Connection) -> list[str]:
    rows = con.execute(
        "SELECT DISTINCT entry_date FROM entries WHERE entry_date LIKE '____-__-%' "
        "ORDER BY entry_date"
    ).fetchall()
    return [r[0] for r in rows]


def load_date(con: sqlite3.Connection, date: str) -> list[dict]:
    rows = con.execute(
        "SELECT * FROM entries WHERE entry_date = ? ORDER BY class_name, child_kana",
        (date,),
    )
    return [dict(r) for r in rows]


def write_day_md(date: str, rows: list[dict], out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"日次報告_{date}.md"

    by_class: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_class[r.get("class_name") or "（クラス未確定）"].append(r)

    n_uncertain = sum(1 for r in rows if not r.get("match_confident"))
    n_absence = sum(1 for r in rows if r.get("absence_notice"))
    classes = "・".join(sorted(c for c in by_class if c != "（クラス未確定）")) or "—"

    L: list[str] = []
    L.append(f"# {date} 日次報告（{classes}）\n")
    L.append(f"対象 {len(rows)} 名 ・ 要確認 {n_uncertain} ・ お休み/早退 {n_absence}\n")

    for cls in sorted(by_class):
        L.append(f"## {cls}")
        for r in sorted(by_class[cls], key=lambda x: x.get("child_kana") or ""):
            flags = []
            if not r.get("match_confident"):
                flags.append("⚠要確認")
            if r.get("absence_notice"):
                flags.append("休/早退")
            flag_str = f"  〔{' '.join(flags)}〕" if flags else ""
            name = r.get("child_kanji") or r.get("child_kana") or "（名称不明）"
            L.append(f"### {name}{flag_str}")

            nap = ""
            if r.get("nap_min") is not None or r.get("nap_start"):
                span = ""
                if r.get("nap_start"):
                    span = f"（{r.get('nap_start')}〜{r.get('nap_end') or ''}）"
                nap = f" ・ 昼寝 {fmt_minutes(r.get('nap_min'))}{span}"
            L.append(f"- 睡眠: 就寝 {r.get('sleep_home_start') or '-'} / "
                     f"起床 {r.get('sleep_home_end') or '-'} / "
                     f"夜間 {fmt_minutes(r.get('sleep_home_min')) or '-'}{nap}")
            L.append(f"- 体温: 家 {_t(r.get('temp_home'))} / "
                     f"園午前 {_t(r.get('temp_en_am'))} / 園午後 {_t(r.get('temp_en_pm'))}")
            L.append(f"- 食事: 夕食 {_meal(r.get('meal_dinner'), r.get('meal_dinner_text'))} / "
                     f"朝食 {_meal(r.get('meal_breakfast'), r.get('meal_breakfast_text'))} / "
                     f"園 {_meal(r.get('meal_en'), r.get('meal_en_text'))}")
            L.append(f"- 排便: 家 {_stool(r.get('stool_present_home'), r.get('stool_type_home'))} / "
                     f"園 {_stool(r.get('stool_present_en'), r.get('stool_type_en'))}")
            ch = (r.get("comment_home") or "").strip()
            ce = (r.get("comment_en") or "").strip()
            if ch:
                L.append(f"- 保護者: {ch}")
            if ce:
                L.append(f"- 保育者: {ce}")
            un = (r.get("uncertain_notes") or "").strip()
            if un:
                L.append(f"- 📝要確認メモ: {un}")
            L.append("")
        L.append("")

    path.write_text("\n".join(L), encoding="utf-8")
    return path


def main() -> None:
    ap = argparse.ArgumentParser(description="renrakucho.db → 日次報告（読み物版Markdown）")
    ap.add_argument("--date", help="対象日 YYYY-MM-DD（省略時はDBの全日付）")
    args = ap.parse_args()

    if not DB_PATH.exists():
        raise SystemExit(f"DB不在: {DB_PATH}")
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row

    dates = [args.date] if args.date else all_dates(con)
    if not dates:
        raise SystemExit("対象日がありません（DBに有効な日付の行がありません）。")

    out_dir = OUT_DIR / "daily"
    for date in dates:
        rows = load_date(con, date)
        if not rows:
            print(f"[{date}] 行なし・スキップ")
            continue
        p = write_day_md(date, rows, out_dir)
        print(f"[{date}] {len(rows)} 名 -> {p}")

    con.close()
    print("完了。")


if __name__ == "__main__":
    main()
