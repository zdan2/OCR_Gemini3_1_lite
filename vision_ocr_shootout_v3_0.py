# vision_ocr_shootout_v2.py
# -*- coding: utf-8 -*-
r"""
PDF Vision OCR shootout for Japanese handwritten forms.

What it does:
  - Finds PDFs in TARGET_DIR (default: C:\test)
  - Renders each PDF page to a normalized JPEG once
  - Sends the same page image to multiple Vision-capable models
  - Saves each model's OCR result as Markdown
  - Saves per-run metrics CSV, aggregate summary CSV, and a scoring sheet template

Setup:
  cd C:\test
  py -m venv .venv
  .\.venv\Scripts\Activate.ps1
  pip install -U anthropic google-genai openai pdf2image pillow

  # If Poppler is not installed:
  winget install oschwartz10612.Poppler

  # API keys:
  $env:ANTHROPIC_API_KEY="sk-ant-..."
  $env:GEMINI_API_KEY="..."
  $env:OPENAI_API_KEY="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"

Examples:
  python .\vision_ocr_shootout_v2.py
  python .\vision_ocr_shootout_v2.py --max-pages all
  python .\vision_ocr_shootout_v2.py --models gemini_3_1_pro_preview,gemini_3_5_flash,claude_sonnet_4_6
  python .\vision_ocr_shootout_v2.py --force
  python .\vision_ocr_shootout_v2.py --list-models
"""

from __future__ import annotations

import argparse
import base64
import csv
import dataclasses
import datetime as dt
import json
import os
import random
import re
import shutil
import sys
import time
import traceback
from pathlib import Path
from typing import Any, Optional

# ---- Console encoding safety on Windows ------------------------------------
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# ---- Optional imports with friendly error messages --------------------------
try:
    from PIL import Image
except ImportError as exc:
    raise SystemExit("Pillow が必要です: pip install pillow") from exc

try:
    from pdf2image import convert_from_path
except ImportError as exc:
    raise SystemExit("pdf2image が必要です: pip install pdf2image") from exc

try:
    from anthropic import Anthropic
except ImportError:
    Anthropic = None  # type: ignore[assignment]

try:
    from google import genai
    from google.genai import types as genai_types
except ImportError:
    genai = None  # type: ignore[assignment]
    genai_types = None  # type: ignore[assignment]

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None  # type: ignore[assignment]


# =============================================================================
# Settings
# =============================================================================

DEFAULT_TARGET_DIR = Path(r"C:\test")
DEFAULT_OUT_DIR_NAME = "_vision_compare_v2"

# For handwritten Japanese OCR, 200-240 DPI is a good first range.
DEFAULT_DPI = 220

# All models receive the exact same image. This keeps the comparison fair.
# Increase to 2200-2576 if small handwriting is being missed, but cost/latency may rise.
DEFAULT_MAX_LONG_EDGE = 2000

DEFAULT_JPEG_QUALITY = 95

# Safer first run: 5 pages. Use --max-pages all for full batch.
DEFAULT_MAX_PAGES = "5"

MAX_OUTPUT_TOKENS = 8192

# Pause between calls. Paid tiers are better, but a tiny pause avoids accidental bursts.
DEFAULT_PAUSE_SEC = 0.8

RETRY_COUNT = 3
RETRY_BASE_SEC = 8.0

PROMPT = """
あなたは日本語OCRの専門家です。
画像内の文書を、できるだけ正確に読み取ってください。

対象は、保育園・園児・家庭連絡帳のような日本語文書です。
印刷文字だけでなく、手書き文字も読み取ってください。

厳守:
- 読めない箇所は [判読不能] と書く
- 推測で補完しない
- 勝手に要約しない
- 原文に近い形で出す
- 日付、時刻、体温、名前、チェック、丸、記号を落とさない
- 「有・無」「午前・午後」「睡眠」「食事」「排便」などのフォーム項目を取り違えない
- 表やフォームの構造はMarkdownで整理する
- 手書き本文は、可能な限りそのまま転記する
- 絵文字・顔文字・ハート・丸囲み・チェックなども、見える範囲で記録する
- 不確かな読みは断定せず、候補があれば「A/B?」のように書く

出力形式:
# OCR結果

## 基本情報
- PDF:
- ページ:
- 日付:
- 氏名:
- ページ内で目立つ項目:

## 読み取り本文
Markdownで、表・項目・手書き文を整理して出力。

## 判読が怪しい箇所
- 箇条書きで列挙。

## 確認したい重要項目
- 氏名:
- 日付:
- 体温:
- 時刻:
- 有無・チェック・丸:
""".strip()


# =============================================================================
# Model definitions
# =============================================================================

@dataclasses.dataclass(frozen=True)
class ModelSpec:
    label: str
    provider: str  # "anthropic", "gemini", or "openai"
    model: str
    input_usd_per_mtok: float
    output_usd_per_mtok: float
    enabled_by_default: bool = True
    # Anthropic Opus 4.7 rejects non-default sampling parameters. Keep this False.
    send_temperature: bool = True
    temperature: Optional[float] = 0.0
    # Optional Gemini thinking level. Leave None for maximum compatibility.
    gemini_thinking_level: Optional[str] = None
    # Optional OpenAI reasoning effort: "none"/"low"/"medium"/"high"/"xhigh".
    # GPT-5 reasoning models bill hidden thinking tokens as output, so for OCR
    # transcription we default callers to a low/none setting to control cost.
    openai_reasoning_effort: Optional[str] = None
    notes: str = ""


