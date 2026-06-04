# send_report.py
# -*- coding: utf-8 -*-
"""
連絡帳パイプライン（配信段）: renrakucho.db から日次/月次レポートを作り、
Gmail 向けに最適化した HTML メールで送る。

Gmail最適化:
  - 文字装飾・表は各タグに inline CSS（Gmailは <style> を一部削るため）。
  - multipart/alternative で HTML＋プレーンテキスト併送。

添付:
  - 日次: その日の原本PDF（DBの source_pdf）。ディスクに在るものだけ添付し、
          無いものは本文に「原本見つからず」と注記する（後で原本確認できるように）。
  - 月次: 原本PDFは添付しない（サマリ表のみ）。

認証情報はチャット/コードに書かない。環境変数から読む:
  GMAIL_USER          送信元アドレス（既定: hikarinomorirenraku@gmail.com）
  GMAIL_APP_PASSWORD  Gmailアプリパスワード（2段階認証→アプリパスワードで発行）
  RECIPIENTS          宛先（カンマ区切り。--to で上書き可。既定: 送信元と同じ）

実行例:
  # まず送らずに見え方だけ確認（HTMLをファイルに書き出す。認証情報不要）
  .venv/Scripts/python.exe send_report.py daily   --date 2026-05-29 --dry-run
  .venv/Scripts/python.exe send_report.py monthly --month 2026-05  --dry-run
  # 本送信（要 GMAIL_APP_PASSWORD）
  $env:GMAIL_APP_PASSWORD="xxxxxxxxxxxxxxxx"
  .venv/Scripts/python.exe send_report.py daily --date 2026-05-29 --to me@example.com
"""

from __future__ import annotations

import argparse
import os
import shutil
import smtplib
import sqlite3
import subprocess
import tempfile
from collections import defaultdict
from email.message import EmailMessage
from html import escape
from pathlib import Path
from typing import Optional

from build_daily_report import DB_PATH, OUT_DIR, fmt_minutes
from build_daily_md import _meal, _stool
from build_daily_md import _t as _td  # 日次用: Noneは "-"
from build_monthly_report import (
    FEVER_C, SLEEP_SHORT_RATIO, SUMMARY_HEADER, _fm, latest_month, load_month,
    summarize_child,
)
from build_monthly_report import _t as _tm  # 月次用: Noneは ""

DEFAULT_ADDR = "hikarinomorirenraku@gmail.com"
SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587

# Gmail向けインラインCSS断片
TD = 'style="border:1px solid #ccc;padding:4px 8px;font-size:13px;"'
TH = 'style="border:1px solid #ccc;padding:4px 8px;font-size:13px;background:#f0f4f8;text-align:left;"'
TABLE = 'style="border-collapse:collapse;margin:6px 0;"'
CARD = 'style="border:1px solid #ddd;border-radius:6px;padding:10px 14px;margin:8px 0;"'
LABEL = 'style="color:#557;font-weight:bold;"'


# ---------------------------------------------------------------------------
# 共通
# ---------------------------------------------------------------------------

def find_browser() -> str:
    """HTML→PDF変換に使う Edge/Chrome を探す。BROWSER_PATH で明示指定も可。"""
    env = os.environ.get("BROWSER_PATH")
    if env and Path(env).exists():
        return env
    cands = [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    ]
    for c in cands:
        if Path(c).exists():
            return c
    raise SystemExit("PDF変換用のブラウザ(Edge/Chrome)が見つかりません。"
                     "BROWSER_PATH 環境変数で実行ファイルを指定してください。")


