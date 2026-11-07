#!/usr/bin/env python3
"""おたより工房（ローカル版）のサーバ。

静的ファイルを配りながら、Claude API への問い合わせを中継する。
APIキーはこのプロセスだけが持ち、ブラウザには一切渡さない。

    python server.py            # http://127.0.0.1:8787
    python server.py --port 9000

認証は Anthropic SDK の解決順にまかせる（ANTHROPIC_API_KEY、ANTHROPIC_AUTH_TOKEN、
`ant auth login` のプロファイルの順）。環境変数が無くてもプロファイルがあれば動く。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import threading
import time
import traceback
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

# Windows のコンソールは cp932 のことがある。出せない文字で落とさない。
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(errors="replace")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"
PROMPTS = ROOT / "prompts"
DATA = ROOT / "data"

# 画面のモデル選択に出す候補。先頭が既定。
MODELS = [
    {"id": "claude-opus-5-5", "label": "Opus 5.5（いちばん賢い・既定）"},
    {"id": "claude-sonnet-5-5", "label": "Sonnet 5.5（速くて安い）"},
    {"id": "claude-haiku-5-5", "label": "Haiku 5.5（いちばん速い）"},
    {"id": "claude-fable-5-1", "label": "Fable 5.1（最上位・高価）"},
]
DEFAULT_MODEL = MODELS[0]["id"]
EFFORTS = ["low", "medium", "high", "xhigh", "max"]

# Fable 5.1 は thinking が常時オンで、明示指定すると 400 になる。
NO_THINKING_PARAM = {"claude-fable-5-1", "claude-mythos-5-1"}

_client = None
_client_lock = threading.Lock()


def get_client():
    """Anthropic クライアントを遅延生成する。資格情報が無ければ RuntimeError。"""
    global _client
    with _client_lock:
        if _client is None:
            try:
                import anthropic
            except ImportError as exc:  # pragma: no cover
                raise RuntimeError(
                    "anthropic パッケージが入っていません。"
                    "`pip install anthropic` を実行してください。"
                ) from exc
            try:
                _client = anthropic.Anthropic()
            except Exception as exc:
                raise RuntimeError(
                    "Anthropic の資格情報が見つかりません。"
                    "ANTHROPIC_API_KEY を設定するか `ant auth login` を実行してください。"
                ) from exc
        return _client


def read_prompt(name: str) -> str:
    """prompts/<name>.txt を毎回読み直す。編集したら次のリクエストから効く。"""
    path = PROMPTS / f"{name}.txt"
    if not path.exists():
        raise RuntimeError(f"プロンプトが見つかりません: {path}")
    return path.read_text(encoding="utf-8")


def fill(template: str, values: dict) -> str:
    """<<KEY>> を置き換える。JSON の波括弧と衝突しないようにこの形にしてある。"""
    out = template
    for key, value in values.items():
        out = out.replace(f"<<{key}>>", str(value))
    return out


def ask(
    messages,
    *,
    model: str,
    effort: str = "high",
    max_tokens: int = 16000,
    system: str | None = None,
) -> str:
    """Claude に投げて本文テキストを返す。長い出力でも落ちないよう streaming を使う。"""
    client = get_client()
    kwargs = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": messages,
        "output_config": {"effort": effort},
    }
    if system:
        kwargs["system"] = system
    if model not in NO_THINKING_PARAM:
        kwargs["thinking"] = {"type": "adaptive"}

    with client.messages.stream(**kwargs) as stream:
        message = stream.get_final_message()

    if message.stop_reason == "refusal":
        detail = getattr(message, "stop_details", None)
        category = getattr(detail, "category", None) if detail else None
        raise RuntimeError(f"この内容には答えられませんでした（{category or 'refusal'}）。")

    text = "".join(b.text for b in message.content if b.type == "text")
    if not text.strip():
        raise RuntimeError("返事が空でした。もう一度お試しください。")
    return text


_FENCE = re.compile(r"```(?:json)?\s*(.+?)\s*```", re.S)


def parse_json(text: str):
    """返事から JSON を取り出す。素のJSON、コードフェンス、前後に一言ある形に耐える。"""
    candidates = [text.strip()]
    fence = _FENCE.search(text)
    if fence:
        candidates.append(fence.group(1).strip())
    for opener, closer in (("{", "}"), ("[", "]")):
        start, end = text.find(opener), text.rfind(closer)
        if start != -1 and end > start:
            candidates.append(text[start : end + 1])
    for candidate in candidates:
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue
    raise RuntimeError("返事の形がくずれていて読み取れませんでした。もう一度お試しください。")


def ask_json(messages, **kwargs):
    return parse_json(ask(messages, **kwargs))


def pick_model(payload: dict) -> str:
    model = payload.get("model") or DEFAULT_MODEL
    return model if any(m["id"] == model for m in MODELS) else DEFAULT_MODEL


def pick_effort(payload: dict, fallback: str = "high") -> str:
    effort = payload.get("effort") or fallback
    return effort if effort in EFFORTS else fallback


# ---------------------------------------------------------------- エンドポイント

def api_config(_payload):
    """画面の接続表示のため。鍵の中身は読まず、あるか無いかだけを見る。"""
    ready, has_key, message = False, False, ""
    try:
        client = get_client()
        ready = True
        has_key = bool(getattr(client, "api_key", None) or getattr(client, "auth_token", None))
        if not has_key:
            message = ("ANTHROPIC_API_KEY は見つかりませんでした。"
                       "`ant auth login` のプロファイルがあればこのまま動きます。"
                       "最初の生成で失敗するなら、キーを設定して開き直してください。")
    except RuntimeError as exc:
        message = str(exc)
    return {
        "models": MODELS,
        "defaultModel": DEFAULT_MODEL,
        "efforts": EFFORTS,
        "ready": ready,
        "hasKey": has_key,
        "message": message,
        "saved": sorted(p.stem for p in DATA.glob("*.json")),
        "form": {"configured": bool(form_url()), "url": mask_url(form_url())},
    }


def api_chat(payload):
    turns = payload.get("turns") or []
    cleaned = [
        {"role": "assistant" if t.get("role") == "assistant" else "user",
         "content": str(t.get("content") or "")}
        for t in turns if str(t.get("content") or "").strip()
    ]
    if not cleaned or cleaned[-1]["role"] != "user":
        raise RuntimeError("先生からの発言が必要です。")
    messages = [{"role": "user", "content": read_prompt("chat")}] + cleaned[-12:]
    data = ask_json(
        messages,
        model=pick_model(payload),
        effort=pick_effort(payload, "low"),
        max_tokens=1500,
    )
    return {
        "status": "ready" if data.get("status") == "ready" else "ask",
        "message": str(data.get("message") or ""),
        "chips": [str(c) for c in (data.get("chips") or [])][:4],
    }


def api_compose(payload):
    brief = str(payload.get("brief") or "").strip()
    if not brief:
        raise RuntimeError("どんなおたよりにしたいか、一言でも教えてください。")
    prompt = fill(read_prompt("compose"), {
        "BRIEF": brief,
        "ILLUSTRATIONS": payload.get("illustrations") or "",
        "EXTRA": str(payload.get("extra") or ""),
    })
    return ask_json(
        [{"role": "user", "content": prompt}],
        model=pick_model(payload),
        effort=pick_effort(payload),
        max_tokens=24000,
    )


def api_revise(payload):
    instruction = str(payload.get("instruction") or "").strip()
    if not instruction:
        raise RuntimeError("直してほしいことを書いてください。")
    doc = payload.get("doc")
    if not isinstance(doc, dict):
        raise RuntimeError("いまの原稿が送られてきませんでした。")
    prompt = fill(read_prompt("revise"), {
        "DOC": json.dumps(doc, ensure_ascii=False),
        "INSTRUCTION": instruction,
        "ILLUSTRATIONS": payload.get("illustrations") or "",
    })
    return ask_json(
        [{"role": "user", "content": prompt}],
        model=pick_model(payload),
        effort=pick_effort(payload),
        max_tokens=24000,
    )


def api_comment(payload):
    memo = str(payload.get("memo") or "").strip()
    if not memo:
        raise RuntimeError("子どもの様子をメモで入れてください。")
    prompt = fill(read_prompt("comment"), {
        "CALLED": str(payload.get("called") or "名前は使わない"),
        "MEMO": memo,
        "TONE": str(payload.get("tone") or "あたたかい"),
        "LENGTH": str(payload.get("length") or "100"),
        "COUNT": str(payload.get("count") or "3"),
    })
    data = ask_json(
        [{"role": "user", "content": prompt}],
        model=pick_model(payload),
        effort=pick_effort(payload, "medium"),
        max_tokens=4000,
    )
    drafts = data.get("drafts") if isinstance(data, dict) else data
    return {"drafts": [str(d) for d in (drafts or []) if str(d).strip()]}


def api_save(payload):
    name = re.sub(r'[\\/:*?"<>|]', "", str(payload.get("name") or "")).strip()
    if not name:
        raise RuntimeError("保存する名前を入れてください。")
    doc = payload.get("doc")
    if not isinstance(doc, dict):
        raise RuntimeError("保存する原稿がありません。")
    DATA.mkdir(exist_ok=True)
    (DATA / f"{name}.json").write_text(
        json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    return {"saved": name, "list": sorted(p.stem for p in DATA.glob("*.json"))}


def api_load(payload):
    name = re.sub(r'[\\/:*?"<>|]', "", str(payload.get("name") or "")).strip()
    path = DATA / f"{name}.json"
    if not name or not path.exists():
        raise RuntimeError("その名前の控えが見つかりません。")
    return {"doc": json.loads(path.read_text(encoding="utf-8"))}


# ---------------------------------------------------------------- Googleフォーム連携
#
# 取り込み先は2通り。どちらも「区分ごとの最新1件」にまとめて画面へ返す。
#   - apps_script/Code.gs をフォームに置いて出した JSON（おすすめ）
#   - 回答スプレッドシートを「ウェブに公開」した CSV

FORM_CONFIG = ROOT / "form_source.json"
FORM_HOSTS = ("script.google.com", "script.googleusercontent.com", "docs.google.com")
_LABEL_SUFFIX = re.compile(r"[（(][^（）()]*[)）]\s*$")
_SHEET_TIME = re.compile(r"^(\d{4})[/-](\d{1,2})[/-](\d{1,2})[ T](\d{1,2}):(\d{2})(?::(\d{2}))?")


def form_url() -> str:
    if FORM_CONFIG.exists():
        try:
            return str(json.loads(FORM_CONFIG.read_text(encoding="utf-8")).get("url") or "")
        except Exception:
            return ""
    return ""


def mask_url(url: str) -> str:
    """画面に出すとき key= の中身は伏せる。"""
    return re.sub(r"(key=)[^&]+", r"\1••••", url)


def short_label(title: str) -> str:
    """「本文（保健から）」→「本文」、「ねらい（ひよこ）」→「ねらい」。"""
    return _LABEL_SUFFIX.sub("", title).strip() or title.strip()


def sheet_time(value: str) -> str:
    """「2026/11/8 9:05:03」→「2026-11-08T09:05:03」。読めなければそのまま。"""
    m = _SHEET_TIME.match(value.strip())
    if not m:
        return value.strip()
    y, mo, d, h, mi, s = m.groups()
    return f"{y}-{int(mo):02d}-{int(d):02d}T{int(h):02d}:{mi}:{int(s or 0):02d}"


def latest_by_kubun(rows):
    """rows: [(time, {設問タイトル: 回答})] → {区分: {time, fields}}。新しい方が勝つ。"""
    out = {}
    for time, answers in rows:
        kubun = str(answers.get("区分") or "").strip()
        if not kubun:
            continue
        fields = {}
        for title, value in answers.items():
            text = str(value or "").replace("\r\n", "\n").replace("\r", "\n").strip()
            if title == "区分" or not text:
                continue
            fields[short_label(title)] = text
        if kubun not in out or time > out[kubun]["time"]:
            out[kubun] = {"time": time, "fields": fields}
    return out


def parse_form_payload(body: bytes, content_type: str):
    text = body.decode("utf-8-sig", errors="replace")
    head = text.lstrip()[:200].lower()
    if "html" in content_type.lower() or head.startswith("<!doctype") or head.startswith("<html"):
        raise RuntimeError(
            "ログイン画面が返ってきました。Apps Script のデプロイで"
            "「アクセスできるユーザー」を「全員」にしてください。"
        )
    if head.startswith("{"):
        data = json.loads(text)
        if not data.get("ok"):
            raise RuntimeError(f"フォーム側のエラー: {data.get('error') or '不明'}")
        rows = [(str(r.get("time") or ""), r.get("answers") or {}) for r in data.get("responses") or []]
        return {"form": data.get("form") or "", "sections": latest_by_kubun(rows)}

    import csv
    import io
    reader = csv.reader(io.StringIO(text))
    header = next(reader, None)
    if not header or "区分" not in header:
        raise RuntimeError("CSV に「区分」の列が見つかりません。回答シートを公開したURLか確かめてください。")
    rows = []
    for record in reader:
        answers = {header[i]: record[i] for i in range(min(len(header), len(record)))}
        stamp = answers.pop("タイムスタンプ", None) or answers.pop("Timestamp", "") or ""
        rows.append((sheet_time(stamp), answers))
    return {"form": "", "sections": latest_by_kubun(rows)}


def api_form_config(payload):
    url = str(payload.get("url") or "").strip()
    if url:
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.hostname not in FORM_HOSTS:
            raise RuntimeError("Google の Apps Script か、公開したスプレッドシートの https の URL を入れてください。")
    FORM_CONFIG.write_text(json.dumps({"url": url}, ensure_ascii=False), encoding="utf-8")
    return {"configured": bool(url), "url": mask_url(url)}


def api_form_fetch(_payload):
    import urllib.error
    import urllib.request
    url = form_url()
    if not url:
        raise RuntimeError("まだ取り込み先の URL が設定されていません。")
    request = urllib.request.Request(url, headers={"User-Agent": "otayori-kobo/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=25) as res:
            body = res.read(8 * 1024 * 1024)
            content_type = res.headers.get("Content-Type", "")
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"フォームの取り込みに失敗しました（HTTP {exc.code}）。URL を確かめてください。") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"フォームにつながりませんでした（{exc.reason}）。") from exc
    data = parse_form_payload(body, content_type)
    data["fetchedAt"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    return data


ROUTES = {
    "/api/config": api_config,
    "/api/form/config": api_form_config,
    "/api/form/fetch": api_form_fetch,
    "/api/chat": api_chat,
    "/api/compose": api_compose,
    "/api/revise": api_revise,
    "/api/comment": api_comment,
    "/api/save": api_save,
    "/api/load": api_load,
}

CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".ico": "image/x-icon",
}


class Handler(BaseHTTPRequestHandler):
    server_version = "otayori/1.0"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):  # 1行にまとめる
        sys.stderr.write("  %s\n" % (fmt % args))

    def _send(self, status, body: bytes, content_type: str):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status, obj):
        self._send(status, json.dumps(obj, ensure_ascii=False).encode("utf-8"),
                   "application/json; charset=utf-8")

    def do_GET(self):
        path = unquote(urlparse(self.path).path)
        if path in ("/", "/index.html"):
            path = "/static/index.html"
        if path == "/api/config":
            try:
                self._json(200, api_config({}))
            except Exception as exc:
                self._json(500, {"error": str(exc)})
            return
        if not path.startswith("/static/"):
            self._json(404, {"error": "not found"})
            return
        target = (STATIC / path[len("/static/"):]).resolve()
        if not str(target).startswith(str(STATIC.resolve())) or not target.is_file():
            self._json(404, {"error": "not found"})
            return
        self._send(200, target.read_bytes(),
                   CONTENT_TYPES.get(target.suffix, "application/octet-stream"))

    def do_POST(self):
        path = unquote(urlparse(self.path).path)
        handler = ROUTES.get(path)
        if handler is None:
            self._json(404, {"error": "not found"})
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
            payload = json.loads(self.rfile.read(length) or b"{}")
        except Exception:
            self._json(400, {"error": "送られてきた内容を読み取れませんでした。"})
            return
        try:
            self._json(200, handler(payload))
        except RuntimeError as exc:
            self._json(400, {"error": str(exc)})
        except Exception as exc:
            traceback.print_exc()
            self._json(500, {"error": f"{type(exc).__name__}: {exc}"})


def main():
    parser = argparse.ArgumentParser(description="おたより工房 ローカル版")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--no-open", action="store_true", help="ブラウザを開かない")
    args = parser.parse_args()

    DATA.mkdir(exist_ok=True)
    url = f"http://{args.host}:{args.port}/"

    try:
        get_client()
        print("Claude への接続: 準備できています")
    except RuntimeError as exc:
        print(f"Claude への接続: まだです。{exc}")

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"おたより工房 {url}  (止めるには Ctrl+C)")
    if not args.no_open:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n終了します。")
        server.shutdown()


if __name__ == "__main__":
    main()
