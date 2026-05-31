# build_daily_report.py
# -*- coding: utf-8 -*-
"""
連絡帳パイプライン（本番・第1段）: PDF → Gemini 3.1 Flash-Lite でJSON抽出
→ 名簿照合 → SQLite登録（UPSERT）→ 日次報告CSV出力。

レイアウト（日次CSV 1行=1児童×1日）:
  児童名 | クラス | 日付 | 要確認 | 休早退 |
  就寝 | 起床 | 夜間睡眠 | 昼寝開始 | 昼寝終了 | 昼寝時間 |
  体温(家) | 体温(園午前) | 体温(園午後) |
  夕食 | 朝食 | 園食事 |
  排便(家) | 便(家) | 排便(園) | 便(園) |
  保護者コメント | 保育者コメント

設計メモ:
  - 使用モデル: gemini-3.1-flash-lite（押し切り方針）。
  - 食事量は文字のまま（旺盛/普通/あまりなし/なし）。
  - コメントはセル内改行を保持（Excelで読める）。
  - フラグ（要確認・休早退）は ○ / 空欄。
  - 重複登録は (child_id, entry_date) で UPSERT 上書き（再スキャン時に読み直せる）。
  - 名簿照合が要確認(confident=False)でも登録はする（要確認列に○）。誤紐付け防止は人の点検で。

依存: google-genai, pdf2image, pillow, openpyxl, jaconv, rapidfuzz
同フォルダに entry_schema.py, roster_match.py が必要。

使い方:
  $env:GEMINI_API_KEY="..."
  python build_daily_report.py --pdf "C:\\test\\20260528どんぐり　家庭での生活.pdf" \\
      --roster "C:\\test\\在園児各月児童名簿_令和8年度.xlsx"
  # ページ指定 / 既存JSON再利用も可
  python build_daily_report.py --pdf "...pdf" --roster "...xlsx" --pages 1,6,7,11
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import os
import re
import sqlite3
import time
from pathlib import Path
from typing import Any, Optional

try:
    from entry_schema import ENTRY_SCHEMA, EXTRACTION_PROMPT, absence_flag
    import roster_match as rm
except ModuleNotFoundError as e:
    missing = e.name
    if missing in ("entry_schema", "roster_match"):
        raise SystemExit(f"{missing}.py を同じフォルダに置いてください。")
    raise SystemExit(
        f"依存パッケージ '{missing}' が見つかりません。\n"
        f"  pip install jaconv rapidfuzz openpyxl\n"
        f"を実行してください（不足: {missing}）。"
    )


MODEL = "gemini-3.1-flash-lite"
INPUT_USD_PER_MTOK = 0.25
OUTPUT_USD_PER_MTOK = 1.50
MAX_OUTPUT_TOKENS = 4096
DEFAULT_DPI = 220
DEFAULT_MAX_LONG_EDGE = 2000

DB_PATH = Path("renrakucho.db")
OUT_DIR = Path("_reports")


def date_from_filename(name: str) -> Optional[dt.date]:
    """ファイル名の先頭 YYYYMMDD を日付として返す。例: '20260526どんぐり….pdf' -> 2026-05-26。
    1PDF=1日が前提。手書き日付欄のOCR誤読に左右されないよう、これを正の日付とする。"""
    m = re.match(r"(\d{4})(\d{2})(\d{2})", Path(name).name)
    if not m:
        return None
    y, mo, d = map(int, m.groups())
    try:
        return dt.date(y, mo, d)
    except ValueError:
        return None


# =============================================================================
# 睡眠時間計算
# =============================================================================

def _parse_hhmm(s: Optional[str]) -> Optional[int]:
    if not s:
        return None
    try:
        h, m = map(int, str(s).split(":"))
    except Exception:
        return None
    if not (0 <= h <= 23 and 0 <= m <= 59):  # 不正な時刻（誤読の25:00等）を弾く
        return None
    return h * 60 + m


def sleep_minutes(start: Optional[str], end: Optional[str]) -> Optional[int]:
    """HH:MM→睡眠分。end<startなら日付またぎ。異常値はNone。"""
    s = _parse_hhmm(start)
    e = _parse_hhmm(end)
    if s is None or e is None:
        return None
    if e < s:
        e += 24 * 60
    diff = e - s
    if diff <= 0 or diff > 20 * 60:
        return None
    return diff


def fmt_minutes(mins: Optional[int]) -> str:
    if mins is None:
        return ""
    return f"{mins // 60}時間{mins % 60:02d}分"


# =============================================================================
# Gemini 抽出
# =============================================================================

def get_client():
    from google import genai
    key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not key:
        raise SystemExit("GEMINI_API_KEY を設定してください。")
    return genai.Client(api_key=key)


def render_pdf(pdf_path: Path, pages: Optional[list[int]]) -> list[tuple[int, bytes]]:
    from pdf2image import convert_from_path
    from PIL import Image
    import io
    imgs = convert_from_path(str(pdf_path), dpi=DEFAULT_DPI)
    out = []
    for idx, im in enumerate(imgs, start=1):
        if pages and idx not in pages:
            continue
        im = im.convert("RGB")
        w, h = im.size
        le = max(w, h)
        if le > DEFAULT_MAX_LONG_EDGE:
            sc = DEFAULT_MAX_LONG_EDGE / le
            im = im.resize((int(w * sc), int(h * sc)), Image.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=95)
        out.append((idx, buf.getvalue()))
    return out


def extract_json(client, image_bytes: bytes) -> dict[str, Any]:
    from google.genai import types as genai_types
    image_part = genai_types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg")
    cfg: dict[str, Any] = {
        "max_output_tokens": MAX_OUTPUT_TOKENS,
        "temperature": 0.0,
        "response_mime_type": "application/json",
        "response_schema": ENTRY_SCHEMA,
    }
    try:
        cfg["thinking_config"] = genai_types.ThinkingConfig(thinking_level="low")
    except Exception:
        pass

    started = time.time()
    try:
        resp = client.models.generate_content(
            model=MODEL, contents=[image_part, EXTRACTION_PROMPT],
            config=genai_types.GenerateContentConfig(**cfg))
    except Exception:
        cfg2 = {k: v for k, v in cfg.items() if k != "thinking_config"}
        resp = client.models.generate_content(
            model=MODEL, contents=[image_part, EXTRACTION_PROMPT],
            config=genai_types.GenerateContentConfig(**cfg2))
    elapsed = time.time() - started

    usage = getattr(resp, "usage_metadata", None)
    in_tok = getattr(usage, "prompt_token_count", None)
    out_tok = getattr(usage, "candidates_token_count", None)
    th_tok = getattr(usage, "thoughts_token_count", None)
    cost = None
    if in_tok is not None and out_tok is not None:
        cost = in_tok / 1e6 * INPUT_USD_PER_MTOK + (out_tok + (th_tok or 0)) / 1e6 * OUTPUT_USD_PER_MTOK

    raw = getattr(resp, "text", None) or ""
    try:
        data = json.loads(raw)
    except Exception as e:
        data = None
    return {"data": data, "cost": cost, "elapsed": elapsed, "raw": raw}


# =============================================================================
# DB
# =============================================================================

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS entries (
  child_kanji TEXT, child_kana TEXT, class_name TEXT,
  entry_date  TEXT NOT NULL,
  match_score REAL, match_confident INTEGER,
  source_pdf TEXT, source_page INTEGER,
  sleep_home_start TEXT, sleep_home_end TEXT, sleep_home_min INTEGER,
  nap_start TEXT, nap_end TEXT, nap_min INTEGER,
  temp_home REAL, temp_en_am REAL, temp_en_pm REAL,
  meal_dinner TEXT, meal_breakfast TEXT, meal_en TEXT,
  meal_dinner_text TEXT, meal_breakfast_text TEXT, meal_en_text TEXT,
  stool_present_home INTEGER, stool_type_home TEXT,
  stool_present_en INTEGER, stool_type_en TEXT,
  comment_home TEXT, comment_en TEXT,
  uncertain_notes TEXT,
  absence_notice INTEGER, absence_hits TEXT,
  created_at TEXT,
  PRIMARY KEY (child_kana, entry_date)
);
"""


