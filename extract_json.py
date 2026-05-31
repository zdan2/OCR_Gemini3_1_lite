# extract_json.py
# -*- coding: utf-8 -*-
"""
連絡帳ページ画像 → Gemini 3.1 Flash-Lite で構造化JSON抽出（検証用ミニスクリプト）。

目的:
  本番のDB/CSVを作り込む前に、スキーマが期待どおり効くかを2〜3枚で確認する。
  - 読めない欄が null になるか
  - 食事量カテゴリ・体温・時刻が取れるか
  - 崩し字（メニュー等）の取りこぼし方
  - お迎え欄の扱い
  - コスト/所要

これは抽出と保存だけ。名簿照合・DB・CSVは含めない。

使い方:
  pip install -U google-genai pdf2image pillow
  $env:GEMINI_API_KEY="..."   (PowerShell)  /  export GEMINI_API_KEY=...  (bash)

  # PDFの全ページを抽出（既定）
  python extract_json.py --pdf "C:\\test\\20260528どんぐり　家庭での生活.pdf"
  # ページを絞る
  python extract_json.py --pdf "...pdf" --pages 1,6,7
  # 既存のページ画像JPGを直接渡す
  python extract_json.py --images page_001.jpg page_006.jpg

出力:
  ./_json_out/<元名>_page<NNN>.json   抽出JSON＋メタ（コスト・finish_reason等）
  コンソールに要約を表示。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Optional

try:
    from google import genai
    from google.genai import types as genai_types
except ImportError:
    raise SystemExit("google-genai が必要です: pip install google-genai")

# スキーマ・プロンプトは別ファイルから読む（本番と共有するため）
try:
    from entry_schema import ENTRY_SCHEMA, EXTRACTION_PROMPT, absence_flag
except ImportError:
    raise SystemExit("entry_schema.py を同じフォルダに置いてください。")


MODEL = "gemini-3.1-flash-lite"
INPUT_USD_PER_MTOK = 0.25
OUTPUT_USD_PER_MTOK = 1.50
MAX_OUTPUT_TOKENS = 4096
DEFAULT_DPI = 220
DEFAULT_MAX_LONG_EDGE = 2000
OUT_DIR = Path("_json_out")


def get_client() -> "genai.Client":
    key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not key:
        raise SystemExit("GEMINI_API_KEY（または GOOGLE_API_KEY）を設定してください。")
    return genai.Client(api_key=key)


def render_pdf(pdf_path: Path, pages: Optional[list[int]]) -> list[tuple[int, bytes]]:
    """PDFを画像化してページ番号とJPEGバイト列のリストを返す。"""
    try:
        from pdf2image import convert_from_path
        from PIL import Image
    except ImportError:
        raise SystemExit("pdf2image と pillow が必要です: pip install pdf2image pillow")
    import io

    imgs = convert_from_path(str(pdf_path), dpi=DEFAULT_DPI)
    out = []
    for idx, im in enumerate(imgs, start=1):
        if pages and idx not in pages:
            continue
        im = im.convert("RGB")
        w, h = im.size
        long_edge = max(w, h)
        if long_edge > DEFAULT_MAX_LONG_EDGE:
            s = DEFAULT_MAX_LONG_EDGE / long_edge
            im = im.resize((int(w * s), int(h * s)), Image.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=95)
        out.append((idx, buf.getvalue()))
    return out


def load_images(paths: list[str]) -> list[tuple[int, bytes]]:
    out = []
    for i, p in enumerate(paths, start=1):
        out.append((i, Path(p).read_bytes()))
    return out


def extract_one(client, image_bytes: bytes) -> dict[str, Any]:
    image_part = genai_types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg")

    config_kwargs: dict[str, Any] = {
        "max_output_tokens": MAX_OUTPUT_TOKENS,
        "temperature": 0.0,
        "response_mime_type": "application/json",
        "response_schema": ENTRY_SCHEMA,
    }
    # OCR転記なので思考は最小に（出力枠を思考で食い潰す途切れを防ぐ）。
    # SDKが thinking_level 非対応なら握りつぶす。
    try:
        config_kwargs["thinking_config"] = genai_types.ThinkingConfig(thinking_level="low")
    except Exception:
        pass

    started = time.time()
    try:
        resp = client.models.generate_content(
            model=MODEL,
            contents=[image_part, EXTRACTION_PROMPT],
            config=genai_types.GenerateContentConfig(**config_kwargs),
        )
    except Exception:
        # thinking_config を SDK/モデルが弾いた場合のみを想定した再試行。
        # （response_schema 自体が原因なら同じく失敗するので、その時はそのまま送出）
        fallback = {k: v for k, v in config_kwargs.items() if k != "thinking_config"}
        resp = client.models.generate_content(
            model=MODEL,
            contents=[image_part, EXTRACTION_PROMPT],
            config=genai_types.GenerateContentConfig(**fallback),
        )
    elapsed = time.time() - started

    usage = getattr(resp, "usage_metadata", None)
    in_tok = getattr(usage, "prompt_token_count", None)
    out_tok = getattr(usage, "candidates_token_count", None)
    th_tok = getattr(usage, "thoughts_token_count", None)
    cand = getattr(resp, "candidates", None) or []
    finish = None
    if cand:
        fr = getattr(cand[0], "finish_reason", None)
        finish = getattr(fr, "name", None) or (str(fr) if fr is not None else None)

    raw_text = getattr(resp, "text", None) or ""
    parsed: Any = None
    parse_error: Optional[str] = None
    try:
        parsed = json.loads(raw_text)
    except Exception as e:
        parse_error = f"{type(e).__name__}: {e}"

    cost = None
    if in_tok is not None and out_tok is not None:
        billable_out = out_tok + (th_tok or 0)
        cost = in_tok / 1e6 * INPUT_USD_PER_MTOK + billable_out / 1e6 * OUTPUT_USD_PER_MTOK

    return {
        "data": parsed,
        "parse_error": parse_error,
        "raw_text_if_unparsed": raw_text if parse_error else None,
        "_meta": {
            "model": MODEL,
            "finish_reason": finish,
            "elapsed_sec": round(elapsed, 2),
            "input_tokens": in_tok,
            "output_tokens": out_tok,
            "thoughts_tokens": th_tok,
            "estimated_cost_usd": cost,
            "truncated": finish == "MAX_TOKENS" or bool(parse_error),
        },
    }


def summarize(page_num: int, result: dict[str, Any]) -> None:
    m = result["_meta"]
    d = result.get("data") or {}
    if result["parse_error"]:
        print(f"  page{page_num:>3}: ★JSONパース失敗 ({result['parse_error']}) "
              f"finish={m['finish_reason']} cost=${m['estimated_cost_usd']}")
        return
    name = d.get("child_name")
    date = d.get("entry_date_raw")
    # 抽出できた主要フィールド数（null以外）をざっくり数える
    keys_obs = ["sleep_home_start", "sleep_home_end", "temp_home", "temp_en_am",
                "meal_dinner", "meal_breakfast", "meal_en",
                "stool_present_home", "stool_present_en"]
    filled = sum(1 for k in keys_obs if d.get(k) is not None)
    flag = absence_flag(d.get("comment_home"))
    print(f"  page{page_num:>3}: {name} / {date} | 観察項目 {filled}/{len(keys_obs)} 充足 "
          f"| 休早退連絡={flag['absence_notice']}{flag['absence_hits'] or ''} "
          f"| {m['elapsed_sec']}s ${m['estimated_cost_usd']:.4f} thoughts={m['thoughts_tokens']}")
    if d.get("uncertain_notes"):
        print(f"           ⚠ uncertain: {d['uncertain_notes']}")


def main() -> None:
    ap = argparse.ArgumentParser(description="連絡帳ページ→Gemini 3.1 Flash-Lite でJSON抽出（検証用）")
    ap.add_argument("--pdf", help="入力PDFパス")
    ap.add_argument("--images", nargs="*", help="ページ画像JPGを直接指定（PDFの代わり）")
    ap.add_argument("--pages", help="抽出するページ番号をカンマ区切りで（例 1,6,7）。未指定は全ページ。")
    args = ap.parse_args()

    if not args.pdf and not args.images:
        raise SystemExit("--pdf か --images のどちらかを指定してください。")

    pages = None
    if args.pages:
        pages = [int(x) for x in args.pages.split(",") if x.strip()]

    if args.images:
        items = load_images(args.images)
        src_stem = "images"
    else:
        pdf_path = Path(args.pdf)
        if not pdf_path.exists():
            raise SystemExit(f"PDFが見つかりません: {pdf_path}")
        items = render_pdf(pdf_path, pages)
        src_stem = pdf_path.stem

    OUT_DIR.mkdir(exist_ok=True)
    client = get_client()

    print(f"モデル: {MODEL} / 対象 {len(items)} ページ")
    total_cost = 0.0
    for page_num, img in items:
        result = extract_one(client, img)
        out_path = OUT_DIR / f"{src_stem}_page{page_num:03}.json"
        out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        summarize(page_num, result)
        c = result["_meta"].get("estimated_cost_usd") or 0.0
        total_cost += c
        time.sleep(0.5)

    print(f"\n完了。出力: {OUT_DIR.resolve()}  概算合計コスト: ${total_cost:.4f}")


if __name__ == "__main__":
    main()