MODELS: list[ModelSpec] = [
    ModelSpec(
        label="claude_sonnet_4_6",
        provider="anthropic",
        model="claude-sonnet-4-6",
        input_usd_per_mtok=3.00,
        output_usd_per_mtok=15.00,
        send_temperature=True,
        notes="Claude balanced/high quality",
    ),
    ModelSpec(
        label="claude_opus_4_7",
        provider="anthropic",
        model="claude-opus-4-7",
        input_usd_per_mtok=5.00,
        output_usd_per_mtok=25.00,
        send_temperature=False,
        notes="Claude highest quality; temperature omitted",
    ),
    ModelSpec(
        label="gemini_3_5_flash",
        provider="gemini",
        model="gemini-3.5-flash",
        input_usd_per_mtok=1.50,
        output_usd_per_mtok=9.00,
        notes="Gemini stable high-performance Flash",
    ),
    ModelSpec(
        label="gemini_3_flash_preview",
        provider="gemini",
        model="gemini-3-flash-preview",
        input_usd_per_mtok=0.50,
        output_usd_per_mtok=3.00,
        notes="Gemini 3 Flash preview; good paid-tier candidate",
    ),
    ModelSpec(
        label="gemini_3_1_pro_preview",
        provider="gemini",
        model="gemini-3.1-pro-preview",
        input_usd_per_mtok=2.00,
        output_usd_per_mtok=12.00,
        notes="Gemini Pro preview; requires paid tier; price assumes <=200k input tokens",
    ),
    ModelSpec(
        label="gemini_3_1_flash_lite",
        provider="gemini",
        model="gemini-3.1-flash-lite",
        input_usd_per_mtok=0.25,
        output_usd_per_mtok=1.50,
        notes="Gemini cheapest current 3.1 stable-lite candidate",
    ),
    ModelSpec(
        label="gemini_2_5_flash",
        provider="gemini",
        model="gemini-2.5-flash",
        input_usd_per_mtok=0.30,
        output_usd_per_mtok=2.50,
        notes="Gemini 2.5 Flash baseline",
    ),
    ModelSpec(
        label="gemini_2_5_flash_lite",
        provider="gemini",
        model="gemini-2.5-flash-lite",
        input_usd_per_mtok=0.10,
        output_usd_per_mtok=0.40,
        notes="Very cheap baseline",
    ),
    ModelSpec(
        label="gpt_5_5",
        provider="openai",
        model="gpt-5.5",
        input_usd_per_mtok=5.00,
        output_usd_per_mtok=30.00,
        # GPT-5.5 always reasons; "none" is not accepted. Use the lowest setting
        # that still works to keep hidden-thinking output tokens (and cost) down.
        send_temperature=False,
        openai_reasoning_effort="low",
        notes="OpenAI current flagship; tops handwriting (IAM) leaderboards; reasoning bills as output",
    ),
    ModelSpec(
        label="gpt_5_4",
        provider="openai",
        model="gpt-5.4",
        input_usd_per_mtok=2.50,
        output_usd_per_mtok=15.00,
        send_temperature=False,
        openai_reasoning_effort="low",
        notes="OpenAI cost-quality balance; good paid-tier frontier candidate",
    ),
]


# =============================================================================
# Helpers
# =============================================================================

def now_stamp() -> str:
    return dt.datetime.now().strftime("%Y%m%d_%H%M%S")


def parse_max_pages(value: str) -> Optional[int]:
    value = str(value).strip().lower()
    if value in {"all", "none", "0", ""}:
        return None
    try:
        n = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("--max-pages は整数または all を指定してください。") from exc
    if n < 1:
        return None
    return n


def safe_stem(path: Path) -> str:
    # Keep Japanese names, remove only unsafe path characters.
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", path.stem).strip() or "document"


def find_poppler_path() -> Optional[str]:
    if shutil.which("pdftoppm"):
        return None

    candidates: list[Path] = [
        Path(r"C:\Program Files\poppler\Library\bin"),
        Path(r"C:\Program Files\poppler-24.08.0\Library\bin"),
        Path(r"C:\Program Files\poppler-25.07.0\Library\bin"),
        Path(r"C:\Program Files (x86)\poppler\Library\bin"),
    ]

    program_files = [Path(os.environ.get("ProgramFiles", r"C:\Program Files"))]
    if os.environ.get("ProgramFiles(x86)"):
        program_files.append(Path(os.environ["ProgramFiles(x86)"]))

    for base in program_files:
        if base.exists():
            candidates.extend(base.glob("poppler*/*/bin"))
            candidates.extend(base.glob("poppler*/Library/bin"))
            candidates.extend(base.glob("poppler*/bin"))

    for p in candidates:
        if (p / "pdftoppm.exe").exists():
            return str(p)

    return None


def ensure_dirs(out_dir: Path) -> dict[str, Path]:
    dirs = {
        "out": out_dir,
        "pages": out_dir / "pages",
        "outputs": out_dir / "outputs",
        "errors": out_dir / "errors",
        "logs": out_dir / "logs",
    }
    for p in dirs.values():
        p.mkdir(parents=True, exist_ok=True)
    return dirs


def image_to_base64(path: Path) -> str:
    return base64.b64encode(path.read_bytes()).decode("utf-8")


