import base64
import csv
import os
import time
import traceback
from pathlib import Path
from typing import Optional

from PIL import Image
from pdf2image import convert_from_path

from anthropic import Anthropic
from google import genai
from google.genai import types


TARGET_DIR = Path(r"C:\test")
OUT_DIR = TARGET_DIR / "_vision_compare"
PAGES_DIR = OUT_DIR / "pages"
OUTPUTS_DIR = OUT_DIR / "outputs"
METRICS_CSV = OUT_DIR / "metrics.csv"

DPI = 200
MAX_LONG_EDGE = 1800

# 最初は5ページくらいがおすすめ。全部やるなら None。
MAX_PAGES_PER_PDF: Optional[int] = 5

MAX_OUTPUT_TOKENS = 4096

MODELS = [
    {
        "provider": "anthropic",
        "model": "claude-sonnet-4-6",
        "label": "claude_sonnet_4_6",
    },
    {
        "provider": "anthropic",
        "model": "claude-opus-4-7",
        "label": "claude_opus_4_7",
    },
    {
        "provider": "gemini",
        "model": "gemini-3.5-flash",
        "label": "gemini_3_5_flash",
    },
    {
        "provider": "gemini",
        "model": "gemini-3.1-flash-lite",
        "label": "gemini_3_1_flash_lite",
    },
    {
        "provider": "gemini",
        "model": "gemini-3.1-pro-preview",
        "label": "gemini_3_1_pro_preview",
    },
    {
        "provider": "gemini",
        "model": "gemini-2.5-flash",
        "label": "gemini_2_5_flash",
    },
]

# USD / 1M tokens
PRICE_PER_MTOK = {
    ("anthropic", "claude-sonnet-4-6"): {"input": 3.00, "output": 15.00},
    ("anthropic", "claude-opus-4-7"): {"input": 5.00, "output": 25.00},

    ("gemini", "gemini-3.5-flash"): {"input": 1.50, "output": 9.00},
    ("gemini", "gemini-3.1-flash-lite"): {"input": 0.25, "output": 1.50},
    ("gemini", "gemini-3.1-pro-preview"): {"input": 2.00, "output": 12.00},
    ("gemini", "gemini-2.5-flash"): {"input": 0.30, "output": 2.50},
}

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
- 表やフォームの構造はMarkdownで整理する
- 手書き本文は、可能な限りそのまま転記する

出力形式:
# OCR結果

## 基本情報
- 日付:
- 氏名:
- ページ内で目立つ項目:

## 読み取り本文
Markdownで、表・項目・手書き文を整理して出力。

