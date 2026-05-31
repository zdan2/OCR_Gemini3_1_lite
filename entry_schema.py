# entry_schema.py
# -*- coding: utf-8 -*-
"""
連絡帳1ページからの構造化抽出スキーマ（Gemini structured output 用）と、
コード側で立てる「お休み・早退などの連絡フラグ」の語句マッチ。

方針:
  - Gemini には「読み取った事実」だけ出させる。是非・予定日などの判定はさせない。
  - 読めない欄は null。傾向観察が主目的なので、量カテゴリ・数値・時刻を重視。
  - 食事内容テキストは参考情報（崩し字で揺れる前提。観察には量カテゴリを使う）。
  - お休み/早退などの連絡有無は、保護者コメント全文に対するコード側の語句マッチで立てる
    （AIに判定させない。語句リストは運用で育てる）。
  - 使用モデル: gemini-3.1-flash-lite。

依存: google-genai（スキーマ実行時）。本ファイル単体（スキーマ定義と語句マッチ）は依存なし。
"""

from __future__ import annotations

import re
from typing import Any


# =============================================================================
# Gemini structured output 用 JSON スキーマ（OpenAPI 3.0 サブセット）
# nullable=True を多用し、「読めない欄は null」を許容する。
# =============================================================================

# enum は文字列のみ（Gemini/pydantic は enum に None を許さない）。
# 「読めなければ null」は各フィールドの nullable=True が担う。
MEAL_ENUM = ["旺盛", "普通", "あまりなし", "なし"]
STOOL_ENUM = ["普通", "硬い", "軟便", "下痢便"]

ENTRY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "child_name": {"type": "string", "nullable": True,
                       "description": "児童名。読めたまま（漢字/かな/カタカナどれでも可）。"},
        "entry_date_raw": {"type": "string", "nullable": True,
                           "description": "年月日欄の記載をそのまま。例『8年5月28日(木)』『2026年5月28日』『R8年…』"},

        # 睡眠（時刻は HH:MM 文字列。読めなければ null）
        "sleep_home_start": {"type": "string", "nullable": True, "description": "家庭の就寝時刻 HH:MM"},
        "sleep_home_end":   {"type": "string", "nullable": True, "description": "家庭の起床時刻 HH:MM"},
        "nap_start":        {"type": "string", "nullable": True, "description": "園の昼寝開始 HH:MM"},
        "nap_end":          {"type": "string", "nullable": True, "description": "園の昼寝終了 HH:MM"},

        # 体温（℃ 数値。読めなければ null）
        "temp_home":   {"type": "number", "nullable": True, "description": "家庭の検温 ℃"},
        "temp_en_am":  {"type": "number", "nullable": True, "description": "園の午前検温 ℃"},
        "temp_en_pm":  {"type": "number", "nullable": True, "description": "園の午後検温 ℃"},

        # 食事量（丸が付いた選択肢。観察の主データ）
        "meal_dinner":    {"type": "string", "nullable": True, "enum": MEAL_ENUM, "description": "夕食の量(丸)"},
        "meal_breakfast": {"type": "string", "nullable": True, "enum": MEAL_ENUM, "description": "朝食の量(丸)"},
        "meal_en":        {"type": "string", "nullable": True, "enum": MEAL_ENUM, "description": "園の食事内容の量(丸)"},

        # 食事内容テキスト（参考情報。崩し字で揺れる前提）
        "meal_dinner_text":    {"type": "string", "nullable": True},
        "meal_breakfast_text": {"type": "string", "nullable": True},
        "meal_en_text":        {"type": "string", "nullable": True},

        # 排便
        "stool_present_home": {"type": "boolean", "nullable": True, "description": "家庭排便 有=true 無=false"},
        "stool_type_home":    {"type": "string", "nullable": True, "enum": STOOL_ENUM},
        "stool_present_en":   {"type": "boolean", "nullable": True, "description": "園排便 有=true 無=false"},
        "stool_type_en":      {"type": "string", "nullable": True, "enum": STOOL_ENUM},

        # コメント全文（正確に。改行は維持しなくてよい）
        "comment_home": {"type": "string", "nullable": True, "description": "家庭での様子と連絡事項 全文"},
        "comment_en":   {"type": "string", "nullable": True, "description": "園での様子 全文"},

        # OCRが自信を持てない箇所のメモ（候補併記など。人の点検用）
        "uncertain_notes": {"type": "string", "nullable": True,
                            "description": "判読困難・候補が複数ある箇所をまとめる。無ければ null。"},
    },
    "required": ["child_name", "entry_date_raw", "comment_home", "comment_en"],
    # property_ordering で出力順を安定させる（任意）
    "propertyOrdering": [
        "child_name", "entry_date_raw",
        "sleep_home_start", "sleep_home_end", "nap_start", "nap_end",
        "temp_home", "temp_en_am", "temp_en_pm",
        "meal_dinner", "meal_breakfast", "meal_en",
        "meal_dinner_text", "meal_breakfast_text", "meal_en_text",
        "stool_present_home", "stool_type_home", "stool_present_en", "stool_type_en",
        "comment_home", "comment_en", "uncertain_notes",
    ],
}


