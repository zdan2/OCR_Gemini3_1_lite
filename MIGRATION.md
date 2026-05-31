# TrueNAS SCALE 移植手順（Dockge 経由）

連絡帳パイプラインを Windows PC から TrueNAS SCALE (24.10 Electric Eel 以降) の
Dockge スタックとして動かすための手順。

---

## 0. 全体構成

```
TrueNAS SCALE
├── データセット
│   ├── /mnt/main/renrakucho/scansnap  (rclone が Dropbox から同期、コンテナは ro 参照)
│   └── /mnt/main/renrakucho/data      (DB / 状態 / 設定 / レポート出力, rw)
│
├── App: rclone (既存の TrueNAS アプリでもよい)
│   └── Dropbox の ScanSnap フォルダ → /mnt/main/renrakucho/scansnap へ定期 pull
│
└── App: Dockge
    └── stack: renrakucho (このリポジトリの compose.yaml を使う)
```

---

## 1. TrueNAS 側の準備

### 1-1. データセット作成
TrueNAS UI から以下 2 つを作成（プール名は環境に合わせて読み替え）:

| データセット | 用途 | 権限 |
|---|---|---|
| `main/renrakucho/scansnap` | rclone 同期先 | 所有者: apps、書き込み可 |
| `main/renrakucho/data` | DB・設定・出力 | 所有者: apps、書き込み可 |

### 1-2. rclone で Dropbox 同期を設定
方法は何でも可（rclone アプリ / cron / TrueCommand 等）。要件は **1 つだけ**:

> Dropbox の ScanSnap フォルダの中身が `/mnt/main/renrakucho/scansnap` に
> 最新化されていること

5〜10 分間隔の pull で十分（watch_folder 側でも安定確認するため少々遅れても問題ない）。

### 1-3. 初期データの配置
SCP / SMB 等で元 PC から `/mnt/main/renrakucho/data/` 直下に以下をコピー:

| ファイル | 必須？ | 備考 |
|---|---|---|
| `alias.json` | 必須 | OCR 別名辞書。リポジトリ同梱版でも可 |
| `在園児各月児童名簿　令和8年度.xlsx` | 必須 | 名簿マッチング用 |
| `renrakucho.db` | 任意 | 既存 DB を引き継ぐ場合のみ |

---

## 2. Dockge スタックの登録

### 2-1. ソースの配置
SSH で TrueNAS に入り、Dockge の stacks ディレクトリ配下にプロジェクトを置く:

```bash
cd /mnt/tank/dockge/stacks   # 環境に合わせて読み替え
git clone <このリポジトリのURL> renrakucho
cd renrakucho
```

`compose.yaml` の名前で参照されることが多いので、必要ならリネーム:

```bash
mv docker-compose.yml compose.yaml
```

### 2-2. .env ファイルを作成
`/mnt/tank/dockge/stacks/renrakucho/.env`:

```env
GEMINI_API_KEY=AIza...
GMAIL_USER=hikarinomorirenraku@gmail.com
GMAIL_APP_PASSWORD=xxxxxxxxxxxxxxxx
RECIPIENTS=parent1@example.com,parent2@example.com
```

> Gmail アプリパスワードは Google アカウント → セキュリティ → 2 段階認証 →
> アプリ パスワード で発行（16 桁、スペース無し）。

### 2-3. Dockge UI でデプロイ
1. Dockge Web UI を開く
2. 左メニューから対象スタック (renrakucho) を選択
3. **「Deploy」** ボタンを押すと初回ビルド + 起動
4. **Logs** タブで `監視開始: /scansnap` が出ているか確認

---

## 3. 動作確認

### 3-1. ログの確認
Dockge UI または CLI:

```bash
docker logs -f renrakucho
```

期待される出力例:

```
2026-05-30 12:00:00 | 監視開始: /scansnap
2026-05-30 12:00:00 | 名簿: 在園児各月児童名簿　令和8年度.xlsx ／ 送信: ON ／ 間隔: 30s ／ モード: 常駐
2026-05-30 12:00:30 | [取り込み] 20260530どんぐり_家庭での生活.pdf (日付=2026-05-30)
2026-05-30 12:00:45 | [完了] 20260530どんぐり_家庭での生活.pdf
2026-05-30 12:00:45 |   [送信] 日次メール 2026-05-30
```

### 3-2. 出力ファイルの確認
TrueNAS シェルで:

```bash
ls -la /mnt/main/renrakucho/data/
# renrakucho.db, .watch_state.json, _reports/ が出来ているはず
```

### 3-3. 月次レポートの手動実行
```bash
docker exec renrakucho python /app/build_monthly_report.py --month 2026-05
```

---

## 4. 運用 Tips

### 4-1. 再処理したいとき
`.watch_state.json` から該当ファイルのエントリを削除すれば次回走査で再取り込みされる:

```bash
docker exec renrakucho python -c "
import json, pathlib
p = pathlib.Path('/data/.watch_state.json')
s = json.loads(p.read_text(encoding='utf-8'))
s.pop('20260530どんぐり_家庭での生活.pdf', None)
p.write_text(json.dumps(s, ensure_ascii=False, indent=1), encoding='utf-8')
"
```

### 4-2. メール送信を一時停止したい
`compose.yaml` の `command:` から `--send` を削除して **Update** で再デプロイ。
取り込み・DB 登録・レポート生成は続くが、メールだけ止まる。

### 4-3. コード更新の流れ
```bash
cd /mnt/tank/dockge/stacks/renrakucho
git pull
# Dockge UI で「Update」(ビルドキャッシュを使った再ビルド + 再起動)
```

### 4-4. DB バックアップ
`/data` データセットに ZFS スナップショットを定期取得する設定を TrueNAS で入れておく。
SQLite ファイル 1 個で完結するので ZFS スナップショットで十分。

---

## 5. トラブルシュート

| 症状 | 確認ポイント |
|---|---|
| ログに「名簿xlsxが見つかりません」 | `/mnt/main/renrakucho/data/` 直下に `*名簿*.xlsx` があるか |
| ログに「GEMINI_API_KEY を設定してください」 | `.env` の値が空でないか、Dockge で **Update** したか |
| 取り込みは走るがメールが飛ばない | `GMAIL_APP_PASSWORD` がアプリパスワード（16 桁）か、2 段階認証が有効か |
| PDF を置いても無反応 | ファイル名先頭 8 桁が `YYYYMMDD` で、かつ「家庭での生活」と「きいちご」「どんぐり」を含むか |
| `[保留] 同期中の可能性` が続く | rclone がまだ書き込み中。次回走査で安定するまで待つ |
| 名簿マッチングがおかしい | `/data/alias.json` を編集して別名追加。コンテナ再起動不要（次回 PDF から反映） |