def db_connect() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH)
    con.execute(SCHEMA_SQL)
    return con


def upsert_entry(con: sqlite3.Connection, row: dict[str, Any]) -> None:
    cols = list(row.keys())
    placeholders = ",".join("?" for _ in cols)
    updates = ",".join(f"{c}=excluded.{c}" for c in cols if c not in ("child_kana", "entry_date"))
    sql = (f"INSERT INTO entries ({','.join(cols)}) VALUES ({placeholders}) "
           f"ON CONFLICT(child_kana, entry_date) DO UPDATE SET {updates}")
    con.execute(sql, [row[c] for c in cols])
    con.commit()


# =============================================================================
# 1ページ処理
# =============================================================================

def process_page(client, roster_xlsx: str, image_bytes: bytes,
                 source_pdf: str, page_num: int,
                 roster_cache: dict,
                 default_year: Optional[int] = None,
                 aliases: Optional[dict] = None,
                 file_date: Optional[dt.date] = None) -> Optional[dict[str, Any]]:
    ext = extract_json(client, image_bytes)
    d = ext["data"]
    if not d:
        print(f"  page{page_num}: ★JSON取得失敗 raw先頭={ext['raw'][:80]!r}")
        return None

    # 日付の決定: ファイル名の日付(YYYYMMDD)を正とする。中身OCRの日付は補助・照合用。
    ocr_date = rm.extract_date_from_md(d.get("entry_date_raw") or "", default_year=default_year)
    date_obj = file_date or ocr_date
    if file_date and ocr_date and file_date != ocr_date:
        print(f"    [日付] ファイル名={file_date} ≠ 中身OCR={ocr_date} → ファイル名を採用 "
              f"(raw={d.get('entry_date_raw')!r})")
    sheet = rm.month_sheet_for_date(date_obj) if date_obj else None

    # 名簿照合（月シート単位でキャッシュ）
    matched, score, confident, matched_by = None, 0.0, False, "none"
    if not sheet:
        print(f"    [照合スキップ] 日付が解釈できず月シート未確定 (entry_date_raw={d.get('entry_date_raw')!r})")
    else:
        if sheet not in roster_cache:
            try:
                roster_cache[sheet] = rm.load_roster(roster_xlsx, sheet)
                print(f"    [名簿] {sheet}: {len(roster_cache[sheet])}名 読込")
            except Exception as exc:
                print(f"    [名簿エラー] {sheet} の読込に失敗: {type(exc).__name__}: {exc}")
                roster_cache[sheet] = []
        roster = roster_cache[sheet]
        if not roster:
            print(f"    [照合スキップ] {sheet} の名簿が空")
        elif not d.get("child_name"):
            print(f"    [照合スキップ] OCRが児童名を取得できず")
        else:
            res = rm.match_child(d["child_name"], roster, aliases=aliases)
            matched, score, confident, matched_by = res.child, res.score, res.confident, res.matched_by
            if matched_by == "alias":
                print(f"    [別名] OCR名={d['child_name']!r} -> {res.child.name_kanji}（辞書）")
            elif not confident:
                cand = f"{res.child.name_kanji}/{res.child.name_kana}" if res.child else "なし"
                print(f"    [要確認] OCR名={d['child_name']!r} 最有力={cand} score={score:.0f} ({res.reason})")

    # 確定(confident)した時だけ正式名を採用する。
    # 要確認の時は最有力候補名を入れない（誤った子の名で登録する事故を防ぐ）。
    # 読み取り名のまま残し、人が後で原本確認して修正する運用。
    if confident and matched:
        out_kanji = matched.name_kanji
        out_kana = matched.name_kana
        out_class = matched.class_name
    else:
        raw = d.get("child_name") or ""
        out_kanji = raw
        # 要確認の行が (空名, 日付) で互いに衝突して上書きし合うのを防ぐため、
        # かなキーに source とページを混ぜてユニーク性を確保する。
        out_kana = raw or ""
        out_kana = f"_要確認_{out_kana}_{source_pdf}_p{page_num}"
        out_class = ""

    sh_min = sleep_minutes(d.get("sleep_home_start"), d.get("sleep_home_end"))
    nap_min = sleep_minutes(d.get("nap_start"), d.get("nap_end"))
    af = absence_flag(d.get("comment_home"))

    row = {
        "child_kanji": out_kanji,
        "child_kana":  out_kana,
        "class_name":  out_class,
        "entry_date":  date_obj.isoformat() if date_obj else (d.get("entry_date_raw") or f"_unknown_p{page_num}"),
        "match_score": round(score, 1),
        "match_confident": 1 if confident else 0,
        "source_pdf": source_pdf, "source_page": page_num,
        "sleep_home_start": d.get("sleep_home_start"), "sleep_home_end": d.get("sleep_home_end"),
        "sleep_home_min": sh_min,
        "nap_start": d.get("nap_start"), "nap_end": d.get("nap_end"), "nap_min": nap_min,
        "temp_home": d.get("temp_home"), "temp_en_am": d.get("temp_en_am"), "temp_en_pm": d.get("temp_en_pm"),
        "meal_dinner": d.get("meal_dinner"), "meal_breakfast": d.get("meal_breakfast"), "meal_en": d.get("meal_en"),
        "meal_dinner_text": d.get("meal_dinner_text"), "meal_breakfast_text": d.get("meal_breakfast_text"),
        "meal_en_text": d.get("meal_en_text"),
        "stool_present_home": _b(d.get("stool_present_home")), "stool_type_home": d.get("stool_type_home"),
        "stool_present_en": _b(d.get("stool_present_en")), "stool_type_en": d.get("stool_type_en"),
        "comment_home": d.get("comment_home"), "comment_en": d.get("comment_en"),
        "uncertain_notes": d.get("uncertain_notes"),
        "absence_notice": 1 if af["absence_notice"] else 0,
        "absence_hits": ",".join(af["absence_hits"]),
        "created_at": dt.datetime.now().isoformat(timespec="seconds"),
    }
    row["_cost"] = ext["cost"]
    return row


