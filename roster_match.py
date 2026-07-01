# roster_match.py
# -*- coding: utf-8 -*-
"""
保育園連絡帳OCRの読み取り氏名を、月別名簿（きいちご・どんぐりの2クラス）に照合する。

前提:
  - 名簿Excel「在園児各月児童名簿_令和8年度.xlsx」は月別シート（'4月','5月','6月'…）を持つ。
  - 各月シートのレイアウトは固定:
      きいちご見出し: 左カラム(B列) r3 付近
      どんぐり見出し: 左カラム(B列) r14 付近
      列構成(左カラム): B=漢字氏名, C=かな氏名, D=生年月日, E=クラス区分, F=性別
  - 対象はきいちご・どんぐりの2クラスのみ。他クラスは無視する。
  - 2クラス合算でも、かな氏名の重複は無い前提（重複検出時は警告を出す）。

照合方針:
  - OCRが読んだ氏名を「漢字キー」と「かなキー」の両方で名簿と突き合わせ、最良スコアを採用。
    これにより、OCRが漢字で読んでも（例: 小林 杏）、かなで読んでも（例: あいた そうま）、
    カタカナで読んでも（例: リゼ）当てられる。pykakasiのような読み推定は使わず、
    名簿側が漢字とかなを両方持っていることを利用するので、読み違いのリスクが小さい。
  - スコアが閾値未満なら確定せず「要確認」として返す（誤紐付けで別の子の記録になる事故を防ぐ）。

依存: openpyxl, jaconv, rapidfuzz
  pip install openpyxl jaconv rapidfuzz
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import jaconv
import openpyxl
from rapidfuzz import fuzz


# 既知のクラス見出し（これらに当たったら別クラスの開始とみなす）
KNOWN_CLASS_HEADINGS = {
    "きいちご", "うめ", "もも", "ばら", "すみれ", "たんぽぽ,",
    "たんぽぽ", "どんぐり", "くるみ", "さくら", "ちゅうりっぷ",
}
# 今回照合の対象とするクラス
TARGET_CLASSES = ("きいちご", "どんぐり")

# 左カラムの列番号（1-indexed）
COL_KANJI = 2   # B: 児童氏名（漢字）
COL_KANA = 3    # C: 児童かな氏名
COL_DOB = 4     # D: 生年月日
COL_CLASS = 5   # E: クラス区分
COL_SEX = 6     # F: 性別

# 自動確定のスコア閾値（0-100）。未満は要確認。
DEFAULT_SCORE_CUTOFF = 75.0
# 1位と2位のスコア差がこれ未満なら、紛らわしいので要確認に回す。
DEFAULT_MARGIN = 5.0


@dataclass(frozen=True)
class Child:
    name_kanji: str          # 全角スペース除去済み
    name_kana: str           # 全角スペース除去済み
    dob: Optional[dt.date]
    class_name: str          # 'きいちご' | 'どんぐり'


@dataclass
class MatchResult:
    ocr_name: str
    child: Optional[Child]   # 確定（または最有力）の児童。要確認時もNoneにはしない
    score: float
    runner_up_score: float
    confident: bool          # True=自動確定可, False=要確認
    reason: str              # 判定理由（ログ用）
    matched_by: str = "fuzzy"  # 'alias'（別名辞書で確定） | 'fuzzy'（曖昧照合） | 'none'


def _norm_kana(s: str) -> str:
    """カタカナ→ひらがな、全角/半角スペース除去、トリム。"""
    s = jaconv.kata2hira(str(s))
    return s.replace("\u3000", "").replace(" ", "").strip()


def _norm_raw(s: str) -> str:
    """漢字照合用。スペースだけ除去（文字種は変換しない）。"""
    return str(s).replace("\u3000", "").replace(" ", "").strip()


def month_sheet_for_date(scan_date: dt.date) -> str:
    """スキャン日（連絡帳の日付）から参照すべき月シート名を返す。例: 2026-05-28 -> '5月'。"""
    return f"{scan_date.month}月"


def _fiscal_pos(month: int) -> int:
    """年度内の順序（4月=0 … 3月=11）。月シートの新旧比較に使う。"""
    return (month - 4) % 12


def resolve_month_sheet(month_sheet: str, sheetnames: list[str]) -> Optional[str]:
    """希望の月シートが無い場合、年度順で「直近の既存月シート」を代用として返す。
    名簿は月ごとにシートを足していく運用のため、新しい月のシートが未追加のうちに
    スキャンが来ると照合不能で全員要確認になる。0〜1歳クラスは月途中の入退園が
    少ないので、直近月の名簿で代用するのが実用的（入園月ズレのリスクは警告で補う）。

    戻り値: 代用シート名。月シートが1枚も無ければ None。
    選び方: 希望月以前で最も新しい月（年度順）。それも無ければ最も古い既存月。"""
    if month_sheet in sheetnames:
        return month_sheet
    m = re.fullmatch(r"(\d{1,2})月", month_sheet)
    if not m or not (1 <= int(m.group(1)) <= 12):
        return None
    want = _fiscal_pos(int(m.group(1)))
    months = []
    for s in sheetnames:
        mm = re.fullmatch(r"(\d{1,2})月", str(s).strip())
        if mm and 1 <= int(mm.group(1)) <= 12:
            months.append((_fiscal_pos(int(mm.group(1))), str(s).strip()))
    if not months:
        return None
    months.sort()
    prev = [t for t in months if t[0] <= want]
    return (prev[-1] if prev else months[0])[1]


def load_roster(xlsx_path: str | Path, month_sheet: str) -> list[Child]:
    """指定月シートから、きいちご・どんぐりの2クラスを抽出する。左カラムのみ走査。
    月シートが未追加の場合は直近の既存月シートで代用する（警告表示）。"""
    wb = openpyxl.load_workbook(xlsx_path, data_only=True)
    if month_sheet not in wb.sheetnames:
        fallback = resolve_month_sheet(month_sheet, wb.sheetnames)
        if not fallback:
            raise ValueError(f"シートが見つかりません: {month_sheet} (在: {wb.sheetnames})")
        print(f"    [名簿代用] {month_sheet} シート未追加 → 直近の {fallback} で代用します"
              f"（月初は名簿の更新を確認してください）")
        month_sheet = fallback
    ws = wb[month_sheet]

    children: list[Child] = []
    current_class: Optional[str] = None

    for r in range(1, ws.max_row + 1):
        v = ws.cell(r, COL_KANJI).value
        if v is None:
            continue
        sv = str(v).strip()

        # クラス見出し行の処理
        if sv in KNOWN_CLASS_HEADINGS:
            current_class = sv if sv in TARGET_CLASSES else None
            continue
        if sv == "児童氏名":  # ヘッダ行
            continue

        # 対象クラスの中の実データ行のみ拾う
        if current_class and ws.cell(r, COL_KANA).value:
            dob_val = ws.cell(r, COL_DOB).value
            dob = dob_val.date() if isinstance(dob_val, dt.datetime) else None
            children.append(Child(
                name_kanji=_norm_raw(sv),
                name_kana=_norm_kana(ws.cell(r, COL_KANA).value),
                dob=dob,
                class_name=current_class,
            ))

    # かな氏名の重複チェック（重複があると2クラス合算照合で衝突しうる）
    kanas = [c.name_kana for c in children]
    dups = sorted({k for k in kanas if kanas.count(k) > 1})
    if dups:
        # 例外にはせず、呼び出し側で気づけるよう警告。必要なら厳格化してもよい。
        import warnings
        warnings.warn(f"{month_sheet}: かな氏名の重複あり {dups}。クラス指定での照合を検討してください。")

    return children


def _score_against(ocr_name: str, child: Child) -> float:
    """1児童に対する最良スコア。漢字full/部分・かなfull/部分の最大値。"""
    q_raw = _norm_raw(ocr_name)
    q_hira = _norm_kana(ocr_name)
    return max(
        fuzz.ratio(q_raw, child.name_kanji),
        fuzz.partial_ratio(q_raw, child.name_kanji),
        fuzz.ratio(q_hira, child.name_kana),
        fuzz.partial_ratio(q_hira, child.name_kana),
    )


def match_child(
    ocr_name: str,
    roster: list[Child],
    score_cutoff: float = DEFAULT_SCORE_CUTOFF,
    margin: float = DEFAULT_MARGIN,
    aliases: Optional[dict[str, str]] = None,
) -> MatchResult:
    """OCR氏名を名簿に照合。最有力候補・スコア・確信度を返す。

    aliases: {別名(ひらがな/カタカナ/誤読表記) -> 名簿のかな氏名} の辞書。
      園が知っている「この書き方はこの子」を明示登録する場所。
      曖昧照合の前に引き、一致すれば score=100・confident=True で確定する
      （機械の推測ではなく人間の既知の対応なので、誤紐付けの心配がない）。
    """
    if not ocr_name or not str(ocr_name).strip():
        return MatchResult(ocr_name, None, 0.0, 0.0, False, "OCR氏名が空", "none")
    if not roster:
        return MatchResult(ocr_name, None, 0.0, 0.0, False, "名簿が空", "none")

    # --- 1) 別名辞書（エイリアス）を先に引く ---
    if aliases:
        q = _norm_kana(ocr_name)
        # 完全一致、または別名がOCR名に含まれる/OCR名が別名に含まれる（部分一致）で拾う
        for alias_key, target_kana in aliases.items():
            ak = _norm_kana(alias_key)
            if not ak:
                continue
            if ak == q or ak in q or q in ak:
                tgt = _norm_kana(target_kana)
                for c in roster:
                    if c.name_kana == tgt:
                        return MatchResult(
                            ocr_name, c, 100.0, 0.0, True,
                            f"別名辞書で確定: '{alias_key}' -> {c.name_kanji}", "alias")
                # 辞書に書かれた対象が今月の名簿にいない場合は通常照合に落とす
                break

    # --- 2) 通常の曖昧照合 ---
    scored = sorted(
        ((c, _score_against(ocr_name, c)) for c in roster),
        key=lambda t: t[1],
        reverse=True,
    )
    best_child, best = scored[0]
    runner = scored[1][1] if len(scored) > 1 else 0.0

    confident = (best >= score_cutoff) and ((best - runner) >= margin)
    if confident:
        reason = f"score={best:.0f} (>= {score_cutoff:.0f}), margin={best - runner:.0f}"
    elif best < score_cutoff:
        reason = f"要確認: score={best:.0f} が閾値{score_cutoff:.0f}未満"
    else:
        reason = f"要確認: 1位{best:.0f}と2位{runner:.0f}の差が小さい(margin<{margin:.0f})"

    return MatchResult(ocr_name, best_child, best, runner, confident, reason, "fuzzy")


# OCR結果Markdownの「氏名」を取り出すための簡易抽出
_NAME_PATTERNS = [
    re.compile(r"^-?\s*氏名[:：]\s*(.+)$", re.MULTILINE),
    re.compile(r"児童名[:：|\s]+([^\|\n]+)"),
]


def extract_name_from_md(md_text: str) -> Optional[str]:
    """OCR結果Markdownから氏名らしき文字列を1つ取り出す。見つからなければNone。"""
    for pat in _NAME_PATTERNS:
        m = pat.search(md_text)
        if m:
            name = m.group(1).strip()
            # 末尾の補足（「（あいた そうま?）」等）や記号を軽く除去
            name = re.split(r"[（(]", name)[0].strip()
            if name:
                return name
    return None


def extract_date_from_md(md_text: str, default_year: Optional[int] = None) -> Optional[dt.date]:
    """OCR結果から日付を推定。西暦『2026年5月28日』、和暦『R8年5月28日』『8年5月28日』に対応。
    年が書かれていない『5月28日』のみの場合、default_year が与えられればその年で補完する
    （同一バッチの他ページの年や処理日の年を渡す想定）。"""
    # 西暦 2026年5月28日
    m = re.search(r"(20\d{2})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日", md_text)
    if m:
        y, mo, d = map(int, m.groups())
        try:
            return dt.date(y, mo, d)
        except ValueError:
            return None
    # 和暦 R8年5月28日 / 8年5月28日 （令和8年=2026年）。ただし月日だけの誤マッチを避け、
    # 「年」字の前に1〜2桁がある場合のみ和暦とみなす。
    m = re.search(r"R?\s*(\d{1,2})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日", md_text)
    if m:
        reiwa, mo, d = map(int, m.groups())
        y = 2018 + reiwa  # 令和元年=2019 → 令和N年=2018+N
        try:
            return dt.date(y, mo, d)
        except ValueError:
            return None
    # 年なし『5月28日』。default_year があれば補完。
    m = re.search(r"(\d{1,2})\s*月\s*(\d{1,2})\s*日", md_text)
    if m and default_year:
        mo, d = map(int, m.groups())
        try:
            return dt.date(default_year, mo, d)
        except ValueError:
            return None
    return None


if __name__ == "__main__":
    # 簡易デモ: 同梱の名簿に対し、サンプルOCR氏名を照合する。
    import sys

    xlsx = sys.argv[1] if len(sys.argv) > 1 else "在園児各月児童名簿_令和8年度.xlsx"
    roster = load_roster(xlsx, "5月")
    print(f"5月 対象名簿: {len(roster)}名 "
          f"(きいちご{sum(c.class_name=='きいちご' for c in roster)} / "
          f"どんぐり{sum(c.class_name=='どんぐり' for c in roster)})")
    print()

    samples = ["あいた そうま", "大久保 汐理", "かとうつばさ", "小林 杏", "リゼ",
               "やまだ あん", "判読不能なまえ"]
    for s in samples:
        res = match_child(s, roster)
        tag = "OK " if res.confident else "★確認"
        kanji = res.child.name_kanji if res.child else "-"
        kana = res.child.name_kana if res.child else "-"
        print(f"[{tag}] OCR={s!r:16s} -> {kanji}/{kana} ({res.reason})")