def html_to_pdf(html: str) -> bytes:
    """HTML文字列を Edge/Chrome のヘッドレス印刷でPDFバイト列に変換する。
    日本語フォント・表のCSSはブラウザがそのまま描画するので追加依存なし。"""
    browser = find_browser()
    tmp = Path(tempfile.mkdtemp(prefix="renraku_pdf_"))
    try:
        src = tmp / "in.html"
        out = tmp / "out.pdf"
        src.write_text(html, encoding="utf-8")
        # --no-sandbox: Linuxコンテナ(root実行)のchromiumは必須。Windows Edge/Chromeでは無害。
        cmd = [browser, "--headless", "--no-sandbox", "--disable-gpu", "--no-pdf-header-footer",
               f"--print-to-pdf={out}", src.as_uri()]
        r = subprocess.run(cmd, capture_output=True, timeout=120)
        if not out.exists():
            raise SystemExit(f"PDF変換に失敗しました（{Path(browser).name}）。\n"
                             f"{r.stderr.decode('utf-8', 'ignore')[:500]}")
        return out.read_bytes()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _con() -> sqlite3.Connection:
    if not DB_PATH.exists():
        raise SystemExit(f"DB不在: {DB_PATH}")
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def _load_date(con, date: str) -> list[dict]:
    rows = con.execute(
        "SELECT * FROM entries WHERE entry_date = ? ORDER BY class_name, child_kana", (date,)
    )
    return [dict(r) for r in rows]


DEFAULT_SCAN_DIR = r"C:\Users\hikar\光の森保育園 Dropbox\光の森保育園\ScanSnap"


def _find_source_pdf(name_or_path: str) -> Optional[Path]:
    """原本PDFを探す。DBにはファイル名だけ入っている前提。
    1) そのまま(フルパス/CWD相対) 2) スキャン保存フォルダをベース名で探索。
    保存フォルダは環境変数 SCAN_DIR で上書き（本番=TrueNASのマウント先を指定する）。"""
    p = Path(name_or_path)
    if p.exists():
        return p
    base = Path(name_or_path).name
    cand = Path(os.environ.get("SCAN_DIR", DEFAULT_SCAN_DIR)) / base
    return cand if cand.exists() else None


def _row_class(r: dict) -> str:
    """行のクラスを返す。確定行はclass_name。要確認(空)は元PDFファイル名から推定。
    どちらとも判別できなければ '（クラス未確定）'。"""
    c = r.get("class_name")
    if c:
        return c
    src = r.get("source_pdf") or ""
    if "きいちご" in src:
        return "きいちご"
    if "どんぐり" in src:
        return "どんぐり"
    return "（クラス未確定）"


def _latest_date(con) -> Optional[str]:
    r = con.execute(
        "SELECT entry_date FROM entries WHERE entry_date LIKE '____-__-%' "
        "ORDER BY entry_date DESC LIMIT 1"
    ).fetchone()
    return r[0] if r else None


# ---------------------------------------------------------------------------
# 日次 HTML
# ---------------------------------------------------------------------------