def _b(v):
    if v is None:
        return None
    return 1 if v else 0


# =============================================================================
# 日次CSV出力
# =============================================================================

CSV_HEADER = [
    "児童名", "クラス", "日付", "要確認", "休早退",
    "就寝", "起床", "夜間睡眠", "昼寝開始", "昼寝終了", "昼寝時間",
    "体温(家)", "体温(園午前)", "体温(園午後)",
    "夕食", "朝食", "園食事",
    "排便(家)", "排便(園)",
    "保護者コメント", "保育者コメント", "要確認メモ",
]


def _stool(present, typ):
    if present is None:
        return ""
    base = "有" if present else "無"
    return f"{base}/{typ}" if (present and typ) else base


def fetch_date_rows(con: sqlite3.Connection, entry_date: str) -> list[dict[str, Any]]:
    """指定日の全行をDBから取得（クラス混在でも全件）。日次CSVを上書きでなく総覧で再生成するため。"""
    con.row_factory = sqlite3.Row
    cur = con.execute("SELECT * FROM entries WHERE entry_date = ?", (entry_date,))
    return [dict(r) for r in cur.fetchall()]


def write_daily_csv(rows: list[dict[str, Any]], entry_date: str, out_dir: Path) -> Path:
    out_dir.mkdir(exist_ok=True)
    path = out_dir / f"日次報告_{entry_date}.csv"
    # クラス→児童名でソート
    rows = sorted(rows, key=lambda r: (r.get("class_name", ""), r.get("child_kana", "")))
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(CSV_HEADER)
        for r in rows:
            w.writerow([
                r["child_kanji"], r["class_name"], r["entry_date"],
                "" if r["match_confident"] else "○",
                "○" if r["absence_notice"] else "",
                r.get("sleep_home_start") or "", r.get("sleep_home_end") or "",
                fmt_minutes(r.get("sleep_home_min")),
                r.get("nap_start") or "", r.get("nap_end") or "", fmt_minutes(r.get("nap_min")),
                r.get("temp_home") or "", r.get("temp_en_am") or "", r.get("temp_en_pm") or "",
                r.get("meal_dinner") or "", r.get("meal_breakfast") or "", r.get("meal_en") or "",
                _stool(r.get("stool_present_home"), r.get("stool_type_home")),
                _stool(r.get("stool_present_en"), r.get("stool_type_en")),
                r.get("comment_home") or "", r.get("comment_en") or "",
                r.get("uncertain_notes") or "",
            ])
    return path


