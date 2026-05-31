# watch_folder.py
# -*- coding: utf-8 -*-
"""
連絡帳パイプライン（自動化段）: 指定フォルダ（DropboxのScanSnap保存先）を監視し、
連絡帳PDFが追加されたら自動で取り込み→レポート生成（→任意で送信）まで回す。

対象ファイルの条件（すべて満たすもの）:
  - 拡張子 .pdf
  - ファイル名に「家庭での生活」を含む
  - ファイル名に「きいちご」または「どんぐり」を含む
  - ファイル名先頭が8桁の日付 YYYYMMDD（取り込みの正の日付に使う）
連絡帳以外のスキャンは無視する。

安全側の設計:
  - 既定は「取り込み＋レポート生成」まで。送信は --send を付けた時だけ（運用初期の確認用）。
  - Dropbox同期途中の半端ファイルを掴まないよう、サイズが安定してから処理する。
  - 既処理は状態ファイル(.watch_state.json)で管理。原本PDFは動かさない/消さない
    （後で原本確認・メール添付に使うため）。同名でもサイズが変われば再処理。
  - 取り込み失敗は数回までリトライし、それ以降はスキップ（APIコストの無駄打ち防止）。

実行:
  $env:GEMINI_API_KEY="..."          # 取り込みに必須
  .venv/Scripts/python.exe watch_folder.py            # 常駐監視（既定30秒間隔・送信なし）
  .venv/Scripts/python.exe watch_folder.py --once     # 1回だけ走査して終了（cron向き）
  .venv/Scripts/python.exe watch_folder.py --send     # 取り込み後に日次メールも送信
"""

from __future__ import annotations

import argparse
import datetime as dt
import glob
import json
import re
import subprocess
import sys
import time
from pathlib import Path

DEFAULT_DIR = r"C:\Users\hikar\光の森保育園 Dropbox\光の森保育園\ScanSnap"
STATE_FILE = Path(".watch_state.json")
MAX_ATTEMPTS = 3  # 取り込み失敗時の最大試行回数


def log(msg: str) -> None:
    print(f"{dt.datetime.now():%Y-%m-%d %H:%M:%S} | {msg}", flush=True)


def date_from_filename(name: str) -> str | None:
    """ファイル名先頭 YYYYMMDD を ISO日付文字列で返す。妥当でなければ None。"""
    m = re.match(r"(\d{4})(\d{2})(\d{2})", Path(name).name)
    if not m:
        return None
    y, mo, d = map(int, m.groups())
    try:
        return dt.date(y, mo, d).isoformat()
    except ValueError:
        return None


def is_target(name: str) -> bool:
    n = Path(name).name
    if not n.lower().endswith(".pdf"):
        return False
    if "家庭での生活" not in n:
        return False
    if ("きいちご" not in n) and ("どんぐり" not in n):
        return False
    return date_from_filename(n) is not None


def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            log(f"[警告] 状態ファイルが壊れています。新規作成します: {STATE_FILE}")
    return {}


def save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")


def is_stable(path: Path, wait: float) -> bool:
    """サイズが wait 秒変化しなければ安定とみなす（Dropbox同期途中の半端対策）。"""
    try:
        s1 = path.stat().st_size
    except FileNotFoundError:
        return False
    time.sleep(wait)
    try:
        s2 = path.stat().st_size
    except FileNotFoundError:
        return False
    return s1 == s2 and s2 > 0


def should_process(path: Path, state: dict) -> bool:
    name = path.name
    size = path.stat().st_size
    rec = state.get(name)
    if rec is None:
        return True
    if rec.get("size") != size:  # 中身が差し替わった → 再処理
        return True
    if rec.get("status") == "done":
        return False
    if rec.get("status") == "error" and rec.get("attempts", 0) >= MAX_ATTEMPTS:
        return False  # 何度も失敗 → 諦めてスキップ
    return rec.get("status") == "error"  # error かつ試行回数未満なら再挑戦


