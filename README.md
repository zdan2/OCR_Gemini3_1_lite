# 連絡帳パイプライン 運用手順（氏名の修正と再送）

手書きの保育園連絡帳PDFを取り込み → Gemini で抽出 → 名簿照合 → SQLite蓄積 →
日次/月次レポートをGmail送信する自動パイプライン。本番は **TrueNAS のDockerコンテナ
`renrakucho`** で常駐（新しいスキャンが入ると自動で取り込み〜日次メール送信まで実行）。

このREADMEは **「氏名の誤読を直して、必要なら報告メールを送り直す」** 運用手順をまとめたもの。

---

## 0. 場所と前提（最初に覚える）

| 何 | 場所 |
|---|---|
| コンテナ名 | `renrakucho` |
| データ（DB・設定・レポート） | ホスト `/mnt/main/renrakucho/data` ＝ コンテナ内 `/data` |
| コード（スクリプト） | コンテナ内 `/app`（GitHubリポジトリが正） |
| 補正ファイル | `/data/corrections.json`（ホスト `/mnt/main/renrakucho/data/corrections.json`） |
| 別名辞書 | `/data/alias.json` |
| 名簿 | `/data/在園児各月児童名簿*.xlsx` |
| 原本PDF | `/scansnap`（Dropbox同期・読み取り専用） |

- 操作は TrueNAS に **SSH**。`docker` 系・`/data` への書き込みは **`sudo` が必要**。
- `/data` はコンテナ(root)所有。VS Codeで直接ファイルを作ると権限エラー（後述の対処を参照）。

---

## 全体の流れ

```
① 点検        review_queue.py で「要確認 / 怪しい確定」を (PDF,ページ) 付きで一覧
   ↓
② 補正を書く   /data/corrections.json に {pdf, page, child} を記入
   ↓
③ ドライラン   apply_corrections.py --dry-run で当たりを確認（DBは変えない）
   ↓
④ 適用        apply_corrections.py でDBを直す（自動バックアップ＋日次CSV再生成）
   ↓
⑤ 再送(任意)  既に送った日を直したら send_report.py で手動再送
```

繰り返し出る誤読は corrections ではなく **`alias.json` に登録**（将来も自動で直る。最後の章参照）。

---

## ① 点検：どれを直すか洗い出す

```bash
# 対象月の「要確認＋低スコア確定（サイレント誤確定の疑い）」を一覧
sudo docker exec renrakucho python /app/review_queue.py --month 2026-06

# child空欄の雛形JSONも出す（/data/_reports/corrections_template.json）
sudo docker exec renrakucho python /app/review_queue.py --month 2026-06 --template
sudo docker exec renrakucho cat /data/_reports/corrections_template.json
```

出力例の見方：
```
[①要確認] 2026-06-02 score= 44.4 読=かしわで てる | 20260602どんぐり_家庭での生活.pdf p9 | （コメント先頭）
[②低確定] 2026-06-02 score= 75.0 読=大久保汐理 | 20260602どんぐり_家庭での生活.pdf p7 | …
```
- `①要確認` … 児童が未割当。原本を見て正しい子を割り当てる。
- `②低確定` … 自動確定したがスコアが低い＝別人の可能性。原本と突き合わせる。
- `20260602…pdf p9` … 補正に使う **キー（PDFファイル名＋ページ番号）**。

---

## ② 補正を書く：corrections.json

### 置き場所と権限（重要）
`/data` は root 所有なので、まず**自分(ndholovu)が編集できるファイルを用意**する：

```bash
sudo touch /mnt/main/renrakucho/data/corrections.json
sudo chown ndholovu /mnt/main/renrakucho/data/corrections.json
```
これで VS Code(Remote-SSH) から `/mnt/main/renrakucho/data/corrections.json` を編集できる。
（コンテナはrootなので、ndholovu所有でも問題なく読める）

> ⚠ ファイル名は必ず **`corrections.json`**（r が入る）。`collections.json` 等の誤記は読まれない。

### 書式（配列・1要素＝1ページの補正）
```json
[
  {"pdf": "20260602どんぐり_家庭での生活.pdf", "page": 9,
   "child": "まるやまちゅうや", "note": "原本確認 2026-06-04"}
]
```
| キー | 意味 |
|---|---|
| `pdf` | 原本PDFのファイル名（review_queue の一覧/雛形の値をそのまま） |
| `page` | ページ番号（同上） |
| `child` | 正しい児童。**名簿のかな氏名**（または漢字氏名）。例 `まるやまちゅうや` / `丸山宙也` |
| `note` | 任意・監査用メモ（DBには入らない） |

---

## ③ ドライランで確認（DBは変えない）

```bash
sudo docker exec renrakucho python /app/apply_corrections.py --dry-run
```
出力の読み方：
- `[i] (dry) …pdf p9: '読み取り名' -> 丸山宙也（どんぐり）` … 直る予定。OK。
- `[i] スキップ: 児童 'xxx' が N月 名簿に居ません` … child の表記ミス。名簿のかな氏名に直す。
- `[i] スキップ: 該当行なし pdf=… p…` … pdf/page が間違い。review_queue の値を再確認。
- `[i] [衝突] 〇〇 の 日付 は既に別行あり …スキップ` … 同じ児童が同日に既存。**勝手に上書きしない**安全動作。人が原本を確認して判断。

