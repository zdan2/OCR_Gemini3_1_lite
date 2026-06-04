# 連絡帳パイプライン: Dropbox(rclone)同期フォルダを監視して
# Gemini で抽出 → SQLite に登録 → 日次レポート生成 → Gmail 送信
FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app \
    TZ=Asia/Tokyo \
    BROWSER_PATH=/usr/bin/chromium

# tzdata: ログ・日付の Asia/Tokyo 表示用
# poppler-utils: pdf2image 用
# chromium + fonts-ipafont-gothic: send_report.py の月次PDF生成(html_to_pdf)用。
#   フォントが無いと日本語が豆腐(□)になるため日本語ゴシックを同梱する。
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      tzdata poppler-utils chromium fonts-ipafont-gothic \
 && rm -rf /var/lib/apt/lists/* \
 && ln -sf /usr/share/zoneinfo/Asia/Tokyo /etc/localtime \
 && echo "Asia/Tokyo" > /etc/timezone

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 本番パイプラインの Python ファイルだけ取り込む（experimental は .dockerignore で除外）
COPY *.py /app/

# 実行時は /data を CWD にする。
# build_daily_report.py 等は相対パス（renrakucho.db, _reports/, alias.json, *名簿*.xlsx,
# .watch_state.json）を CWD から読み書きするため、永続ボリュームを直接 CWD にして
# コード改修ゼロで動かす設計。
WORKDIR /data

# 既定: 監視常駐モード（30秒ループ）+ 取り込み後に日次メール送信
# 送信を止めたい場合は compose.yml の command から --send を外す
CMD ["python", "/app/watch_folder.py", "--dir", "/scansnap", "--send"]
