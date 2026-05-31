"""
OCR script for PDF files in C:\test
Uses pytesseract + pdf2image to extract text from scanned PDFs
"""
import os
import glob
import pytesseract
from pdf2image import convert_from_path

# Set Tesseract path
pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

# Poppler path (pdf2image needs it on Windows)
POPPLER_PATH = r"C:\Users\hikar\AppData\Local\Microsoft\WinGet\Packages\oschwartz10612.Poppler_Microsoft.Winget.Source_8wekyb3d8bbwe\poppler-25.07.0\Library\bin"

FOLDER = r"C:\test"
pdf_files = glob.glob(os.path.join(FOLDER, "**", "*.pdf"), recursive=True) + \
            glob.glob(os.path.join(FOLDER, "**", "*.PDF"), recursive=True)

if not pdf_files:
    print("PDFファイルが見つかりませんでした。")
    exit(1)

print(f"対象PDFファイル: {len(pdf_files)} 件\n")

for pdf_path in pdf_files:
    pdf_name = os.path.splitext(os.path.basename(pdf_path))[0]
    output_path = os.path.join(os.path.dirname(pdf_path), pdf_name + ".txt")

    print(f"処理中: {os.path.basename(pdf_path)}")

    try:
        # Convert PDF pages to images
        kwargs = {}
        if POPPLER_PATH:
            kwargs["poppler_path"] = POPPLER_PATH

        images = convert_from_path(pdf_path, dpi=300, **kwargs)
        print(f"  ページ数: {len(images)}")

        all_text = []
        for i, image in enumerate(images):
            print(f"  OCR中... ページ {i+1}/{len(images)}", end="\r")
            # Use Japanese + English OCR
            text = pytesseract.image_to_string(image, lang="jpn+eng")
            all_text.append(f"--- ページ {i+1} ---\n{text}")

        full_text = "\n\n".join(all_text)

        with open(output_path, "w", encoding="utf-8") as f:
            f.write(full_text)

        print(f"\n  ✓ 保存完了: {os.path.basename(output_path)}")
        print(f"    文字数: {len(full_text)} 文字\n")

    except Exception as e:
        print(f"\n  ✗ エラー: {e}\n")

print("OCR処理が完了しました。")