EXTRACTION_PROMPT = """
あなたは日本語OCRの専門家です。画像は保育園の連絡帳「家庭での生活」1ページです。
印刷された項目名と、保護者・保育士による手書き記入を読み取り、指定のJSON構造で返してください。

厳守事項:
- 読み取れない欄は null にする。推測で埋めない。
- 食事量(meal_*)は、丸が付いている選択肢を「旺盛/普通/あまりなし/なし」から選ぶ。丸が不明なら null。
- 食事内容テキスト(meal_*_text)は手書きをそのまま。崩れて読めなければ読める範囲＋不明箇所、難しければ null。
- 排便の有/無は、丸の位置や時刻記入から判断（時刻が書かれていれば有の可能性が高いが、丸を優先）。
- 体温は数値のみ（例 36.7）。時刻は HH:MM 形式。
- comment_home / comment_en は手書き本文を可能な限り正確に全文。
- 判読に自信がない箇所、候補が複数ある箇所は uncertain_notes にまとめる（「朝食末尾: 枝豆/えだまめ?」のように）。
- 是非の判断や、将来の予定の解釈はしない。読み取った事実のみを返す。
""".strip()


# =============================================================================
# コード側で立てる連絡フラグ（AIに判定させない。単なる語句検索）
# =============================================================================

# お休み・早退・通院・健診など「予定/欠席系」の語。運用で育てる。
ABSENCE_KEYWORDS = [
    "休み", "おやすみ", "お休み", "欠席", "早退", "早めにお迎え", "早お迎え",
    "健診", "検診", "歯科", "通院", "病院", "受診", "予防接種", "ワクチン",
    "遅刻", "遅れて", "お迎えの時間", "迎えに伺", "むかえに",
]

# 体調注意系（任意。傾向と別に「気になる記載」を拾いたい場合）
HEALTH_WATCH_KEYWORDS = [
    "発熱", "熱が", "咳", "鼻水", "下痢", "嘔吐", "吐い", "発疹", "湿疹",
    "アレル", "薬", "投薬", "けが", "ケガ", "怪我",
]


def _hits(text: str | None, keywords: list[str]) -> list[str]:
    if not text:
        return []
    return [k for k in keywords if k in text]


def absence_flag(comment_home: str | None) -> dict[str, Any]:
    """保護者コメントから、お休み・早退等の連絡が含まれるかを判定（語句マッチのみ）。"""
    hits = _hits(comment_home, ABSENCE_KEYWORDS)
    return {"absence_notice": bool(hits), "absence_hits": hits}


def health_watch_flag(comment_home: str | None, comment_en: str | None) -> dict[str, Any]:
    """家庭・園コメントから体調注意語を拾う（任意機能）。"""
    hits = sorted(set(_hits(comment_home, HEALTH_WATCH_KEYWORDS)
                      + _hits(comment_en, HEALTH_WATCH_KEYWORDS)))
    return {"health_watch": bool(hits), "health_hits": hits}


if __name__ == "__main__":
    # フラグ語句マッチの単体デモ（page11 髙嶋の連絡を模擬）
    samples = {
        "p11 健診で早退": "明日、歯科健診のため13:00〜13:30にむかえに伺います。",
        "p7 通常コメント": "帰宅後もよく食べ、夜もぐっすり眠れています。今日もよろしくお願いします。",
        "p13 通常コメント": "朝起きてすぐモノレールを持って、見ながら朝ごはんを食べてました。",
    }
    print("=== お休み・早退フラグ（語句マッチ）===")
    for label, c in samples.items():
        f = absence_flag(c)
        print(f"  {label}: notice={f['absence_notice']} hits={f['absence_hits']}")