def daily_html(date: str, rows: list[dict], attached: list[str], missing: list[str]) -> tuple[str, str]:
    by_class: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_class[r.get("class_name") or "（クラス未確定）"].append(r)
    n_un = sum(1 for r in rows if not r.get("match_confident"))
    n_ab = sum(1 for r in rows if r.get("absence_notice"))
    classes = "・".join(sorted(c for c in by_class if c != "（クラス未確定）")) or "—"

    H = [f'<div style="font-family:sans-serif;color:#222;max-width:760px;">']
    H.append(f'<h2 style="margin:0 0 4px;">{escape(date)} 日次報告（{escape(classes)}）</h2>')
    H.append(f'<p style="margin:0 0 4px;color:#555;">対象 {len(rows)} 名 ・ 要確認 {n_un} ・ お休み/早退 {n_ab}</p>')
    if missing:
        H.append('<p style="color:#a00;font-size:12px;">⚠ 原本PDFが見つからず未添付: '
                 + escape(", ".join(missing)) + '</p>')

    for cls in sorted(by_class):
        H.append(f'<h3 style="margin:14px 0 4px;border-bottom:2px solid #88a;">{escape(cls)}</h3>')
        for r in sorted(by_class[cls], key=lambda x: x.get("child_kana") or ""):
            flags = []
            if not r.get("match_confident"):
                flags.append('<span style="color:#a00;">⚠要確認</span>')
            if r.get("absence_notice"):
                flags.append('<span style="color:#a60;">休/早退</span>')
            flag = ("　" + " ".join(flags)) if flags else ""
            name = escape(r.get("child_kanji") or r.get("child_kana") or "（名称不明）")
            H.append(f'<div {CARD}>')
            H.append(f'<div style="font-size:15px;font-weight:bold;">{name}{flag}</div>')

            nap = ""
            if r.get("nap_min") is not None or r.get("nap_start"):
                span = f"（{r.get('nap_start')}〜{r.get('nap_end') or ''}）" if r.get("nap_start") else ""
                nap = f" ・ 昼寝 {escape(fmt_minutes(r.get('nap_min')))}{escape(span)}"
            H.append(f'<table {TABLE}>')
            H.append(f'<tr><td {TD}><span {LABEL}>睡眠</span></td><td {TD}>'
                     f'就寝 {escape(r.get("sleep_home_start") or "-")} / 起床 {escape(r.get("sleep_home_end") or "-")} / '
                     f'夜間 {escape(fmt_minutes(r.get("sleep_home_min")) or "-")}{nap}</td></tr>')
            H.append(f'<tr><td {TD}><span {LABEL}>体温</span></td><td {TD}>'
                     f'家 {_td(r.get("temp_home"))} / 園午前 {_td(r.get("temp_en_am"))} / 園午後 {_td(r.get("temp_en_pm"))}</td></tr>')
            H.append(f'<tr><td {TD}><span {LABEL}>食事</span></td><td {TD}>'
                     f'夕 {escape(_meal(r.get("meal_dinner"), r.get("meal_dinner_text")))} / '
                     f'朝 {escape(_meal(r.get("meal_breakfast"), r.get("meal_breakfast_text")))} / '
                     f'園 {escape(_meal(r.get("meal_en"), r.get("meal_en_text")))}</td></tr>')
            H.append(f'<tr><td {TD}><span {LABEL}>排便</span></td><td {TD}>'
                     f'家 {escape(_stool(r.get("stool_present_home"), r.get("stool_type_home")))} / '
                     f'園 {escape(_stool(r.get("stool_present_en"), r.get("stool_type_en")))}</td></tr>')
            H.append('</table>')
            ch = (r.get("comment_home") or "").strip()
            ce = (r.get("comment_en") or "").strip()
            if ch:
                H.append(f'<p style="margin:2px 0;"><span {LABEL}>保護者:</span> {escape(ch)}</p>')
            if ce:
                H.append(f'<p style="margin:2px 0;"><span {LABEL}>保育者:</span> {escape(ce)}</p>')
            un = (r.get("uncertain_notes") or "").strip()
            if un:
                H.append(f'<p style="margin:2px 0;color:#777;font-size:12px;">📝 {escape(un)}</p>')
            H.append('</div>')
    H.append('</div>')

    text = [f"{date} 日次報告（{classes}）",
            f"対象 {len(rows)}名 / 要確認 {n_un} / 休早退 {n_ab}",
            "HTML対応メーラーで整形表示されます。"]
    if missing:
        text.append("原本PDF未添付: " + ", ".join(missing))
    return "\n".join(H), "\n".join(text)


# ---------------------------------------------------------------------------
# 月次 HTML
# ---------------------------------------------------------------------------

def monthly_html(month: str, children: list[tuple[str, str, dict]]) -> tuple[str, str]:
    H = [f'<div style="font-family:sans-serif;color:#222;">']
    H.append(f'<h2 style="margin:0 0 6px;">{escape(month)} 月次サマリ（{len(children)} 児童）</h2>')
    H.append(f'<table {TABLE}>')
    H.append('<tr>' + "".join(f'<th {TH}>{escape(h)}</th>' for h in SUMMARY_HEADER) + '</tr>')
    for name, cls, s in children:
        sl, nap, th = s["sleep"], s["nap"], s["temp_home"]
        cells = [
            name, cls, str(s["record_days"]), str(len(s["uncertain_days"])),
            _fm(sl, "avg"), _fm(sl, "min"), _fm(sl, "max"), _fm(sl, "sd"),
            _fm(nap, "avg"), _fm(nap, "min"), _fm(nap, "max"),
            _tm(th["avg"]), _tm(th["max"]), str(len(s["fever_days"])),
            str(s["stool_home_days"]), str(s["stool_en_days"]),
            str(len(s["absence_days"])), " ".join(s["absence_days"]),
        ]
        H.append('<tr>' + "".join(f'<td {TD}>{escape(c)}</td>' for c in cells) + '</tr>')
    H.append('</table>')
    H.append(f'<p style="color:#777;font-size:12px;">発熱ライン={FEVER_C}℃。睡眠ブレ幅(±)は標準偏差。'
             '気になる児童は児童別Markdown（_reports/monthly/）と原本PDFで確認してください。</p>')
    H.append('</div>')
    text = [f"{month} 月次サマリ（{len(children)}児童）",
            "HTML対応メーラーで表が整形表示されます。",
            "各児童の睡眠・体温の日別推移とコメント履歴は添付HTML（月次詳細）をご覧ください。"]
    return "\n".join(H), "\n".join(text)