def run(cmd: list[str]) -> bool:
    """サブプロセス実行。成功(returncode 0)で True。出力は末尾だけ要約表示。"""
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        tail = (r.stderr or r.stdout or "").strip().splitlines()
        log("  [失敗] " + (tail[-1] if tail else f"returncode={r.returncode}"))
        return False
    return True


def process_file(path: Path, roster: str, do_send: bool) -> bool:
    date = date_from_filename(path.name)
    log(f"[取り込み] {path.name} (日付={date})")
    # 1) 本体パイプライン: PDF → 抽出 → 照合 → DB → 日次CSV
    if not run([sys.executable, "build_daily_report.py", "--pdf", str(path), "--roster", roster]):
        return False
    # 2) 日次の読み物Markdownを更新（DB読み取りのみ）
    run([sys.executable, "build_daily_md.py", "--date", date])
    # 3) 任意: 日次メール送信
    if do_send:
        if run([sys.executable, "send_report.py", "daily", "--date", date]):
            log(f"  [送信] 日次メール {date}")
    log(f"[完了] {path.name}")
    return True


def scan_once(watch_dir: Path, roster: str, stable_wait: float, do_send: bool, state: dict) -> int:
    processed = 0
    candidates = [p for p in sorted(watch_dir.glob("*.pdf")) if is_target(p.name)]
    for path in candidates:
        try:
            if not should_process(path, state):
                continue
            if not is_stable(path, stable_wait):
                log(f"[保留] 同期中の可能性 → 次回再確認: {path.name}")
                continue
            size = path.stat().st_size
            ok = process_file(path, roster, do_send)
            rec = state.get(path.name, {})
            attempts = rec.get("attempts", 0) + (0 if ok else 1)
            state[path.name] = {
                "size": size,
                "status": "done" if ok else "error",
                "attempts": attempts,
                "updated_at": dt.datetime.now().isoformat(timespec="seconds"),
            }
            save_state(state)
            if ok:
                processed += 1
            elif attempts >= MAX_ATTEMPTS:
                log(f"  [打ち切り] {path.name} は {MAX_ATTEMPTS} 回失敗。以降スキップします。")
        except Exception as exc:
            log(f"  [例外] {path.name}: {type(exc).__name__}: {exc}")
    return processed


def find_roster(arg: str | None) -> str:
    if arg:
        return arg
    hits = sorted(glob.glob("*名簿*.xlsx"))
    if not hits:
        raise SystemExit("名簿xlsxが見つかりません。--roster で指定してください。")
    return hits[0]


def main() -> None:
    ap = argparse.ArgumentParser(description="ScanSnapフォルダ監視→連絡帳PDF自動取り込み")
    ap.add_argument("--dir", default=DEFAULT_DIR, help=f"監視フォルダ（既定: {DEFAULT_DIR}）")
    ap.add_argument("--roster", help="名簿xlsx（既定: カレントの *名簿*.xlsx）")
    ap.add_argument("--interval", type=float, default=30.0, help="走査間隔秒（既定30）")
    ap.add_argument("--stable", type=float, default=5.0, help="安定とみなす待機秒（既定5）")
    ap.add_argument("--once", action="store_true", help="1回だけ走査して終了（cron向き）")
    ap.add_argument("--send", action="store_true", help="取り込み後に日次メールも送信する")
    args = ap.parse_args()

    watch_dir = Path(args.dir)
    if not watch_dir.is_dir():
        raise SystemExit(f"監視フォルダが見つかりません: {watch_dir}")
    roster = find_roster(args.roster)

    log(f"監視開始: {watch_dir}")
    log(f"名簿: {roster} ／ 送信: {'ON' if args.send else 'OFF'} ／ "
        f"間隔: {args.interval}s ／ モード: {'once' if args.once else '常駐'}")

    state = load_state()
    while True:
        n = scan_once(watch_dir, roster, args.stable, args.send, state)
        if n:
            log(f"[走査完了] {n} 件処理")
        if args.once:
            break
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
