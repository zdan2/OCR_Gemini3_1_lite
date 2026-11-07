# TrueNAS の Dockge で動かして、Tailscale でつなぐ

おたより工房を TrueNAS の上で動かし、Tailscale を入れた端末（パソコン・スマホ・タブレット）からだけ開けるようにする。
LAN やインターネットにはポートを開けない。

```
[ 先生の端末 ] --Tailscale--> [ tailscale コンテナ ] --同じネットワーク--> [ おたより工房 :8787 ]
                                   （TrueNAS の Dockge スタック "otayori"）
```

使うファイルは `compose.yaml`・`Dockerfile`・`tailscale/serve.json`（このフォルダに入っている）。

## 1. Tailscale の準備（管理画面 https://login.tailscale.com/admin ）

1. **DNS** のページで MagicDNS がオンになっていることを確かめる（ふつうは最初からオン）。
2. （HTTPS で開きたいとき）同じ **DNS** のページで **HTTPS Certificates** を有効にする。
3. **Settings → Keys → Generate auth key** で鍵を作る。
   - Reusable はオフ、Ephemeral はオフのままでよい。
   - できた `tskey-auth-…` をコピーしておく（あとで1回だけ使う）。

## 2. ファイルを TrueNAS に置く

1. TrueNAS の **Apps → Dockge → Edit** で、**Stacks** のホストパスを確かめる
   （例：`/mnt/tank/apps/dockge/stacks`）。
2. その中に `otayori` というフォルダを作り、このフォルダの中身をまるごとコピーする
   （SMB の共有から入れるのがかんたん）。次は入れなくてよい。
   - `.venv`、`__pycache__`、`.claude`、`run.cmd`
3. 今まで Windows で作った控えや自作のイラストを使うなら、`data` フォルダもそのままコピーする。
   Windows で画面から設定したAPIキーを持っていくなら、`C:\otayori\.env` を `otayori/data/.env` に置く。

置いたあとはこうなる。

```
stacks/otayori/
  compose.yaml   Dockerfile   server.py   requirements.txt
  static/   prompts/   tailscale/serve.json   data/（あれば）
```

## 3. Dockge で起動する

1. Dockge を開く。一覧に `otayori` が出ていなければ、右上のメニューの **Scan Stacks Folder** を押す。
2. `otayori` を開いて **編集（Edit）**。下の **.env** の欄に次を書く。

   ```
   TS_AUTHKEY=tskey-auth-ここにコピーした鍵
   ```

   名前を変えたいときは `TS_HOSTNAME=hoikuen-otayori` のように足す（既定は `otayori`）。
3. **保存** して **起動（Deploy / Start）**。初回はイメージを作るので1〜2分かかる。

## 4. つないでみる

1. Tailscale の管理画面の **Machines** に `otayori` が出ていれば、つながっている。
2. Tailscale を入れてログインした端末のブラウザで開く。
   - `http://otayori:8787`
   - HTTPS を有効にしたなら `https://otayori.<tailnet名>.ts.net`（tailnet名は管理画面の DNS ページに出ている）。
     初めて開くときは証明書を取るので、数秒〜数十秒待つことがある。
3. 画面の「AIにつなぐ」で Anthropic のAPIキーを設定する。キーは `stacks/otayori/data/.env` に保存される。

## 5. つないだあとにしておくこと

- **鍵の期限を切る**：Machines の `otayori` の「…」から **Disable key expiry**。
  これをしないと、180日ほどで勝手にログアウトして開けなくなる。
- **auth key を消してよい**：一度つながればログイン状態は `tailscale/state` に残る。
  Dockge の .env から `TS_AUTHKEY` の行を消しても、作り直しても、そのままつながる。

## 更新のしかた

1. 新しい `server.py`・`static`・`prompts` などを `stacks/otayori/` に上書きコピーする
   （`data` と `tailscale` は上書きしない）。
2. Dockge で `otayori` を開いて **更新（Update）** を押す。イメージが作り直されて反映される
   （`compose.yaml` の `pull_policy: build` のおかげ。**再起動（Restart）** では作り直されない）。

`prompts/*.txt` を直したときも同じく **更新** を押す（コンテナの中にコピーして使っているため）。

## フォーム連携

「フォーム」タブの取り込み先（Apps Script の URL と鍵）は `data/form_source.json` に入るので、作り直しても残る。
取り込みは TrueNAS から `script.google.com` に出ていく。Tailscale の中だけで開いていても、TrueNAS が
インターネットに出られれば動く。フォーム側の準備は README の「フォーム連携」を見る。

## バックアップ

`stacks/otayori/data/` を残せばよい。中身は次のとおり。

| もの | 場所 |
|---|---|
| APIキー | `data/.env` |
| おたよりの控え | `data/*.json` |
| 自作のイラスト | `data/illust/` |
| フォーム連携の取り込み先（URL と鍵） | `data/form_source.json` |

`tailscale/state/` は Tailscale のログイン状態。消すと、もう一度 auth key で入れ直すことになる。

## auth key を使わずにつなぐ

`TS_AUTHKEY` を書かずに起動すると、tailscale コンテナのログにログイン用のリンクが出る。

```
To authenticate, visit:
	https://login.tailscale.com/a/xxxxxxxx
```

これを開いて、入れたい tailnet のアカウントで承認すればよい。待っているあいだ tailscale コンテナは
何度か起動し直し、そのたびにリンクが変わる。古いリンクは使えないので、いちばん新しいものを開く。

## tailscale コンテナが起動し直したとき

おたより工房は tailscale コンテナのネットワークを借りている。tailscale コンテナだけが起動し直すと、
おたより工房は古いネットワークに取り残されて、外から開けなくなる。
そのため `OTAYORI_WATCH_IFACE=tailscale0` で見張っていて、`tailscale0` が 90 秒消えたままなら
おたより工房が自分で終わり、起こし直されて新しいネットワークに入り直す（1〜2分で戻る）。

## うまくいかないとき

- **Machines には出ているのに開けない（接続を拒否される）**：上の見張りで1〜2分で直る。
  急ぐときは Dockge で `otayori` を **再起動** する。

- **Machines に出てこない**：Dockge で `tailscale` コンテナのログを見る。
  `invalid key` なら auth key が切れているか打ちまちがい。新しく作って .env に入れ直し、起動し直す。
- **`/dev/net/tun` のエラーで tailscale が起動しない**：`compose.yaml` で `TS_USERSPACE=false` を `true` にし、
  `devices:` の2行を消して起動し直す。少し遅くなるが同じように使える。
- **名前が `otayori-1` になった**：前に同じ名前の端末があった。Machines で古い方を消してから、
  `tailscale/state` を空にして入れ直す。
- **画面は出るが「つなぐ」や生成で失敗する**：Dockge で `otayori` コンテナのログを見る。
  TrueNAS から `api.anthropic.com` に出られるか（DNS やファイアウォール）も確かめる。

## 気をつけること

- tailnet に入っている人は誰でも開け、設定したAPIキーで生成できる（料金がかかる）。
  家族や同僚を tailnet に招くなら、Tailscale の ACL で `otayori` を開ける人をしぼる。
- コンテナは root で動くので、`data` の中のファイルは root の持ちものになる。
  SMB から消したり書きかえたりできないときは、TrueNAS の権限設定で直す。
