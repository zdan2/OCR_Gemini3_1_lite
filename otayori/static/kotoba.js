/* おたより工房 — 「④ ことば」タブ

   紙面の文章を1つ選んで、AIに整えた案を出してもらい、選んだ案で置きかえる。
   やること：字数に収める／誤字・脱字の確認／やさしい言い回しに／自由に指示。
   紙の上の文章をクリックすると、その文章がここで選ばれる。 */

(function () {
"use strict";

var A = window.OtayoriApp;
var O = window.Otayori;
var esc = O.esc;
var $ = function (id){ return document.getElementById(id); };

var EMPTY = "（まだ提出されていません）";
var KIND_NAMES = {text: "本文", lead: "あいさつ", note: "編集後記", list: "箇条書き", banner: "帯",
                  section: "記事", comments: "こどもたちのすがた"};
var mode = "shorten";
var list = [];          // 選べる文章 [{path, label, name, src, part, lines, page}]
var current = null;     // いま選んでいる文章
var busy = false;

function chars(s){ return String(s || "").replace(/\s/g, "").length; }

function limitOf(t){
  var F = window.OtayoriForm;
  return (F && F.limitFor) ? F.limitFor(t.src, t.part) : null;
}

/** 紙面から、整えられる文章を集める。 */
function collect(){
  var doc = A.getDoc(), out = [];
  if (!doc) return out;
  (doc.pages || []).forEach(function (pg, pi){
    function scan(blocks, base){
      (blocks || []).forEach(function (b, i){
        if (!b) return;
        var p = base + "." + i;
        var name = b.heading || b.src || KIND_NAMES[b.kind] || b.kind;
        function add(path, label, extra){
          out.push(Object.assign({path: path, name: label, src: b.src || "", page: pi + 1}, extra || {}));
        }
        if (b.kind === "text" || b.kind === "lead" || b.kind === "note") add(p + ".body", name);
        else if (b.kind === "banner") add(p + ".text", name);
        else if (b.kind === "list") add(p + ".items", name, {lines: true});
        else if (b.kind === "section"){
          (b.parts || []).forEach(function (pt, q){
            if (pt) add(p + ".parts." + q + ".v", name + "・" + pt.k, {part: pt.k});
          });
        } else if (b.kind === "comments"){
          (b.items || []).forEach(function (it, q){
            if (it) add(p + ".items." + q + ".text", name + "・" + (it.name || ""));
          });
        }
      });
    }
    scan(pg.top, "pages." + pi + ".top");
    (pg.columns || []).forEach(function (c, ci){ scan(c.blocks, "pages." + pi + ".columns." + ci + ".blocks"); });
    scan(pg.bottom, "pages." + pi + ".bottom");
  });
  return out.filter(function (t){
    var v = textOf(t);
    return v.trim() && v.trim() !== EMPTY;
  });
}

function textOf(t){
  var v = O.getPath(A.getDoc(), t.path);
  return t.lines ? (Array.isArray(v) ? v.join("\n") : "") : String(v == null ? "" : v);
}
function writeBack(t, text){
  O.setPath(A.getDoc(), t.path, t.lines
    ? text.split("\n").map(function (l){ return l.replace(/^[・●○◎\-－*＊]\s*/, "").trim(); }).filter(Boolean)
    : text);
}

/** 選べる文章の一覧を作り直す。字数オーバーを先に並べる。 */
function refresh(keepPath){
  list = collect();
  list.forEach(function (t){
    t.n = chars(textOf(t));
    t.limit = limitOf(t);
    t.over = t.limit ? t.n - t.limit : 0;
  });
  list.sort(function (a, b){ return (b.over > 0) - (a.over > 0) || a.page - b.page; });
  var sel = $("k-target");
  if (!list.length){
    sel.innerHTML = '<option value="">（整えられる文章がありません）</option>';
    current = null; showCurrent(); return;
  }
  sel.innerHTML = list.map(function (t, i){
    var tag = t.limit ? "　" + t.n + "／" + t.limit + "字" + (t.over > 0 ? "　" + t.over + "字オーバー" : "")
                      : "　" + t.n + "字";
    return '<option value="' + i + '">' + (t.over > 0 ? "▲ " : "") + t.page + "ページ　" + esc(t.name) + tag + "</option>";
  }).join("");
  var want = keepPath || (current && current.path);
  var idx = 0;
  for (var i = 0; i < list.length; i++) if (list[i].path === want){ idx = i; break; }
  sel.value = String(idx);
  current = list[idx];
  showCurrent();
}

function showCurrent(){
  if (!current){ $("k-orig").textContent = ""; $("k-meta").textContent = ""; return; }
  var text = textOf(current);
  $("k-orig").textContent = text;
  $("k-meta").textContent = "いまの文章　" + chars(text) + "字" +
    (current.limit ? "（上限 " + current.limit + "字）" : "") +
    (current.src ? "　フォーム：" + current.src : "");
  if (!$("k-len").dataset.touched){
    var n = chars(text);
    $("k-len").value = current.limit && n > current.limit ? current.limit : Math.max(20, Math.round(n * 0.8));
  }
}

function setMode(m){
  mode = m;
  Array.prototype.forEach.call($("k-modes").querySelectorAll("button"), function (b){
    b.setAttribute("aria-pressed", b.getAttribute("data-m") === m ? "true" : "false");
  });
  $("k-len-row").hidden = m !== "shorten";
  $("k-free-row").hidden = m !== "free";
}

/* ---------------- 案 ---------------- */

function renderDrafts(drafts, changes, orig){
  var box = $("k-drafts");
  box.innerHTML = "";
  if (mode === "proof"){
    var head = document.createElement("div");
    head.className = "note";
    if (!changes.length){
      head.textContent = "直すところは見つかりませんでした。";
      box.appendChild(head);
      return;
    }
    head.innerHTML = "直したところ（" + changes.length + "か所）";
    var ul = document.createElement("ul");
    ul.className = "chg";
    ul.innerHTML = changes.map(function (c){
      return "<li><del>" + esc(c.before) + "</del> → <ins>" + esc(c.after) + "</ins>" +
             (c.why ? '　<span class="hint">' + esc(c.why) + "</span>" : "") + "</li>";
    }).join("");
    head.appendChild(ul);
    box.appendChild(head);
  }
  drafts.forEach(function (text, i){
    var n = chars(text), lim = current && current.limit;
    var meta = "案 " + (i + 1) + "・" + n + "字";
    var warn = "";
    if (mode === "shorten"){
      var goal = parseInt($("k-len").value, 10);
      if (goal && n > goal) warn = "　目標より " + (n - goal) + "字多い";
    }
    if (lim && n > lim) warn += "　上限より " + (n - lim) + "字多い";
    if (text === orig) meta += "（元のまま）";
    var d = document.createElement("div");
    d.className = "draft";
    d.innerHTML = '<div class="tx"></div><div class="bar"><span class="n">' + esc(meta) +
      (warn ? '<span class="warn">' + esc(warn) + "</span>" : "") + "</span>" +
      '<span style="display:flex;gap:6px"><button class="btn sm" type="button" data-copy>コピー</button>' +
      '<button class="btn sm primary" type="button" data-use>置きかえる</button></span></div>';
    d.querySelector(".tx").textContent = text;
    d.querySelector("[data-use]").addEventListener("click", function (){ use(text); });
    d.querySelector("[data-copy]").addEventListener("click", function (){
      var btn = this;
      navigator.clipboard.writeText(text).then(
        function (){ btn.textContent = "コピーしました"; setTimeout(function (){ btn.textContent = "コピー"; }, 1600); },
        function (){ A.toast("コピーできませんでした。"); });
    });
    box.appendChild(d);
  });
}

function use(text){
  if (!current) return;
  var path = current.path;
  A.pushHistory();
  writeBack(current, text);
  A.commit();
  refresh(path);
  $("k-drafts").innerHTML = "";
  A.toast("置きかえました。「ひとつ戻す」で前の文章にもどせます。");
}

async function go(){
  if (busy || !current) return;
  var orig = textOf(current);
  var payload = {
    text: orig, mode: mode,
    where: current.page + "ページ「" + current.name + "」" + (current.limit ? "（上限 " + current.limit + "字）" : ""),
    model: $("model").value, effort: $("effort").value
  };
  if (mode === "shorten") payload.length = $("k-len").value;
  if (mode === "free") payload.instruction = $("k-free").value;
  busy = true;
  $("k-go").disabled = true;
  $("k-drafts").innerHTML = '<div class="note"><span class="thinking"><span class="dot"></span><span class="dot"></span>' +
                            '<span class="dot"></span>考えています</span></div>';
  try {
    var r = await A.api("/api/kotoba", payload);
    renderDrafts(r.drafts || [], r.changes || [], orig);
  } catch (e){
    $("k-drafts").innerHTML = "";
    A.toast(e.message);
  } finally {
    busy = false;
    $("k-go").disabled = false;
  }
}

/* ---------------- 画面 ---------------- */

$("k-target").addEventListener("change", function (){
  current = list[+this.value] || null;
  delete $("k-len").dataset.touched;
  $("k-drafts").innerHTML = "";
  showCurrent();
});
$("k-len").addEventListener("input", function (){ this.dataset.touched = "1"; });
$("k-modes").addEventListener("click", function (e){
  var b = e.target.closest("button[data-m]");
  if (b){ setMode(b.getAttribute("data-m")); $("k-drafts").innerHTML = ""; }
});
$("k-go").addEventListener("click", go);
$("t-comment").addEventListener("click", function (){ refresh(); });

/* 紙の上の文章をクリックしたら、その文章を選ぶ（箇条書きは1行ではなくブロックごと） */
$("scaler").addEventListener("focusin", function (e){
  var el = e.target.closest && e.target.closest("[data-path]");
  if (!el) return;
  var p = el.getAttribute("data-path");
  var hit = null;
  collect().forEach(function (t){ if (p === t.path || p.indexOf(t.path + ".") === 0) hit = t.path; });
  if (!hit) return;
  if (!$("p-comment").hidden){
    delete $("k-len").dataset.touched;
    refresh(hit);
    $("k-drafts").innerHTML = "";
  } else {
    current = {path: hit};
  }
});

setMode("shorten");

})();