def monthly_detail_html(month: str, children: list[tuple[str, str, dict]]) -> str:
    """全児童の詳細（睡眠・体温の日別推移＋コメント履歴）を1つにまとめた独立HTML文書。
    メール添付用。ダブルクリックでブラウザに整形表示される。"""
    D = ['<!DOCTYPE html><html lang="ja"><head><meta charset="utf-8">',
         f'<title>{escape(month)} 月次詳細</title></head>',
         '<body style="font-family:sans-serif;color:#222;max-width:820px;margin:16px auto;">']
    D.append(f'<h1 style="border-bottom:3px solid #88a;">{escape(month)} 月次詳細（{len(children)} 児童）</h1>')
    # 目次
    D.append('<p style="font-size:13px;color:#557;">児童: '
             + " ・ ".join(escape(n) for n, _, _ in children) + '</p>')

    for name, cls, s in children:
        sl, nap, th = s["sleep"], s["nap"], s["temp_home"]
        short_line = (sl["avg"] * SLEEP_SHORT_RATIO) if sl["avg"] is not None else None
        D.append(f'<h2 style="margin:20px 0 4px;border-bottom:2px solid #ccd;">{escape(name)}'
                 f'（{escape(cls)}）</h2>')
        line = f'記録 {s["record_days"]} 日'
        if s["uncertain_days"]:
            line += f'　<span style="color:#a00;">⚠要確認 {len(s["uncertain_days"])} 日</span>'
        D.append(f'<p style="margin:2px 0;color:#555;">{line}</p>')

        # 睡眠
        D.append('<h3 style="margin:10px 0 2px;">睡眠</h3>')
        if sl["avg"] is not None:
            D.append(f'<p style="margin:2px 0;">夜間睡眠 平均 <b>{escape(fmt_minutes(round(sl["avg"])))}</b>'
                     f'（最短 {escape(fmt_minutes(round(sl["min"])))} 〜 最長 {escape(fmt_minutes(round(sl["max"])))}、'
                     f'ブレ幅 ±{escape(fmt_minutes(round(sl["sd"])))}）</p>')
        if nap["avg"] is not None:
            D.append(f'<p style="margin:2px 0;">昼寝 平均 {escape(fmt_minutes(round(nap["avg"])))}'
                     f'（最短 {escape(fmt_minutes(round(nap["min"])))} 〜 最長 {escape(fmt_minutes(round(nap["max"])))}）</p>')
        D.append(f'<table {TABLE}><tr>'
                 + "".join(f'<th {TH}>{h}</th>' for h in ["日付", "就寝", "起床", "夜間睡眠", "昼寝", "印"])
                 + '</tr>')
        for r in s["rows"]:
            m = r.get("sleep_home_min")
            mark = "🔻短" if (short_line is not None and m is not None and m < short_line) else ""
            D.append('<tr>' + "".join(f'<td {TD}>{escape(str(c))}</td>' for c in [
                r["entry_date"], r.get("sleep_home_start") or "", r.get("sleep_home_end") or "",
                fmt_minutes(m), fmt_minutes(r.get("nap_min")), mark]) + '</tr>')
        D.append('</table>')

        # 体温
        D.append('<h3 style="margin:10px 0 2px;">体温</h3>')
        if s["fever_days"]:
            D.append(f'<p style="margin:2px 0;color:#a00;">🌡 {FEVER_C}℃以上: '
                     f'{len(s["fever_days"])} 日（{escape(", ".join(s["fever_days"]))}）</p>')
        D.append(f'<table {TABLE}><tr>'
                 + "".join(f'<th {TH}>{h}</th>' for h in ["日付", "体温(家)", "園午前", "園午後"])
                 + '</tr>')
        for r in s["rows"]:
            D.append('<tr>' + "".join(f'<td {TD}>{c}</td>' for c in [
                escape(r["entry_date"]), _tm(r.get("temp_home")),
                _tm(r.get("temp_en_am")), _tm(r.get("temp_en_pm"))]) + '</tr>')
        D.append('</table>')

        # 排便・お休み
        D.append(f'<p style="margin:6px 0 2px;"><b>排便</b>: 家 {s["stool_home_days"]} 日 / '
                 f'園 {s["stool_en_days"]} 日</p>')
        ab = f'{len(s["absence_days"])} 日（{escape(", ".join(s["absence_days"]))}）' if s["absence_days"] else "なし"
        D.append(f'<p style="margin:2px 0;"><b>お休み・早退</b>: {ab}</p>')

        # コメント履歴
        D.append('<h3 style="margin:10px 0 2px;">コメント履歴</h3>')
        for r in s["rows"]:
            ch = (r.get("comment_home") or "").strip()
            ce = (r.get("comment_en") or "").strip()
            if not ch and not ce:
                continue
            D.append(f'<p style="margin:6px 0 0;font-weight:bold;color:#557;">{escape(r["entry_date"])}</p>')
            if ch:
                D.append(f'<p style="margin:1px 0;">保護者: {escape(ch)}</p>')
            if ce:
                D.append(f'<p style="margin:1px 0;">保育者: {escape(ce)}</p>')
    D.append('</body></html>')
    return "\n".join(D)