---

## ④ 適用（DBを直す）

```bash
sudo docker exec renrakucho python /app/apply_corrections.py
```
- 実行前に **DBを自動バックアップ**（`/data/renrakucho.db.bak_before_corrections_…`）。
- **冪等**（何度流しても同じ結果）。影響した日の **日次CSVも再生成**。
- watcher は新しいスキャン取込時にも自動で apply_corrections を呼ぶので、置いておけば次回以降も自動適用される。

> これで **DBとレポートは直る。ただしメールは送られない**（次章）。

---

## ⑤ 再送：直した報告を送り直す（必要な日だけ）

修正は**自動では再送信されない**（重複メール防止のため意図的）。

| 状況 | メール |
|---|---|
| 新しいスキャンが来た日 | 取込時に補正→送信なので最初から正しい内容で届く |
| 既に送った過去の日を直した | DBは直るが**送信済みメールは差し替わらない** → 手動再送 |
| 月次サマリ | 実行のたび現在のDBから作る → 補正後に走らせれば自然に正しい |

```bash
# 日次（その日を指定。きいちご・どんぐり 各1通＋原本PDF添付）
sudo docker exec renrakucho python /app/send_report.py daily --date 2026-06-02

# 月次（その月。クラス別 各1通＋詳細PDF添付）
sudo docker exec renrakucho python /app/send_report.py monthly --month 2026-06
```
不安なら先頭に `--dry-run` を付けると送らず `/data/_reports/email_preview_*.html` にプレビューを書き出す。
内容を確認 → 問題なければ `--dry-run` を外して本送信。

---

## くり返す誤読は alias.json（corrections と使い分け）

- **この1ページだけ** の修正 → `corrections.json`
- **同じ書き方が毎回出る**（例: 丸山宙也が チョ/キョ/キュ… と読まれ続ける）→ `/data/alias.json` に登録すると**将来のスキャンも自動で正解**になる。

```bash
# 例: /data/alias.json に "誤読のかな": "名簿のかな氏名" を足す
#   { "ちょ": "まるやまちゅうや", "きょ": "まるやまちゅうや", ... }
```
alias.json を直したら、リポジトリ側にも同じ変更を入れて push しておくと再構築しても消えない。
（部分一致で拾うので、短いキーは他児童と衝突しないか名簿で確認してから足す）

---

## よくある詰まり

| 症状 | 対処 |
|---|---|
| VS Codeで保存できない `EACCES permission denied` | `/data`がroot所有。`sudo touch`＋`sudo chown ndholovu` でファイルを用意してから編集 |
| 補正が効かない | ファイル名が `corrections.json` か（`collections.json` 等の誤記）。`pdf`/`page` が一覧の値と一致しているか |
| `[衝突] …スキップ` | 同児童が同日に既存。原本を見てどちらが正しいか確認（自動では潰さない） |
| 日次メールに原本PDFが付かない | 原本は `/scansnap`(SCAN_DIR)から探す。該当PDFが同期フォルダに在るか確認 |
| 月次PDFが作れない | コンテナに chromium 同梱済み。`docker exec renrakucho chromium --version` で確認 |

---

## コマンド早見表

```bash
# 点検
sudo docker exec renrakucho python /app/review_queue.py --month 2026-06
sudo docker exec renrakucho python /app/review_queue.py --month 2026-06 --template

# 補正ファイル準備（初回）
sudo touch /mnt/main/renrakucho/data/corrections.json
sudo chown ndholovu /mnt/main/renrakucho/data/corrections.json
#   → VS Codeで /mnt/main/renrakucho/data/corrections.json を編集

# 補正の確認→適用
sudo docker exec renrakucho python /app/apply_corrections.py --dry-run
sudo docker exec renrakucho python /app/apply_corrections.py

# 再送（必要な日だけ）
sudo docker exec renrakucho python /app/send_report.py daily   --date 2026-06-02 --dry-run
sudo docker exec renrakucho python /app/send_report.py daily   --date 2026-06-02
sudo docker exec renrakucho python /app/send_report.py monthly --month 2026-06 --dry-run
sudo docker exec renrakucho python /app/send_report.py monthly --month 2026-06
```

---

## 参考：コード変更を本番に反映する手順（開発者向け）

1. 手元（`C:\test`）で改修 → GitHub `zdan2/OCR_Gemini3_1_lite` に push
2. TrueNAS のスタックディレクトリで:
   ```bash
   sudo git pull
   sudo docker compose up -d --build --force-recreate   # --force-recreate 必須
   ```
3. `/data` のファイル（alias.json / 名簿 / DB）は**イメージに入らない**ので、必要なら
   `sudo docker cp <file> renrakucho:/data/` で更新。
4. `watch_folder.py` は **Windows用とコンテナ用で中身が違う**（コンテナ版は `/app` 絶対パス）。
   `C:\test` 版をそのまま push しないこと。