def estimate_cost_usd(
    spec: ModelSpec,
    input_tokens: Optional[int],
    output_tokens: Optional[int],
    thoughts_tokens: Optional[int] = None,
) -> Optional[float]:
    if input_tokens is None or output_tokens is None:
        return None
    # Gemini "thoughts" tokens and OpenAI hidden reasoning tokens are billed at
    # the output rate. Some SDKs already fold them into output_tokens; others do
    # not. We add them only when they are reported separately to avoid double
    # counting (callers pass thoughts_tokens=None when already included).
    billable_output = output_tokens + (thoughts_tokens or 0)
    return (
        input_tokens / 1_000_000 * spec.input_usd_per_mtok
        + billable_output / 1_000_000 * spec.output_usd_per_mtok
    )


def get_attr(obj: Any, *names: str) -> Any:
    for name in names:
        if obj is None:
            return None
        if isinstance(obj, dict) and name in obj:
            return obj[name]
        if hasattr(obj, name):
            return getattr(obj, name)
    return None


def is_retryable_exception(exc: Exception) -> bool:
    msg = f"{type(exc).__name__}: {exc}".lower()
    retry_markers = [
        "429",
        "resource_exhausted",
        "rate limit",
        "rate_limit",
        "ratelimit",
        "quota",
        "timeout",
        "timed out",
        "temporarily",
        "unavailable",
        "503",
        "502",
        "500",
        "overloaded",
        "try again",
    ]
    return any(m in msg for m in retry_markers)


def sleep_for_retry(attempt: int, exc: Exception) -> None:
    msg = str(exc)
    # Try to respect "retry in 20s" or retryDelay from Gemini errors.
    m = re.search(r"retry(?:Delay| in)?[^0-9]*(\d+)", msg, flags=re.IGNORECASE)
    if m:
        delay = float(m.group(1)) + 1.0
    else:
        delay = RETRY_BASE_SEC * (2 ** (attempt - 1)) + random.uniform(0, 2.5)
    delay = min(delay, 90.0)
    print(f"      retry in {delay:.1f}s")
    time.sleep(delay)


def write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


# =============================================================================
# PDF rendering
# =============================================================================

def resize_and_save_jpeg(input_image: Image.Image, output_path: Path, max_long_edge: int, jpeg_quality: int) -> dict[str, Any]:
    img = input_image.convert("RGB")
    original_width, original_height = img.size
    width, height = img.size
    long_edge = max(width, height)
    resized = False

    if long_edge > max_long_edge:
        scale = max_long_edge / long_edge
        new_size = (max(1, int(width * scale)), max(1, int(height * scale)))
        img = img.resize(new_size, Image.LANCZOS)
        resized = True

    img.save(output_path, "JPEG", quality=jpeg_quality, optimize=True)

    final_width, final_height = img.size
    return {
        "original_width": original_width,
        "original_height": original_height,
        "final_width": final_width,
        "final_height": final_height,
        "resized": resized,
        "bytes": output_path.stat().st_size,
    }


def render_pdf_to_images(
    pdf_path: Path,
    pages_dir: Path,
    dpi: int,
    max_long_edge: int,
    jpeg_quality: int,
    max_pages: Optional[int],
    force_render: bool,
) -> list[dict[str, Any]]:
    pdf_pages_dir = pages_dir / safe_stem(pdf_path)
    pdf_pages_dir.mkdir(parents=True, exist_ok=True)

    existing = sorted(pdf_pages_dir.glob("page_*.jpg"))
    if existing and not force_render:
        if max_pages is not None:
            existing = existing[:max_pages]
        rendered = []
        for idx, image_path in enumerate(existing, start=1):
            with Image.open(image_path) as im:
                rendered.append({
                    "page": idx,
                    "image_path": image_path,
                    "final_width": im.size[0],
                    "final_height": im.size[1],
                    "bytes": image_path.stat().st_size,
                    "from_cache": True,
                })
        return rendered

    poppler_path = find_poppler_path()
    print(f"  Rendering PDF pages: dpi={dpi}, max_long_edge={max_long_edge}")
    if poppler_path:
        pages = convert_from_path(str(pdf_path), dpi=dpi, poppler_path=poppler_path)
    else:
        pages = convert_from_path(str(pdf_path), dpi=dpi)

    if max_pages is not None:
        pages = pages[:max_pages]

    rendered = []
    for idx, page_image in enumerate(pages, start=1):
        image_path = pdf_pages_dir / f"page_{idx:03}.jpg"
        info = resize_and_save_jpeg(page_image, image_path, max_long_edge=max_long_edge, jpeg_quality=jpeg_quality)
        info.update({
            "page": idx,
            "image_path": image_path,
            "from_cache": False,
        })
        rendered.append(info)

    return rendered


# =============================================================================
# Model calls
# =============================================================================

def get_anthropic_client() -> Anthropic:
    if Anthropic is None:
        raise RuntimeError("anthropic パッケージがありません: pip install anthropic")
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY が未設定です。")
    return Anthropic(api_key=api_key)


def get_gemini_client():
    if genai is None:
        raise RuntimeError("google-genai パッケージがありません: pip install google-genai")
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY または GOOGLE_API_KEY が未設定です。")
    return genai.Client(api_key=api_key)


def get_openai_client() -> "OpenAI":
    if OpenAI is None:
        raise RuntimeError("openai パッケージがありません: pip install openai")
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY が未設定です。")
    return OpenAI(api_key=api_key)