# ---------------------------------------------------------------------------
# メール組み立て・送信
# ---------------------------------------------------------------------------

def build_msg(sender: str, to: list[str], subject: str, html: str, text: str,
              attachments: list[tuple[str, str, str, bytes]]) -> EmailMessage:
    """attachments: (ファイル名, maintype, subtype, バイト列) のリスト。"""
    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = ", ".join(to)
    msg["Subject"] = subject
    msg.set_content(text)
    msg.add_alternative(html, subtype="html")
    for fn, maintype, subtype, data in attachments:
        msg.add_attachment(data, maintype=maintype, subtype=subtype, filename=fn)
    return msg


def send(msg: EmailMessage, sender: str) -> None:
    pw = os.environ.get("GMAIL_APP_PASSWORD")
    if not pw:
        raise SystemExit("GMAIL_APP_PASSWORD が未設定です（環境変数で渡してください）。--dry-run なら不要。")
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as s:
        s.starttls()
        s.login(sender, pw)
        s.send_message(msg)


def _dry_save(kind: str, key: str, html: str,
              attachments: list[tuple[str, str, str, bytes]], to: list[str], subject: str) -> Path:
    OUT_DIR.mkdir(exist_ok=True)
    path = OUT_DIR / f"email_preview_{kind}_{key}.html"
    path.write_text(html, encoding="utf-8")
    print(f"[dry-run] 本文プレビュー保存: {path}")
    # 添付も確認できるようファイルに書き出す（PDF=バイト, HTML=テキスト）
    for fn, maintype, subtype, data in attachments:
        if subtype in ("html", "pdf"):
            ap = OUT_DIR / f"email_attach_{kind}_{key}_{fn}"
            ap.write_bytes(data)
            print(f"          添付プレビュー保存: {ap}")
    print(f"          宛先: {', '.join(to)}")
    print(f"          件名: {subject}")
    print(f"          添付: {[fn for fn, *_ in attachments] or 'なし'}")
    return path