def load_aliases(path: Optional[str]) -> dict:
    """別名辞書JSON {別名: 名簿かな氏名} を読む。無ければ空。"""
    if not path:
        # 既定で alias.json があれば自動で読む
        default = Path("alias.json")
        if default.exists():
            path = str(default)
        else:
            return {}
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if isinstance(data, dict):
            print(f"  [別名辞書] {path}: {len(data)}件 読込")
            return data
        print(f"  [別名辞書] {path} はオブジェクト形式ではないため無視")
        return {}
    except Exception as exc:
        print(f"  [別名辞書] 読込失敗 {path}: {exc}")
        return {}


def main() -> None:
    ap = argparse.ArgumentParser(description="連絡帳→Flash-Lite抽出→照合→DB→日次CSV")
    ap.add_argument("--pdf", required=True)
    ap.add_argument("--roster", required=True, help="名簿xlsxパス")
    ap.add_argument("--pages", help="ページ番号 カンマ区切り。未指定で全ページ")
    ap.add_argument("--aliases", help="別名辞書JSONパス（既定: alias.json があれば自動）")
    ap.add_argument("--year", type=int, default=dt.date.today().year,
                    help="連絡帳に年がない場合に補う年（既定: 実行日の年）")
    args = ap.parse_args()

    pages = [int(x) for x in args.pages.split(",")] if args.pages else None
    pdf_path = Path(args.pdf)
    if not pdf_path.exists():
        raise SystemExit(f"PDF不在: {pdf_path}")

    client = get_client()
    con = db_connect()
    roster_cache: dict = {}
    aliases = load_aliases(args.aliases)

    file_date = date_from_filename(pdf_path.name)
    items = render_pdf(pdf_path, pages)
    fd_msg = f"ファイル名日付={file_date}" if file_date else "ファイル名に日付なし→中身OCRを使用"
    print(f"モデル: {MODEL} / {len(items)} ページ処理 / {fd_msg} / 年補完={args.year}")

    rows = []
    total_cost = 0.0
    for page_num, img in items:
        row = process_page(client, args.roster, img, pdf_path.name, page_num,
                           roster_cache, default_year=args.year, aliases=aliases,
                           file_date=file_date)
        if not row:
            continue
        total_cost += row.pop("_cost", 0.0) or 0.0
        upsert_entry(con, row)
        rows.append(row)
        flag = "★要確認" if not row["match_confident"] else "OK"
        ab = "休早退" if row["absence_notice"] else ""
        print(f"  p{page_num}: {row['child_kanji']}({row['class_name']}) "
              f"{row['entry_date']} 睡眠{fmt_minutes(row['sleep_home_min'])} [{flag}]{ab}")

    # 日次CSVは「今回のPDF分」ではなくDBの当日全件で再生成する。
    # 同じ日付にきいちご/どんぐりの2枚があると、PDF単位の上書きでは後勝ちで片方が消えるため。
    affected_dates = sorted({r["entry_date"] for r in rows})
    for date in affected_dates:
        drows = fetch_date_rows(con, date)
        p = write_daily_csv(drows, date, OUT_DIR)
        print(f"  CSV: {p}（当日DB {len(drows)}件）")

    print(f"\n完了。DB: {DB_PATH.resolve()}  概算コスト: ${total_cost:.4f}")


if __name__ == "__main__":
    main()