def extract_claude_text(message: Any) -> str:
    parts: list[str] = []
    for block in getattr(message, "content", []) or []:
        if getattr(block, "type", None) == "text":
            parts.append(getattr(block, "text", ""))
    return "\n".join(parts).strip()


def extract_gemini_text(response: Any) -> str:
    try:
        text = getattr(response, "text", None)
        if text:
            return str(text).strip()
    except Exception:
        pass

    parts: list[str] = []
    candidates = getattr(response, "candidates", None) or []
    for cand in candidates:
        content = getattr(cand, "content", None)
        for part in getattr(content, "parts", []) or []:
            txt = getattr(part, "text", None)
            if txt:
                parts.append(str(txt))
    return "\n".join(parts).strip()


def gemini_finish_reason(response: Any) -> Optional[str]:
    candidates = getattr(response, "candidates", None) or []
    if not candidates:
        return None
    reason = getattr(candidates[0], "finish_reason", None)
    # google-genai returns an enum; normalise to its name for easy comparison.
    return getattr(reason, "name", None) or (str(reason) if reason is not None else None)


def build_page_prompt(pdf_name: str, page_number: int) -> str:
    return (
        f"{PROMPT}\n\n"
        f"この画像はPDF「{pdf_name}」の {page_number} ページ目です。"
    )


def run_anthropic(spec: ModelSpec, image_path: Path, page_prompt: str) -> dict[str, Any]:
    client = get_anthropic_client()
    b64 = image_to_base64(image_path)

    payload: dict[str, Any] = {
        "model": spec.model,
        "max_tokens": MAX_OUTPUT_TOKENS,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/jpeg",
                            "data": b64,
                        },
                    },
                    {
                        "type": "text",
                        "text": page_prompt,
                    },
                ],
            }
        ],
    }

    # Claude Opus 4.7 rejects non-default sampling parameters.
    if spec.send_temperature and spec.temperature is not None:
        payload["temperature"] = spec.temperature

    started = time.time()
    message = client.messages.create(**payload)
    elapsed = time.time() - started

    usage = getattr(message, "usage", None)
    input_tokens = get_attr(usage, "input_tokens")
    output_tokens = get_attr(usage, "output_tokens")
    stop_reason = getattr(message, "stop_reason", None)

    return {
        "text": extract_claude_text(message),
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": (input_tokens or 0) + (output_tokens or 0) if input_tokens is not None and output_tokens is not None else None,
        "thoughts_tokens": None,
        "finish_reason": stop_reason,
        "truncated": stop_reason == "max_tokens",
        "elapsed_sec": elapsed,
        "raw_usage": usage.__dict__ if hasattr(usage, "__dict__") else str(usage),
    }


def build_gemini_config(spec: ModelSpec):
    if genai_types is None:
        return None

    kwargs: dict[str, Any] = {
        "max_output_tokens": MAX_OUTPUT_TOKENS,
        "temperature": spec.temperature if spec.temperature is not None else 0.0,
    }

    # Gemini 3.x models reason by default and can burn the entire output budget
    # on hidden thinking before emitting any transcription, which truncates the
    # answer (seen with gemini-3-flash-preview). For OCR we want minimal thinking.
    # Only sent when the SDK supports ThinkingConfig; ignored otherwise.
    level = spec.gemini_thinking_level or "low"
    try:
        kwargs["thinking_config"] = genai_types.ThinkingConfig(thinking_level=level)
    except Exception:
        # Older google-genai or models that reject thinking_level: skip silently.
        pass

    return genai_types.GenerateContentConfig(**kwargs)


def run_gemini(spec: ModelSpec, image_path: Path, page_prompt: str) -> dict[str, Any]:
    client = get_gemini_client()

    if genai_types is None:
        raise RuntimeError("google.genai.types が読み込めません。google-genai を更新してください。")

    image_part = genai_types.Part.from_bytes(
        data=image_path.read_bytes(),
        mime_type="image/jpeg",
    )

    started = time.time()
    response = client.models.generate_content(
        model=spec.model,
        contents=[image_part, page_prompt],
        config=build_gemini_config(spec),
    )
    elapsed = time.time() - started

    usage = getattr(response, "usage_metadata", None)
    input_tokens = get_attr(usage, "prompt_token_count")
    output_tokens = get_attr(usage, "candidates_token_count")
    total_tokens = get_attr(usage, "total_token_count")
    thoughts_tokens = get_attr(usage, "thoughts_token_count")

    finish_reason = gemini_finish_reason(response)
    text = extract_gemini_text(response)
    truncated = (finish_reason == "MAX_TOKENS") or not text

    return {
        "text": text,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
        # candidates_token_count in google-genai already excludes thoughts, so we
        # pass thoughts separately for billing. (Verify against your console.)
        "thoughts_tokens": thoughts_tokens,
        "finish_reason": finish_reason,
        "truncated": truncated,
        "elapsed_sec": elapsed,
        "raw_usage": usage.__dict__ if hasattr(usage, "__dict__") else str(usage),
    }


def extract_openai_text(response: Any) -> str:
    # Responses API exposes a convenience aggregate of all output text.
    text = getattr(response, "output_text", None)
    if text:
        return str(text).strip()

    # Fallback: walk the structured output for text parts.
    parts: list[str] = []
    for item in getattr(response, "output", []) or []:
        for content in getattr(item, "content", []) or []:
            txt = getattr(content, "text", None)
            if txt:
                parts.append(str(txt))
    return "\n".join(parts).strip()