## 判読が怪しい箇所
- 箇条書きで列挙。
""".strip()


def ensure_dirs() -> None:
    PAGES_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)


def resize_and_save_jpeg(image: Image.Image, output_path: Path) -> None:
    img = image.convert("RGB")
    width, height = img.size
    long_edge = max(width, height)

    if long_edge > MAX_LONG_EDGE:
        scale = MAX_LONG_EDGE / long_edge
        new_size = (int(width * scale), int(height * scale))
        img = img.resize(new_size, Image.LANCZOS)

    img.save(output_path, "JPEG", quality=92, optimize=True)


def render_pdf_to_images(pdf_path: Path) -> list[Path]:
    pdf_pages_dir = PAGES_DIR / pdf_path.stem
    pdf_pages_dir.mkdir(parents=True, exist_ok=True)

    pages = convert_from_path(str(pdf_path), dpi=DPI)

    if MAX_PAGES_PER_PDF is not None:
        pages = pages[:MAX_PAGES_PER_PDF]

    image_paths = []
    for index, page in enumerate(pages, start=1):
        image_path = pdf_pages_dir / f"page_{index:03}.jpg"
        if not image_path.exists():
            resize_and_save_jpeg(page, image_path)
        image_paths.append(image_path)

    return image_paths


def image_to_base64(path: Path) -> str:
    return base64.b64encode(path.read_bytes()).decode("utf-8")


def text_from_claude_response(message) -> str:
    parts = []
    for block in message.content:
        if getattr(block, "type", None) == "text":
            parts.append(block.text)
    return "\n".join(parts).strip()


def run_anthropic(model: str, image_path: Path) -> dict:
    client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    b64 = image_to_base64(image_path)

    start = time.time()
    message = client.messages.create(
        model=model,
        max_tokens=MAX_OUTPUT_TOKENS,
        temperature=0,
        messages=[
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
                        "text": PROMPT,
                    },
                ],
            }
        ],
    )
    elapsed = time.time() - start

    usage = getattr(message, "usage", None)
    input_tokens = getattr(usage, "input_tokens", None)
    output_tokens = getattr(usage, "output_tokens", None)

    return {
        "text": text_from_claude_response(message),
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "elapsed_sec": elapsed,
    }


def run_gemini(model: str, image_path: Path) -> dict:
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

    image_part = types.Part.from_bytes(
        data=image_path.read_bytes(),
        mime_type="image/jpeg",
    )

    start = time.time()
    response = client.models.generate_content(
        model=model,
        contents=[
            image_part,
            PROMPT,
        ],
        config=types.GenerateContentConfig(
            temperature=0,
            max_output_tokens=MAX_OUTPUT_TOKENS,
        ),
    )
    elapsed = time.time() - start

    text = getattr(response, "text", "") or ""

    usage = getattr(response, "usage_metadata", None)
    input_tokens = getattr(usage, "prompt_token_count", None)
    output_tokens = getattr(usage, "candidates_token_count", None)

    return {
        "text": text.strip(),
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "elapsed_sec": elapsed,
    }


def estimate_cost_usd(provider: str, model: str, input_tokens, output_tokens) -> Optional[float]:
    if input_tokens is None or output_tokens is None:
        return None

    price = PRICE_PER_MTOK.get((provider, model))
    if not price:
        return None

    return (
        input_tokens / 1_000_000 * price["input"]
        + output_tokens / 1_000_000 * price["output"]
    )


def append_metric(row: dict) -> None:
    file_exists = METRICS_CSV.exists()

    fields = [
        "pdf",
        "page",
        "provider",
        "model",
        "label",
        "status",
        "elapsed_sec",
        "input_tokens",
        "output_tokens",
        "estimated_cost_usd",
        "output_file",
        "error",
    ]

    with METRICS_CSV.open("a", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        if not file_exists:
            writer.writeheader()
        writer.writerow(row)


def run_model_on_image(pdf_path: Path, page_number: int, image_path: Path, model_info: dict) -> None:
    provider = model_info["provider"]
    model = model_info["model"]
    label = model_info["label"]

    out_subdir = OUTPUTS_DIR / pdf_path.stem / f"page_{page_number:03}"
    out_subdir.mkdir(parents=True, exist_ok=True)
    output_file = out_subdir / f"{label}.md"

    print(f"    {label}")

    try:
        if provider == "anthropic":
            if not os.environ.get("ANTHROPIC_API_KEY"):
                raise RuntimeError("ANTHROPIC_API_KEY が未設定です。")
            result = run_anthropic(model, image_path)

        elif provider == "gemini":
            if not os.environ.get("GEMINI_API_KEY"):
                raise RuntimeError("GEMINI_API_KEY が未設定です。")
            result = run_gemini(model, image_path)

        else:
            raise RuntimeError(f"Unknown provider: {provider}")

        text = result["text"]
        input_tokens = result["input_tokens"]
        output_tokens = result["output_tokens"]
        elapsed_sec = result["elapsed_sec"]
        cost = estimate_cost_usd(provider, model, input_tokens, output_tokens)

        output_file.write_text(text, encoding="utf-8")

        append_metric({
            "pdf": pdf_path.name,
            "page": page_number,
            "provider": provider,
            "model": model,
            "label": label,
            "status": "ok",
            "elapsed_sec": round(elapsed_sec, 2),
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "estimated_cost_usd": round(cost, 8) if cost is not None else "",
            "output_file": str(output_file),
            "error": "",
        })

    except Exception as e:
        error_text = f"{type(e).__name__}: {e}"
        err_file = out_subdir / f"{label}_ERROR.txt"
        err_file.write_text(
            error_text + "\n\n" + traceback.format_exc(),
            encoding="utf-8",
        )

        append_metric({
            "pdf": pdf_path.name,
            "page": page_number,
            "provider": provider,
            "model": model,
            "label": label,
            "status": "error",
            "elapsed_sec": "",
            "input_tokens": "",
            "output_tokens": "",
            "estimated_cost_usd": "",
            "output_file": str(err_file),
            "error": error_text,
        })

        print(f"      ERROR: {error_text}")


def main() -> None:
    ensure_dirs()

    pdf_files = sorted(TARGET_DIR.glob("*.pdf"))
    if not pdf_files:
        print("PDFが見つかりません。")
        return

    for pdf_path in pdf_files:
        print(f"\nPDF: {pdf_path.name}")
        image_paths = render_pdf_to_images(pdf_path)

        for page_number, image_path in enumerate(image_paths, start=1):
            print(f"  Page {page_number}: {image_path.name}")

            for model_info in MODELS:
                run_model_on_image(pdf_path, page_number, image_path, model_info)

    print("\nDone.")
    print(f"Metrics: {METRICS_CSV}")
    print(f"Outputs: {OUTPUTS_DIR}")


if __name__ == "__main__":
    main()