def main() -> None:
    ap = argparse.ArgumentParser(description="renrakucho.db → Gmail向けHTMLメール送信")
    ap.add_argument("kind", choices=["daily", "monthly"])
    ap.add_argument("--date", help="日次の対象日 YYYY-MM-DD（既定: DB最新日）")
    ap.add_argument("--month", help="月次の対象月 YYYY-MM（既定: DB最新月）")
    ap.add_argument("--to", help="宛先（カンマ区切り）。既定: RECIPIENTS環境変数 or 送信元")
    ap.add_argument("--dry-run", action="store_true", help="送信せずHTMLをファイルに書き出すだけ")
    args = ap.parse_args()

    sender = os.environ.get("GMAIL_USER", DEFAULT_ADDR)
    to_raw = args.to or os.environ.get("RECIPIENTS") or sender
    to = [a.strip() for a in to_raw.split(",") if a.strip()]

    con = _con()

    # 送信単位のリスト (key, subject, html, text, attachments)。
    # 日次は1通、月次はクラスごと（きいちご/どんぐり）に1通ずつ。
    sends: list[tuple[str, str, str, str, list[tuple[str, str, str, bytes]]]] = []

    if args.kind == "daily":
        date = args.date or _latest_date(con)
        if not date:
            raise SystemExit("対象日が決められません。")
        rows = _load_date(con, date)
        if not rows:
            raise SystemExit(f"{date} の行がありません。")
        # 日次もクラスごとに送る。クラス未確定(要確認)の行は、元PDFのファイル名から
        # どちらのクラスのスキャンかを推定して割り振り、点検が当該クラス側で行えるようにする。
        by_class: dict[str, list[dict]] = defaultdict(list)
        for r in rows:
            by_class[_row_class(r)].append(r)
        for cls in ("きいちご", "どんぐり"):
            cls_rows = by_class.get(cls, [])
            if not cls_rows:
                continue
            srcs = sorted({r.get("source_pdf") for r in cls_rows if r.get("source_pdf")})
            attachments = []
            missing = []
            for s in srcs:
                found = _find_source_pdf(s)
                if found:
                    attachments.append((found.name, "application", "pdf", found.read_bytes()))
                else:
                    missing.append(s)
            html, text = daily_html(date, cls_rows, [a[0] for a in attachments], missing)
            sends.append((f"{date}_{cls}", f"連絡帳 日次報告 {date}（{cls}）",
                          html, text, attachments))
    else:
        month = args.month or latest_month(con)
        if not month:
            raise SystemExit("対象月が決められません。")
        rows = load_month(con, month)
        if not rows:
            raise SystemExit(f"{month} の行がありません。")
        grouped: dict[str, list[dict]] = defaultdict(list)
        for r in rows:
            grouped[r["child_kana"]].append(r)
        children = [(c[0].get("child_kanji") or k, c[0].get("class_name") or "", summarize_child(c))
                    for k, c in grouped.items()]
        children.sort(key=lambda x: (x[1], x[0]))
        # クラスごとに分けて送信。月次は「傾向の振り返り」なので確定した児童のみ対象とし、
        # クラス未確定(要確認の断片)は月次メールには載せない（日次報告の要確認メモで点検する）。
        by_class: dict[str, list] = defaultdict(list)
        for ch in children:
            by_class[ch[1] or "その他"].append(ch)
        skipped = len(by_class.get("その他", []))
        if skipped:
            print(f"[注記] クラス未確定（要確認）{skipped}件は月次メールから除外（日次の要確認メモで点検）")
        for cls in ("きいちご", "どんぐり"):
            cls_children = by_class.get(cls, [])
            if not cls_children:
                continue
            html, text = monthly_html(f"{month}（{cls}）", cls_children)
            # 月次は原本PDFは添付しない。当クラスの詳細をPDF化して1つ添付。
            detail = monthly_detail_html(f"{month}（{cls}）", cls_children)
            attachments = [(f"月次詳細_{month}_{cls}.pdf", "application", "pdf", html_to_pdf(detail))]
            sends.append((f"{month}_{cls}", f"連絡帳 月次サマリ {month}（{cls}）",
                          html, text, attachments))

    con.close()

    for key, subject, html, text, attachments in sends:
        if args.dry_run:
            _dry_save(args.kind, key, html, attachments, to, subject)
            continue
        msg = build_msg(sender, to, subject, html, text, attachments)
        send(msg, sender)
        print(f"[送信完了] {subject} -> {', '.join(to)} （添付 {len(attachments)} 件）")
    if args.dry_run:
        return


if __name__ == "__main__":
    main()