def run_openai(spec: ModelSpec, image_path: Path, page_prompt: str) -> dict[str, Any]:
    client = get_openai_client()
    b64 = image_to_base64(image_path)
    data_url = f"data:image/jpeg;base64,{b64}"

    request: dict[str, Any] = {
        "model": spec.model,
        "max_output_tokens": MAX_OUTPUT_TOKENS,
        "input": [
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": page_prompt},
                    {"type": "input_image", "image_url": data_url},
                ],
            }
        ],
    }

    # GPT-5 reasoning models bill hidden thinking tokens as output. Keep effort
    # low for transcription to limit cost and avoid exhausting the output budget.
    if spec.openai_reasoning_effort:
        request["reasoning"] = {"effort": spec.openai_reasoning_effort}

    # GPT-5 reasoning models only accept the default temperature, so we never
    # send a custom one for them. send_temperature is False for those specs.
    if spec.send_temperature and spec.temperature is not None:
        request["temperature"] = spec.temperature

    started = time.time()
    response = client.responses.create(**request)
    elapsed = time.time() - started

    usage = getattr(response, "usage", None)
    input_tokens = get_attr(usage, "input_tokens", "prompt_tokens")
    output_tokens = get_attr(usage, "output_tokens", "completion_tokens")
    total_tokens = get_attr(usage, "total_tokens")

    # reasoning_tokens live under output_tokens_details and ARE already counted
    # inside output_tokens for the Responses API, so they must NOT be added again
    # for billing; recorded only for visibility.
    details = get_attr(usage, "output_tokens_details")
    reasoning_tokens = get_attr(details, "reasoning_tokens")

    text = extract_openai_text(response)
    status = getattr(response, "status", None)
    incomplete = getattr(response, "incomplete_details", None)
    truncated = (status == "incomplete") or not text

    return {
        "text": text,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens if total_tokens is not None else (
            (input_tokens or 0) + (output_tokens or 0)
            if input_tokens is not None and output_tokens is not None else None
        ),
        # output_tokens already includes reasoning tokens for OpenAI, so flag it
        # so the caller passes thoughts=None to estimate_cost_usd (no double count).
        "thoughts_tokens": reasoning_tokens,
        "thoughts_already_in_output": True,
        "finish_reason": getattr(incomplete, "reason", None) or status,
        "truncated": truncated,
        "elapsed_sec": elapsed,
        "raw_usage": usage.__dict__ if hasattr(usage, "__dict__") else str(usage),
    }


def call_model_with_retries(spec: ModelSpec, image_path: Path, page_prompt: str) -> dict[str, Any]:
    last_exc: Optional[Exception] = None

    for attempt in range(1, RETRY_COUNT + 1):
        try:
            if spec.provider == "anthropic":
                return run_anthropic(spec, image_path, page_prompt)
            if spec.provider == "gemini":
                return run_gemini(spec, image_path, page_prompt)
            if spec.provider == "openai":
                return run_openai(spec, image_path, page_prompt)
            raise RuntimeError(f"Unknown provider: {spec.provider}")
        except KeyboardInterrupt:
            raise
        except Exception as exc:
            last_exc = exc
            print(f"      attempt {attempt}/{RETRY_COUNT} failed: {type(exc).__name__}: {exc}")
            if attempt >= RETRY_COUNT or not is_retryable_exception(exc):
                break
            sleep_for_retry(attempt, exc)

    assert last_exc is not None
    raise last_exc


# =============================================================================
# CSV / outputs
# =============================================================================

METRIC_FIELDS = [
    "run_id",
    "timestamp",
    "pdf",
    "page",
    "image_file",
    "image_width",
    "image_height",
    "image_bytes",
    "provider",
    "model",
    "label",
    "status",
    "elapsed_sec",
    "input_tokens",
    "output_tokens",
    "total_tokens",
    "thoughts_tokens",
    "estimated_cost_usd",
    "output_file",
    "error",
]


