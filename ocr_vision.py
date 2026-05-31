"""
Claude Vision OCR script
PDF を画像に変換し、Claude Vision API で日本語OCRを実行します。
"""
import os
import sys
import base64
import glob
from pathlib import Path
from pdf2image import convert_from_path
import anthropic

# === 設定 ===
POPPLER_PATH = r"C:\Users\hikar\AppData\Local\Microsoft\WinGet\Packages\oschwartz10612.Poppler_Microsoft.Winget.Source_8wekyb3d8bbwe\poppler-25.07.0\Library\bin"
FOLDER = r"C:\test"
DPI = 200  # 解像度（高いほど精度UP・処理時間増加）

# === Anthropic クライアント ===
client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY", ""))

def image_to_base64(image) -> str:
    """PIL Imageをbase64文字列に変換"""
    import io
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return base64.standard_b64encode(buf.getvalue()).decode("utf-8")

def ocr_page_with_claude(image, page_num: int) -> str:
    """Claude Vision API で1ページをOCR"""
    img_b64 = image_to_base64(image)

    response = client.messages.create(
        model="claude-opus-4-7",
        max_tokens=4096,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/png",
                            "data": img_b64,
                        },
                    },
                    {
                        "type": "text",
                        "text": (
                            "この画像は保育園・幼稚園の連絡帳（家庭での生活記録）です。\n"
                            "画像に書かれているすべてのテキストを正確に読み取り、\n"
                            "レイアウトをできるだけ保持しながらテキストとして出力してください。\n"
                            "手書き文字も含めて読み取ってください。\n"
                            "読み取れない部分は「[不明]」と記載してください。"
                        ),
                    },
                ],
            }
        ],
    )

    return response.content[0].text

def ocr_pdf(pdf_path: str) -> None:
    """PDFをOCRしてテキストファイルに保存"""
    pdf_name = Path(pdf_path).stem
    output_path = Path(pdf_path).parent / f"{pdf_name}_vision.txt"

    print(f"\n処理中: {Path(pdf_path).name}")

    # PDF -> 画像変換
    print(f"  PDF -> 画像変換中... (DPI={DPI})")
    images = convert_from_path(pdf_path, dpi=DPI, poppler_path=POPPLER_PATH)
    print(f"  ページ数: {len(images)}")

    all_text = []
    for i, image in enumerate(images):
        print(f"  Claude Vision OCR中... ページ {i+1}/{len(images)}", end="", flush=True)
        text = ocr_page_with_claude(image, i + 1)
        all_text.append(f"{'='*50}\nページ {i+1}\n{'='*50}\n{text}")
        print(" -> 完了")

    full_text = "\n\n".join(all_text)
    output_path.write_text(full_text, encoding="utf-8")

    print(f"  保存完了: {output_path.name}")
    print(f"  文字数: {len(full_text):,} 文字")

# === メイン ===
pdf_files = glob.glob(os.path.join(FOLDER, "**", "*.pdf"), recursive=True)
pdf_files = [p for p in pdf_files if not p.endswith("_vision.pdf")]

if not pdf_files:
    print("PDFファイルが見つかりませんでした。")
    sys.exit(1)

print(f"対象: {len(pdf_files)} 件のPDF")
for pdf in pdf_files:
    ocr_pdf(pdf)

print("\nすべてのOCR処理が完了しました。")
