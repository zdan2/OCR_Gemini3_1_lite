# build_monthly_report.py
# -*- coding: utf-8 -*-
"""
連絡帳パイプライン（第2段）: renrakucho.db を読み、指定月の児童別「月次振り返り」を作る。

出力（2種類）:
  1. クラス集計CSV  _reports/月次サマリ_YYYY-MM.csv
       1行=1児童。平均睡眠/睡眠ブレ/発熱日数/お休み日数などの数値サマリ。Excelで全員を一覧。
  2. 児童別Markdown _reports/monthly/YYYY-MM/<児童名>.md
       1ファイル=1児童。睡眠・体温・排便の日別推移＋コメント履歴を人が読んで振り返る読み物。

集計のみ。新たなOCR・API呼び出しはしない（DBにある数値を読むだけ）。
精度はテスト段階のため不問。要確認(confident=0)の行も含めて出すが、印を付ける。

実行:
  .venv/Scripts/python.exe build_monthly_report.py --month 2026-05
  # --month 省略時は DB にある最新の月を自動採用
"""

from __future__ import annotations

import argparse
import csv
import sqlite3
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any, Optional

from build_daily_report import DB_PATH, OUT_DIR, fmt_minutes

FEVER_C = 37.5  # 発熱とみなすライン（家庭体温）
SLEEP_SHORT_RATIO = 0.75  # 平均のこの割合を下回る夜は「極端に短い」と印


def _stat(values: list[float]) -> dict[str, Any]:
    """非Noneの数値リストから 件数/平均/最小/最大/標準偏差 を出す。空なら全てNone。"""
    if not values:
        return {"n": 0, "avg": None, "min": None, "max": None, "sd": None}
    return {
        "n": len(values),
        "avg": statistics.mean(values),
        "min": min(values),
        "max": max(values),
        "sd": statistics.pstdev(values) if len(values) > 1 else 0.0,
    }


def load_month(con: sqlite3.Connection, month: str) -> list[dict]:
    """entry_date が 'YYYY-MM' で始まる行を読む。"""
    rows = con.execute(
        "SELECT * FROM entries WHERE entry_date LIKE ? ORDER BY entry_date, class_name, child_kana",
        (f"{month}-%",),
    )
    return [dict(r) for r in rows]


def latest_month(con: sqlite3.Connection) -> Optional[str]:
    r = con.execute(
        "SELECT substr(entry_date,1,7) m FROM entries WHERE entry_date LIKE '____-__-%' "
        "ORDER BY entry_date DESC LIMIT 1"
    ).fetchone()
    return r[0] if r else None


def summarize_child(rows: list[dict]) -> dict[str, Any]:
    """1児童分の行リストから月次サマリを計算する。"""
    days = sorted(rows, key=lambda r: r["entry_date"])
    sleep = [r["sleep_home_min"] for r in days if r.get("sleep_home_min") is not None]
    nap = [r["nap_min"] for r in days if r.get("nap_min") is not None]
    temp_home = [r["temp_home"] for r in days if r.get("temp_home") is not None]

    fever_days = [r["entry_date"] for r in days
                  if r.get("temp_home") is not None and r["temp_home"] >= FEVER_C]
    absence_days = [r["entry_date"] for r in days if r.get("absence_notice")]
    uncertain_days = [r["entry_date"] for r in days if not r.get("match_confident")]
    stool_home = sum(1 for r in days if r.get("stool_present_home"))
    stool_en = sum(1 for r in days if r.get("stool_present_en"))

    return {
        "rows": days,
        "record_days": len(days),
        "sleep": _stat(sleep),
        "nap": _stat(nap),
        "temp_home": _stat(temp_home),
        "fever_days": fever_days,
        "absence_days": absence_days,
        "uncertain_days": uncertain_days,
        "stool_home_days": stool_home,
        "stool_en_days": stool_en,
    }


# ---------------------------------------------------------------------------
# 1) クラス集計CSV
# ---------------------------------------------------------------------------

SUMMARY_HEADER = [
    "児童名", "クラス", "記録日数", "要確認日数",
    "夜間睡眠_平均", "夜間睡眠_最短", "夜間睡眠_最長", "夜間睡眠_ブレ幅",
    "昼寝_平均", "昼寝_最短", "昼寝_最長",
    "体温家_平均", "体温家_最高", "発熱日数(>=37.5)",
    "排便あり日数(家)", "排便あり日数(園)",
    "お休み早退日数", "お休み早退日",
]


def _fm(s: dict, key: str) -> str:
    v = s.get(key)
    return fmt_minutes(round(v)) if v is not None else ""


def _t(v: Optional[float]) -> str:
    return f"{v:.1f}" if v is not None else ""


def write_summary_csv(children: list[tuple[str, str, dict]], month: str, out_dir: Path) -> Path:
    out_dir.mkdir(exist_ok=True)
    path = out_dir / f"月次サマリ_{month}.csv"
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(SUMMARY_HEADER)
        for name, cls, s in children:
            sl, nap, th = s["sleep"], s["nap"], s["temp_home"]
            w.writerow([
                name, cls, s["record_days"], len(s["uncertain_days"]),
                _fm(sl, "avg"), _fm(sl, "min"), _fm(sl, "max"), _fm(sl, "sd"),
                _fm(nap, "avg"), _fm(nap, "min"), _fm(nap, "max"),
                _t(th["avg"]), _t(th["max"]), len(s["fever_days"]),
                s["stool_home_days"], s["stool_en_days"],
                len(s["absence_days"]), " ".join(s["absence_days"]),
            ])
    return path


# ---------------------------------------------------------------------------
# 2) 児童別Markdown
# ---------------------------------------------------------------------------