def append_csv(path: Path, row: dict[str, Any], fields: list[str]) -> None:
    file_exists = path.exists()
    with path.open("a", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        if not file_exists:
            writer.writeheader()
        writer.writerow(row)


def write_score_sheet_template(path: Path, run_rows: list[dict[str, Any]]) -> None:
    fields = [
        "pdf",
        "page",
        "label",
        "model",
        "output_file",
        "score_name_0_or_1",
        "score_date_0_or_1",
        "score_temperature_0_or_1",
        "score_time_0_or_1",
        "score_marks_0_to_2",
        "score_handwriting_0_to_5",
        "score_no_hallucination_0_to_3",
        "score_structure_0_to_2",
        "total_score",
        "notes",
    ]
    ok_rows = [r for r in run_rows if r.get("status") in {"ok", "cached", "truncated"}]
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for r in ok_rows:
            writer.writerow({
                "pdf": r.get("pdf", ""),
                "page": r.get("page", ""),
                "label": r.get("label", ""),
                "model": r.get("model", ""),
                "output_file": r.get("output_file", ""),
                "score_name_0_or_1": "",
                "score_date_0_or_1": "",
                "score_temperature_0_or_1": "",
                "score_time_0_or_1": "",
                "score_marks_0_to_2": "",
                "score_handwriting_0_to_5": "",
                "score_no_hallucination_0_to_3": "",
                "score_structure_0_to_2": "",
                "total_score": "",
                "notes": "",
            })


def write_aggregate_summary(path: Path, run_rows: list[dict[str, Any]]) -> None:
    fields = [
        "label",
        "provider",
        "model",
        "ok",
        "cached",
        "truncated",
        "error",
        "avg_elapsed_sec_ok_only",
        "sum_input_tokens",
        "sum_output_tokens",
        "sum_total_tokens",
        "sum_estimated_cost_usd",
    ]

    grouped: dict[str, list[dict[str, Any]]] = {}
    for r in run_rows:
        grouped.setdefault(str(r.get("label", "")), []).append(r)

    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for label, rows in sorted(grouped.items()):
            ok_rows = [r for r in rows if r.get("status") == "ok"]
            cached_rows = [r for r in rows if r.get("status") == "cached"]
            truncated_rows = [r for r in rows if r.get("status") == "truncated"]
            error_rows = [r for r in rows if r.get("status") == "error"]

            def sum_num(key: str) -> float:
                total = 0.0
                for r in rows:
                    v = r.get(key)
                    if v in (None, ""):
                        continue
                    try:
                        total += float(v)
                    except Exception:
                        pass
                return total

            elapsed_values = []
            for r in ok_rows:
                try:
                    elapsed_values.append(float(r.get("elapsed_sec", "")))
                except Exception:
                    pass

            spec = next((m for m in MODELS if m.label == label), None)

            writer.writerow({
                "label": label,
                "provider": spec.provider if spec else "",
                "model": spec.model if spec else "",
                "ok": len(ok_rows),
                "cached": len(cached_rows),
                "truncated": len(truncated_rows),
                "error": len(error_rows),
                "avg_elapsed_sec_ok_only": round(sum(elapsed_values) / len(elapsed_values), 2) if elapsed_values else "",
                "sum_input_tokens": int(sum_num("input_tokens")),
                "sum_output_tokens": int(sum_num("output_tokens")),
                "sum_total_tokens": int(sum_num("total_tokens")),
                "sum_estimated_cost_usd": round(sum_num("estimated_cost_usd"), 6),
            })


def write_readme(path: Path, run_id: str, target_dir: Path, max_pages: Optional[int], selected_models: list[ModelSpec]) -> None:
    lines = [
        "# Vision OCR Shootout v2",
        "",
        f"- Run ID: `{run_id}`",
        f"- Target dir: `{target_dir}`",
        f"- Max pages: `{max_pages if max_pages is not None else 'all'}`",
        "",
        "## Models",
        "",
    ]
    for m in selected_models:
        lines.append(f"- `{m.label}` → `{m.model}` ({m.provider}) — {m.notes}")
    lines += [
        "",
        "## Files",
        "",
        "- `pages/`: PDFから変換したページ画像",
        "- `outputs/`: モデル別OCR結果Markdown",
        "- `metrics_latest.csv`: この実行のメトリクス",
        "- `summary_latest.csv`: モデル別集計",
        "- `score_sheet_latest.csv`: 人間採点用テンプレ",
        "",
        "## Notes",
        "",
        "- `cached` は既存のOCR結果Markdownを再利用した行です。再実行課金を避けるためです。",
        "- 全モデルへ同じJPEG画像を投げています。",
        "- Gemini / Claudeの価格はスクリプト作成時点の標準API価格で概算しています。実請求額は各社コンソールを確認してください。",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


# =============================================================================
# Main processing
# =============================================================================

def select_models(model_filter: Optional[str]) -> list[ModelSpec]:
    if not model_filter:
        return [m for m in MODELS if m.enabled_by_default]

    labels = [x.strip() for x in model_filter.split(",") if x.strip()]
    known = {m.label: m for m in MODELS}
    unknown = [x for x in labels if x not in known]
    if unknown:
        raise SystemExit(f"Unknown model label(s): {', '.join(unknown)}\nUse --list-models to see valid labels.")
    return [known[x] for x in labels]


def list_models() -> None:
    print("Available model labels:")
    for m in MODELS:
        print(f"  {m.label:28s} {m.provider:10s} {m.model:28s}  {m.notes}")


def process_one_model(
    *,
    run_id: str,
    metrics_csv: Path,
    run_rows: list[dict[str, Any]],
    pdf_path: Path,
    page_info: dict[str, Any],
    outputs_dir: Path,
    errors_dir: Path,
    spec: ModelSpec,
    force: bool,
    pause_sec: float,
) -> None:
    page_num = int(page_info["page"])
    image_path: Path = page_info["image_path"]
    image_width = page_info.get("final_width", "")
    image_height = page_info.get("final_height", "")
    image_bytes = page_info.get("bytes", "")

    pdf_output_dir = outputs_dir / safe_stem(pdf_path) / f"page_{page_num:03}"
    pdf_error_dir = errors_dir / safe_stem(pdf_path) / f"page_{page_num:03}"
    pdf_output_dir.mkdir(parents=True, exist_ok=True)
    pdf_error_dir.mkdir(parents=True, exist_ok=True)

    output_file = pdf_output_dir / f"{spec.label}.md"
    usage_file = pdf_output_dir / f"{spec.label}.usage.json"
    error_file = pdf_error_dir / f"{spec.label}_ERROR.txt"

    timestamp = dt.datetime.now().isoformat(timespec="seconds")

    print(f"    {spec.label}")

    if output_file.exists() and output_file.stat().st_size > 0 and not force:
        print("      SKIP: cached output exists")
        row = {
            "run_id": run_id,
            "timestamp": timestamp,
            "pdf": pdf_path.name,
            "page": page_num,
            "image_file": str(image_path),
            "image_width": image_width,
            "image_height": image_height,
            "image_bytes": image_bytes,
            "provider": spec.provider,
            "model": spec.model,
            "label": spec.label,
            "status": "cached",
            "elapsed_sec": "",
            "input_tokens": "",
            "output_tokens": "",
            "total_tokens": "",
            "thoughts_tokens": "",
            "estimated_cost_usd": "",
            "output_file": str(output_file),
            "error": "",
        }
        append_csv(metrics_csv, row, METRIC_FIELDS)
        run_rows.append(row)
        return

    page_prompt = build_page_prompt(pdf_path.name, page_num)

    try:
        result = call_model_with_retries(spec, image_path, page_prompt)
        text = result.get("text", "").strip()
        if not text:
            text = "[EMPTY RESPONSE]"

        input_tokens = result.get("input_tokens")
        output_tokens = result.get("output_tokens")
        total_tokens = result.get("total_tokens")
        thoughts_tokens = result.get("thoughts_tokens")
        finish_reason = result.get("finish_reason")
        truncated = bool(result.get("truncated"))
        elapsed_sec = float(result.get("elapsed_sec") or 0.0)

        # For OpenAI, reasoning tokens are already inside output_tokens, so do not
        # add them again. For Gemini, candidates_token_count excludes thoughts, so
        # add them. The run_* functions signal this via thoughts_already_in_output.
        thoughts_for_cost = None if result.get("thoughts_already_in_output") else thoughts_tokens
        estimated_cost = estimate_cost_usd(spec, input_tokens, output_tokens, thoughts_for_cost)

        # A truncated/empty answer is not a clean "ok": flag it so the score sheet
        # and summary do not silently treat a cut-off transcription as a success.
        status = "truncated" if truncated else "ok"

        header = (
            f"<!--\n"
            f"run_id: {run_id}\n"
            f"pdf: {pdf_path.name}\n"
            f"page: {page_num}\n"
            f"provider: {spec.provider}\n"
            f"model: {spec.model}\n"
            f"label: {spec.label}\n"
            f"image: {image_path.name} ({image_width}x{image_height}, {image_bytes} bytes)\n"
            f"status: {status}\n"
            f"finish_reason: {finish_reason}\n"
            f"elapsed_sec: {elapsed_sec:.2f}\n"
            f"input_tokens: {input_tokens}\n"
            f"output_tokens: {output_tokens}\n"
            f"thoughts_tokens: {thoughts_tokens}\n"
            f"total_tokens: {total_tokens}\n"
            f"estimated_cost_usd: {estimated_cost}\n"
            f"-->\n\n"
        )
        if truncated:
            header += (
                "> **⚠ 出力が途中で切れた可能性があります "
                f"(finish_reason={finish_reason})。**\n"
                "> MAX_OUTPUT_TOKENS を増やすか reasoning/thinking を下げて再実行してください。\n\n"
            )
        output_file.write_text(header + text + "\n", encoding="utf-8")

        usage_payload = {
            "run_id": run_id,
            "provider": spec.provider,
            "model": spec.model,
            "label": spec.label,
            "pdf": pdf_path.name,
            "page": page_num,
            "image_file": str(image_path),
            "status": status,
            "finish_reason": finish_reason,
            "elapsed_sec": elapsed_sec,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": total_tokens,
            "thoughts_tokens": thoughts_tokens,
            "estimated_cost_usd": estimated_cost,
            "raw_usage": result.get("raw_usage"),
        }
        write_json(usage_file, usage_payload)

        row = {
            "run_id": run_id,
            "timestamp": timestamp,
            "pdf": pdf_path.name,
            "page": page_num,
            "image_file": str(image_path),
            "image_width": image_width,
            "image_height": image_height,
            "image_bytes": image_bytes,
            "provider": spec.provider,
            "model": spec.model,
            "label": spec.label,
            "status": status,
            "elapsed_sec": round(elapsed_sec, 2),
            "input_tokens": input_tokens if input_tokens is not None else "",
            "output_tokens": output_tokens if output_tokens is not None else "",
            "total_tokens": total_tokens if total_tokens is not None else "",
            "thoughts_tokens": thoughts_tokens if thoughts_tokens is not None else "",
            "estimated_cost_usd": round(estimated_cost, 8) if estimated_cost is not None else "",
            "output_file": str(output_file),
            "error": "" if not truncated else f"truncated (finish_reason={finish_reason})",
        }
        append_csv(metrics_csv, row, METRIC_FIELDS)
        run_rows.append(row)
        if truncated:
            print(f"      WARNING: truncated output (finish_reason={finish_reason})")

    except KeyboardInterrupt:
        raise
    except Exception as exc:
        error_text = f"{type(exc).__name__}: {exc}"
        error_file.write_text(error_text + "\n\n" + traceback.format_exc(), encoding="utf-8")

        row = {
            "run_id": run_id,
            "timestamp": timestamp,
            "pdf": pdf_path.name,
            "page": page_num,
            "image_file": str(image_path),
            "image_width": image_width,
            "image_height": image_height,
            "image_bytes": image_bytes,
            "provider": spec.provider,
            "model": spec.model,
            "label": spec.label,
            "status": "error",
            "elapsed_sec": "",
            "input_tokens": "",
            "output_tokens": "",
            "total_tokens": "",
            "thoughts_tokens": "",
            "estimated_cost_usd": "",
            "output_file": str(error_file),
            "error": error_text,
        }
        append_csv(metrics_csv, row, METRIC_FIELDS)
        run_rows.append(row)
        print(f"      ERROR: {error_text}")

    if pause_sec > 0:
        time.sleep(pause_sec)


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare Vision OCR across Claude and Gemini models.")
    parser.add_argument("--target-dir", default=str(DEFAULT_TARGET_DIR), help=r"PDF folder. Default: C:\test")
    parser.add_argument("--out-dir", default=None, help="Output directory. Default: <target-dir>\\_vision_compare_v2")
    parser.add_argument("--max-pages", default=DEFAULT_MAX_PAGES, help="Max pages per PDF. Use 'all' for all pages. Default: 5")
    parser.add_argument("--models", default=None, help="Comma-separated model labels. Use --list-models.")
    parser.add_argument("--list-models", action="store_true", help="List model labels and exit.")
    parser.add_argument("--force", action="store_true", help="Re-run OCR even if output files already exist.")
    parser.add_argument("--force-render", action="store_true", help="Re-render page images even if cached images exist.")
    parser.add_argument("--dpi", type=int, default=DEFAULT_DPI, help=f"PDF render DPI. Default: {DEFAULT_DPI}")
    parser.add_argument("--long-edge", type=int, default=DEFAULT_MAX_LONG_EDGE, help=f"Max long edge for JPEG. Default: {DEFAULT_MAX_LONG_EDGE}")
    parser.add_argument("--jpeg-quality", type=int, default=DEFAULT_JPEG_QUALITY, help=f"JPEG quality. Default: {DEFAULT_JPEG_QUALITY}")
    parser.add_argument("--pause", type=float, default=DEFAULT_PAUSE_SEC, help=f"Pause between API calls in seconds. Default: {DEFAULT_PAUSE_SEC}")
    args = parser.parse_args()

    if args.list_models:
        list_models()
        return

    target_dir = Path(args.target_dir)
    out_dir = Path(args.out_dir) if args.out_dir else target_dir / DEFAULT_OUT_DIR_NAME
    max_pages = parse_max_pages(args.max_pages)
    selected_models = select_models(args.models)
    run_id = now_stamp()

    if not target_dir.exists():
        raise SystemExit(f"Target directory not found: {target_dir}")

    pdf_files = sorted(target_dir.glob("*.pdf"))
    if not pdf_files:
        raise SystemExit(f"PDFが見つかりません: {target_dir}")

    dirs = ensure_dirs(out_dir)
    metrics_csv = out_dir / "metrics_latest.csv"
    summary_csv = out_dir / "summary_latest.csv"
    score_sheet_csv = out_dir / "score_sheet_latest.csv"
    readme_md = out_dir / "README_latest.md"
    prompt_txt = out_dir / "prompt_latest.txt"

    # Fresh per-run metrics files. Existing OCR markdowns can still be cached.
    for p in [metrics_csv, summary_csv, score_sheet_csv]:
        if p.exists():
            p.unlink()

    prompt_txt.write_text(PROMPT, encoding="utf-8")
    write_readme(readme_md, run_id, target_dir, max_pages, selected_models)

    print("Vision OCR Shootout v2")
    print(f"  target_dir: {target_dir}")
    print(f"  out_dir   : {out_dir}")
    print(f"  max_pages : {max_pages if max_pages is not None else 'all'}")
    print(f"  models    : {', '.join(m.label for m in selected_models)}")
    print(f"  force     : {args.force}")
    print("")

    run_rows: list[dict[str, Any]] = []

    try:
        for pdf_path in pdf_files:
            print(f"PDF: {pdf_path.name}")
            rendered_pages = render_pdf_to_images(
                pdf_path=pdf_path,
                pages_dir=dirs["pages"],
                dpi=args.dpi,
                max_long_edge=args.long_edge,
                jpeg_quality=args.jpeg_quality,
                max_pages=max_pages,
                force_render=args.force_render,
            )

            for page_info in rendered_pages:
                page_num = int(page_info["page"])
                image_path = page_info["image_path"]
                width = page_info.get("final_width")
                height = page_info.get("final_height")
                from_cache = page_info.get("from_cache", False)
                print(f"  Page {page_num}: {image_path.name} ({width}x{height}){' [cached image]' if from_cache else ''}")

                for spec in selected_models:
                    process_one_model(
                        run_id=run_id,
                        metrics_csv=metrics_csv,
                        run_rows=run_rows,
                        pdf_path=pdf_path,
                        page_info=page_info,
                        outputs_dir=dirs["outputs"],
                        errors_dir=dirs["errors"],
                        spec=spec,
                        force=args.force,
                        pause_sec=args.pause,
                    )

    finally:
        write_aggregate_summary(summary_csv, run_rows)
        write_score_sheet_template(score_sheet_csv, run_rows)

    print("")
    print("Done.")
    print(f"  Metrics     : {metrics_csv}")
    print(f"  Summary     : {summary_csv}")
    print(f"  Score sheet : {score_sheet_csv}")
    print(f"  Outputs     : {dirs['outputs']}")


if __name__ == "__main__":
    main()