def _safe_filename(name: str) -> str:
    bad = '<>:"/\\|?*'
    cleaned = "".join("_" if c in bad else c for c in name).strip()
    return cleaned or "名称不明"


def write_child_md(name: str, cls: str, s: dict, month: str, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{_safe_filename(name)}.md"
    sl = s["sleep"]
    short_line = (sl["avg"] * SLEEP_SHORT_RATIO) if sl["avg"] is not None else None

    L: list[str] = []
    L.append(f"# {name}（{cls}）— {month} 月次振り返り\n")
    L.append(f"- 記録日数: {s['record_days']} 日")
    if s["uncertain_days"]:
        L.append(f"- ⚠ 要確認日: {len(s['uncertain_days'])} 日（{', '.join(s['uncertain_days'])}）")
    L.append("")

    # 睡眠
    L.append("## 睡眠")
    if sl["avg"] is not None:
        L.append(f"- 夜間睡眠 平均 **{fmt_minutes(round(sl['avg']))}** "
                 f"（最短 {fmt_minutes(round(sl['min']))} 〜 最長 {fmt_minutes(round(sl['max']))}、"
                 f"ブレ幅 ±{fmt_minutes(round(sl['sd']))}）")
    else:
        L.append("- 夜間睡眠: 記録なし")
    nap = s["nap"]
    if nap["avg"] is not None:
        L.append(f"- 昼寝 平均 {fmt_minutes(round(nap['avg']))} "
                 f"（最短 {fmt_minutes(round(nap['min']))} 〜 最長 {fmt_minutes(round(nap['max']))}）")
    L.append("")
    L.append("| 日付 | 就寝 | 起床 | 夜間睡眠 | 昼寝 | 印 |")
    L.append("|---|---|---|---|---|---|")
    for r in s["rows"]:
        m = r.get("sleep_home_min")
        mark = "🔻短" if (short_line is not None and m is not None and m < short_line) else ""
        L.append(f"| {r['entry_date']} | {r.get('sleep_home_start') or ''} | "
                 f"{r.get('sleep_home_end') or ''} | {fmt_minutes(m)} | "
                 f"{fmt_minutes(r.get('nap_min'))} | {mark} |")
    L.append("")

    # 体温
    L.append("## 体温")
    th = s["temp_home"]
    if th["avg"] is not None:
        L.append(f"- 家庭体温 平均 {th['avg']:.1f}℃（最高 {th['max']:.1f}℃）")
    if s["fever_days"]:
        L.append(f"- 🌡 発熱ライン({FEVER_C}℃)以上: {len(s['fever_days'])} 日"
                 f"（{', '.join(s['fever_days'])}）")
    L.append("")
    L.append("| 日付 | 体温(家) | 体温(園午前) | 体温(園午後) |")
    L.append("|---|---|---|---|")
    for r in s["rows"]:
        L.append(f"| {r['entry_date']} | {_t(r.get('temp_home'))} | "
                 f"{_t(r.get('temp_en_am'))} | {_t(r.get('temp_en_pm'))} |")
    L.append("")

    # 排便
    L.append("## 排便")
    L.append(f"- 家で排便あり: {s['stool_home_days']} 日 / 園で排便あり: {s['stool_en_days']} 日")
    L.append("")

    # お休み・早退
    L.append("## お休み・早退")
    if s["absence_days"]:
        L.append(f"- 該当 {len(s['absence_days'])} 日: {', '.join(s['absence_days'])}")
    else:
        L.append("- なし")
    L.append("")

    # コメント履歴
    L.append("## コメント履歴")
    for r in s["rows"]:
        ch = (r.get("comment_home") or "").strip()
        ce = (r.get("comment_en") or "").strip()
        if not ch and not ce:
            continue
        L.append(f"### {r['entry_date']}")
        if ch:
            L.append(f"- 保護者: {ch}")
        if ce:
            L.append(f"- 保育者: {ce}")
        L.append("")

    path.write_text("\n".join(L), encoding="utf-8")
    return path


def main() -> None:
    ap = argparse.ArgumentParser(description="renrakucho.db → 月次振り返り（CSVサマリ＋児童別Markdown）")
    ap.add_argument("--month", help="対象月 YYYY-MM（省略時はDBの最新月）")
    args = ap.parse_args()

    if not DB_PATH.exists():
        raise SystemExit(f"DB不在: {DB_PATH}")
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row

    month = args.month or latest_month(con)
    if not month:
        raise SystemExit("対象月が決められません（DBに有効な日付の行がありません）。")
    print(f"[対象月] {month}")

    rows = load_month(con, month)
    if not rows:
        raise SystemExit(f"{month} の行がDBにありません。")
    print(f"[読込] {len(rows)} 行")

    # 児童ごとに集約（child_kana が安定キー。要確認行は個別キーなので別扱いになる）
    grouped: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        grouped[r["child_kana"]].append(r)

    children: list[tuple[str, str, dict]] = []
    for kana, crows in grouped.items():
        name = crows[0].get("child_kanji") or kana
        cls = crows[0].get("class_name") or ""
        children.append((name, cls, summarize_child(crows)))
    # クラス→名前で並べる
    children.sort(key=lambda x: (x[1], x[0]))

    csv_path = write_summary_csv(children, month, OUT_DIR)
    print(f"[CSV] {csv_path}  （{len(children)} 児童）")

    md_dir = OUT_DIR / "monthly" / month
    for name, cls, s in children:
        write_child_md(name, cls, s, month, md_dir)
    print(f"[Markdown] {md_dir}  （{len(children)} ファイル）")

    con.close()
    print("完了。")


if __name__ == "__main__":
    main()
