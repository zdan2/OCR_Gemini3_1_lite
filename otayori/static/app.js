/* おたより工房 ローカル版 — 画面の組み立てとサーバとのやりとり */
(function () {
"use strict";

var O = window.Otayori;
var PAGE_W = O.PAGE_W, PAGE_H = O.PAGE_H;
var LS_KEY = "otayori-local.v1";

var doc = null, history = [], drafts = [], config = null;
var busy = false, zoom = null, pageView = "both", turns = [];
var pickerPath = null, blockAddPath = null;

var $ = function (id){ return document.getElementById(id); };
var esc = O.esc, getPath = O.getPath, setPath = O.setPath;
function clone(o){ return JSON.parse(JSON.stringify(o)); }

/* ---------------- サーバ ---------------- */
async function api(path, payload){
  var res = await fetch(path, {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify(payload || {})
  });
  if (res.status === 404){
    throw new Error("サーバが古いままです。黒い画面で Ctrl+C を押して止め、run.cmd で起動し直してから、このページを再読み込みしてください。");
  }
  var data;
  try { data = await res.json(); }
  catch (e) { throw new Error("サーバからの返事を読み取れませんでした。"); }
  if (!res.ok || data.error) throw new Error(data.error || ("エラー " + res.status));
  return data;
}
function illListForPrompt(){
  return ILL_KEYS.map(function (k){ return k + "(" + ILL[k][1] + ")"; }).join("、");
}

/* ---------------- 下ごしらえ ---------------- */
function pickSeason(name){
  var pool = (SEASON_SETS[name] || SEASON_SETS.mix).filter(function (k){ return ILL[k]; });
  return pool.length ? pool : SEASON_SETS.mix.slice();
}
function someIlls(n, season){
  var pool = pickSeason(season), bag = pool.slice(), out = [];
  for (var i = 0; i < n; i++){
    if (!bag.length) bag = pool.slice();
    out.push(bag.splice(Math.floor(Math.random() * bag.length), 1)[0]);
  }
  return out;
}
function emptyPage(season){
  return {deco: {corners: someIlls(4, season), edge: someIlls(10, season)}, top: [], columns: [], bottom: []};
}

function starterDoc(){
  function B(kind, patch){
    var b = O.blockProto(kind);
    for (var k in patch) if (Object.prototype.hasOwnProperty.call(patch, k)) b[k] = patch[k];
    return b;
  }
  var d = {
    meta: {school: "みどりの森保育園", className: "ひまわり組", issue: "2026年5月号",
           dateText: "2026年5月1日発行", teacher: "担任　佐野・池田"},
    theme: {palette: "wakaba", titleFont: "pop", headingFont: "maru", pattern: "dots", level: "mori"},
    pages: [emptyPage("haru"), emptyPage("haru")]
  };
  d.pages[0].top = [B("title", {title: "ひまわり組だより", sub: "だんごむしを探す手つきが、ずいぶん慎重になってきました。",
                               ill: "koinobori", illR: "himawari"}),
                    B("lead", {ill: "kodomo", heading: "ごあいさつ",
                               body: "進級から一か月がたちました。朝の支度を自分でやりきる子が増え、靴の左右を見比べてから履く姿も見られます。五月は園庭や散歩先へ出て、体をたくさん動かして過ごしたいと思います。"})];
  d.pages[0].columns = [
    {w: 2.0, blocks: [B("text", {ill: "tentou", heading: "園庭がいちばんの先生",
      body: "園庭に出ると、まず花壇のわきに集まります。土の表面をそっとめくってだんごむしを探すのですが、強く掘ると逃げてしまうことに気づいた子から、指先の力の加減が広がっていきました。見つけた子が「いた」と小さな声で言うと、まわりの子も声をひそめます。"})]},
    {w: 2.0, blocks: [B("text", {ill: "bus", heading: "遠足に行ってきます",
      body: "十五日は緑ヶ丘公園へ遠足に出かけます。当日はクラスごとに手をつないで歩きますので、歩きやすい靴でお願いします。お弁当は、ふたを自分で開けられる入れ物だと安心です。雨の場合は二十二日に延期します。"}),
                      B("quiz", {ill: "hoshi", heading: "こんげつのなぞなぞ", q: "はるになるとせなかにはっぱをのせてあるく虫、なあに。", a: "だんごむし。はっぱをたべます。"})]},
    {w: 1.45, blocks: [B("schedule", {ill: "hoshi", heading: "五月の予定", items: [
      {date: "5/1", label: "こどもの日の会"}, {date: "5/7", label: "身体測定"},
      {date: "5/11", label: "避難訓練"}, {date: "5/15", label: "遠足（緑ヶ丘公園）"},
      {date: "5/18", label: "誕生会"}, {date: "5/21", label: "歯科健診"},
      {date: "5/26", label: "保育参観"}, {date: "5/29", label: "お弁当の日"}]})]}
  ];
  d.pages[0].bottom = [B("illband", {items: someIlls(7, "haru")})];

  d.pages[1].top = [B("head", {ill: "ehon", ill2: "hana", text: "ひまわり組のおしらせ"})];
  d.pages[1].columns = [
    {w: 1.0, blocks: [
      B("list", {ill: "ashiato", heading: "おねがい", items: [
        "日ざしが強くなりました。帽子を毎日持たせてください。名前の記入もお願いします。",
        "着替えが増える時季です。半袖と長袖を一組ずつ、袋に入れて置いておいてください。",
        "遠足は十五日です。前日までに、歩きやすい靴とお弁当の入れ物をご用意ください。"]}),
      B("pair", {ill: "onpu", heading: "今月のうた・えほん", items: [
        {k: "うた", v: "こいのぼり／ちゃつぼ"}, {k: "えほん", v: "そらまめくんのベッド（なかやみわ）"}]}),
      B("chips", {ill: "cake", heading: "おたんじょうびおめでとう", items: [
        {name: "あおい", note: "5/3"}, {name: "そうた", note: "5/9"},
        {name: "みのり", note: "5/17"}, {name: "けんと", note: "5/28"}]})]},
    {w: 2.1, blocks: [
      B("comments", {ill: "sakura", heading: "こどもたちのすがた", cols: 3, items: [
        {ill: "bus", name: "ゆいちゃん", text: "ブロックで長い電車をつくり、机のふちまで線路をのばしていました。あとから来た年下の子に「どうぞ」と連結器をひとつ分けてあげる姿がありました。"},
        {ill: "tentou", name: "はるとくん", text: "だんごむしを見つけるのが得意です。見つけると必ず近くの友だちを呼び、手のひらにそっとのせて見せてくれます。"},
        {ill: "onigiri", name: "さくらちゃん", text: "給食のにんじんを、小さく切ってもらってから口に運びました。食べ終えたあと、自分でおかわりの列に並びにいきました。"}]})]}
  ];
  d.pages[1].bottom = [B("note", {ill: "kuma", heading: "編集後記",
    body: "保育室の窓から、こいのぼりが見えるところに飾りました。風が吹くと子どもたちが一斉に窓を見ます。五月も元気に過ごせるよう、体調の変化は遠慮なくお知らせください。"})];
  return d;
}

function normalize(d){
  if (!d || typeof d !== "object") return starterDoc();
  d.meta = Object.assign({school: "", className: "", issue: "", dateText: "", teacher: ""}, d.meta || {});
  d.theme = Object.assign({palette: "wakaba", titleFont: "pop", headingFont: "maru", pattern: "dots", level: "mori"}, d.theme || {});
  if (!PALETTES[d.theme.palette]) d.theme.palette = "wakaba";
  if (!FONTS[d.theme.titleFont]) d.theme.titleFont = "pop";
  if (!FONTS[d.theme.headingFont]) d.theme.headingFont = "maru";
  if (["futsu", "mori", "max"].indexOf(d.theme.level) < 0) d.theme.level = "mori";
  if (!Array.isArray(d.pages) || !d.pages.length) d.pages = [emptyPage("mix"), emptyPage("mix")];
  while (d.pages.length < 2) d.pages.push(emptyPage("mix"));
  d.pages = d.pages.slice(0, 4);
  d.pages.forEach(function (pg){
    pg.deco = pg.deco || {};
    if (!Array.isArray(pg.deco.corners) || pg.deco.corners.length < 4) pg.deco.corners = someIlls(4, "mix");
    if (!Array.isArray(pg.deco.edge) || pg.deco.edge.length < 10) pg.deco.edge = someIlls(10, "mix");
    pg.deco.corners = pg.deco.corners.slice(0, 4).map(function (k){ return ILL[k] || /^u_/.test(k) ? k : "hana"; });
    pg.deco.edge = pg.deco.edge.slice(0, 10).map(function (k){ return ILL[k] || /^u_/.test(k) ? k : "hoshi"; });
    ["top", "bottom"].forEach(function (s){ if (!Array.isArray(pg[s])) pg[s] = []; });
    if (!Array.isArray(pg.columns)) pg.columns = [];
    if (pg.footer != null && typeof pg.footer !== "string") delete pg.footer;
    /* 自作の絵のキー（u_…）は一覧を読みこむ前でも残す。描くときに無ければ飛ばす */
    if (Array.isArray(pg.stickers)){
      pg.stickers = pg.stickers.filter(function (t){ return t && typeof t.k === "string"; }).map(function (t){
        function n(v, d){ v = parseFloat(v); return isFinite(v) ? v : d; }
        return {k: t.k, x: n(t.x, PAGE_W / 2), y: n(t.y, PAGE_H / 2), s: Math.min(420, Math.max(24, n(t.s, 90))), r: n(t.r, 0)};
      });
    } else delete pg.stickers;
    pg.columns = pg.columns.slice(0, 4).map(function (c){
      var w = parseFloat(c && c.w);
      return {w: isFinite(w) && w > 0 ? Math.min(4, Math.max(0.5, w)) : 1,
              blocks: Array.isArray(c && c.blocks) ? c.blocks.filter(Boolean) : []};
    });
  });
  return d;
}

/* ---------------- 保存 ---------------- */
var saveTimer = null;
var quotaWarned = false;
function saveLocal(){
  try { localStorage.setItem(LS_KEY, JSON.stringify({doc: doc, turns: turns})); }
  catch (e){
    if (!quotaWarned){
      quotaWarned = true;
      toast("写真が多くて、ブラウザへの自動保存ができませんでした。「⑤ ほぞん」タブで保存しておいてください。");
    }
  }
}
function loadLocal(){
  try {
    var raw = localStorage.getItem(LS_KEY);
    if (!raw) return false;
    var v = JSON.parse(raw);
    if (v && v.doc){ doc = normalize(v.doc); turns = v.turns || []; return true; }
  } catch (e) {}
  return false;
}
function pushHistory(){
  history.push(clone(doc));
  if (history.length > 15) history.shift();
  $("btn-undo").disabled = history.length === 0;
}

/* ---------------- 表示 ---------------- */
function render(){
  var sheets = O.renderDoc(doc);
  $("scaler").innerHTML = sheets.join("");
  autofit();
  applyPageView();
  fit();
  syncControls();
  renderDecoPanel();
  renderStructure();
  markStickers();
}
/** 段に入りきらないときだけ、その段の文字を 0.5px ずつ小さくする（11px まで）。
 *  先生が字数を守らずに出してきても紙面が崩れないようにするため。 */
function autofit(){
  allSheets().forEach(function (sheet){
    var hidden = sheet.hidden;
    if (hidden) sheet.hidden = false;
    Array.prototype.forEach.call(sheet.querySelectorAll(".col"), function (col){
      var add = col.querySelector(".addblk");
      var extra = add ? add.offsetHeight + 16 : 0;
      var over = function (){ return col.scrollHeight - extra > col.clientHeight + 1; };
      col.style.removeProperty("--fs");
      var fs = 14.5;
      while (over() && fs > 11){
        fs -= 0.5;
        col.style.setProperty("--fs", fs + "px");
      }
      col.classList.toggle("over", over());
    });
    if (hidden) sheet.hidden = true;
  });
}
var fitTimer = null;
function allSheets(){ return Array.prototype.slice.call($("scaler").children); }
function applyPageView(){
  allSheets().forEach(function (el, i){
    el.hidden = !(pageView === "both" || String(i + 1) === pageView);
  });
}
function currentFit(){ return Math.min(1, Math.max(0.08, ($("scroller").clientWidth - 36) / PAGE_W)); }
function fit(){
  var scaler = $("scaler"), frame = $("frame");
  if (!scaler) return;
  var f = zoom || currentFit();
  scaler.style.transform = "scale(" + f + ")";
  /* 紙の上の操作ボタンは、縮小しても押せる大きさに保つ */
  scaler.style.setProperty("--inv", Math.max(1, 1 / f).toFixed(3));
  var n = allSheets().filter(function (el){ return !el.hidden; }).length || 1;
  frame.style.width = (PAGE_W * f) + "px";
  frame.style.height = ((n * PAGE_H + (n - 1) * 22) * f) + "px";
  $("zoomlabel").textContent = Math.round(f * 100) + "%";
}
window.addEventListener("resize", fit);

var toastTimer = null;
function toast(msg){
  var t = $("toast"); t.textContent = msg; t.hidden = false;
  clearTimeout(toastTimer); toastTimer = setTimeout(function (){ t.hidden = true; }, 5200);
}
function setBusy(b){
  busy = b;
  ["btn-pdf", "btn-print"].forEach(function (id){ $(id).disabled = b; });
  /* AIを使うボタンは、つながっていないあいだも押せないままにする */
  ["btn-send", "btn-make", "btn-revise", "btn-compose"].forEach(function (id){ $(id).disabled = b || !aiReady; });
}

/* ---------------- 紙の上の編集 ---------------- */
$("scaler").addEventListener("input", function (e){
  var el = e.target.closest && e.target.closest("[contenteditable][data-path]");
  if (!el) return;
  setPath(doc, el.getAttribute("data-path"), el.innerText);
  clearTimeout(saveTimer); saveTimer = setTimeout(saveLocal, 600);
  clearTimeout(fitTimer); fitTimer = setTimeout(autofit, 700);
});
$("scaler").addEventListener("paste", function (e){
  var el = e.target.closest && e.target.closest("[contenteditable][data-path]");
  if (!el) return;
  e.preventDefault();
  var t = (e.clipboardData || window.clipboardData).getData("text/plain").replace(/\r/g, "");
  if (el.hasAttribute("data-oneline")) t = t.replace(/\n+/g, "　");
  document.execCommand("insertText", false, t);
});
/* フッターの文字を全部消して欄を出たら、フッターごと消す。もどすで消す前の文字に戻る */
var footBefore = "";
$("scaler").addEventListener("focusin", function (e){
  if (e.target.hasAttribute && e.target.hasAttribute("data-oneline")) footBefore = e.target.innerText;
});
$("scaler").addEventListener("focusout", function (e){
  var el = e.target;
  if (!el.hasAttribute || !el.hasAttribute("data-oneline")) return;
  if (el.innerText.replace(/\s/g, "") !== "") return;
  var pg = getPath(doc, el.getAttribute("data-path").replace(/\.footer$/, ""));
  if (!pg || typeof pg.footer !== "string") return;
  pg.footer = footBefore;
  pushHistory();
  delete pg.footer;
  setTimeout(function (){ render(); saveLocal(); toast("フッターを消しました。"); }, 0);
});
/* 1行の欄（フッター）は Enter で改行させない */
$("scaler").addEventListener("keydown", function (e){
  if (e.key === "Enter" && e.target.hasAttribute && e.target.hasAttribute("data-oneline")){
    e.preventDefault(); e.target.blur();
  }
});

function splitPath(path){
  var ks = path.split("."), idx = parseInt(ks.pop(), 10);
  return {list: getPath(doc, ks.join(".")), index: idx, listPath: ks.join(".")};
}

$("scaler").addEventListener("click", function (e){
  var slot = e.target.closest && e.target.closest("[data-slot]");
  if (slot){ openIllPicker(slot); return; }
  var b = e.target.closest && e.target.closest("[data-act]");
  if (!b) return;
  var act = b.getAttribute("data-act"), path = b.getAttribute("data-path");

  if (act === "blk-add"){ openBlockPicker(b, path); return; }
  if (act === "blk-deco"){ openDecoPicker(b, path); return; }
  if (act === "photo-pick"){ pickPhotos({list: path}); return; }
  if (act === "photo-slot"){ pickPhotos({slot: path}); return; }

  if (act === "foot-add"){
    pushHistory();
    var pg = getPath(doc, path);
    pg.footer = (doc.meta.school || "◯◯保育園") + "　〒000-0000 ◯◯市◯◯町1-2-3　TEL 000-000-0000";
    render(); saveLocal();
    var ft = document.querySelector('[data-path="' + path + '.footer"]');
    if (ft){
      ft.focus();
      var rg = document.createRange(); rg.selectNodeContents(ft);
      var sel = window.getSelection(); sel.removeAllRanges(); sel.addRange(rg);
    }
    toast("フッターを足しました。そのまま文字を打つと書きかわります。");
    return;
  }

  pushHistory();
  if (act === "foot-del"){
    delete getPath(doc, path).footer;
  } else if (act === "blk-up" || act === "blk-down"){
    var s = splitPath(path);
    var to = s.index + (act === "blk-up" ? -1 : 1);
    if (Array.isArray(s.list) && to >= 0 && to < s.list.length){
      var it = s.list.splice(s.index, 1)[0];
      s.list.splice(to, 0, it);
    }
  } else if (act === "blk-left" || act === "blk-right"){
    /* 隣の段の、同じ順番の位置へ移す（段の長さが足りなければ、いちばん下へ） */
    var mv = /^(pages\.\d+\.columns)\.(\d+)\.blocks\.(\d+)$/.exec(path);
    var cols = mv && getPath(doc, mv[1]);
    var from = mv ? +mv[2] : 0, at = mv ? +mv[3] : 0, toCol = from + (act === "blk-left" ? -1 : 1);
    if (cols && cols[from] && cols[toCol]){
      var moved = cols[from].blocks.splice(at, 1)[0];
      var dest = cols[toCol].blocks;
      dest.splice(Math.min(at, dest.length), 0, moved);
    }
  } else if (act === "blk-del"){
    var s2 = splitPath(path);
    if (Array.isArray(s2.list)) s2.list.splice(s2.index, 1);
  } else if (act === "item-add"){
    var list = getPath(doc, path);
    if (Array.isArray(list)) list.push(O.itemProto(b.getAttribute("data-k")));
  } else if (act === "item-del"){
    var l2 = getPath(doc, path);
    if (Array.isArray(l2)) l2.pop();
  } else if (act === "item-at-del"){
    var l3 = getPath(doc, path);
    if (Array.isArray(l3)) l3.splice(parseInt(b.getAttribute("data-i"), 10), 1);
  } else if (act === "row-add"){
    var blk = getPath(doc, path);
    if (blk && Array.isArray(blk.rows)) blk.rows.push((blk.head || []).map(function (){ return ""; }));
  } else if (act === "row-del"){
    var blk2 = getPath(doc, path);
    if (blk2 && Array.isArray(blk2.rows)) blk2.rows.pop();
  }
  render(); saveLocal();
});

/* ---------------- イラスト選び ---------------- */
/** 分類ごとのイラストの一覧。attr は押したときに読む属性。sticker なら紙へドラッグでき、自作の絵は消せる */
/* ---------------- イラストの一覧（検索・分類・最近使ったもの） ---------------- */
var ILL_RECENT_KEY = "otayori-recent-ill";
function recentIlls(){
  try {
    var v = JSON.parse(localStorage.getItem(ILL_RECENT_KEY) || "[]");
    return Array.isArray(v) ? v.filter(function (k){ return ILL[k]; }) : [];
  } catch (e){ return []; }
}
function noteRecent(k){
  if (!ILL[k]) return;
  var r = recentIlls().filter(function (x){ return x !== k; });
  r.unshift(k);
  try { localStorage.setItem(ILL_RECENT_KEY, JSON.stringify(r.slice(0, 16))); } catch (e){}
  pickerDirty = true;
}
/** 絵の出どころ。工房で描いた絵・Fluent Emoji・先生が足した絵 */
function illStyle(k){ return k.indexOf("u_") === 0 ? "mine" : k.indexOf("f_") === 0 ? "fluent" : "kobo"; }
/** カタカナをひらがなにそろえる。「パンダ」でも「ぱんだ」でも見つかるように */
function kana(s){
  return String(s || "").toLowerCase().replace(/[\u30a1-\u30f6]/g, function (c){
    return String.fromCharCode(c.charCodeAt(0) - 0x60);
  });
}
var illFilter = {};   // 一覧ごとの、いまの絞り込み

function illGridHtml(attr, sticker){
  var groups = {}, order = [], hasMine = false;
  ILL_KEYS.forEach(function (k){
    var g = ILL[k][0];
    if (!groups[g]){ groups[g] = []; order.push(g); }
    groups[g].push(k);
    if (k.indexOf("u_") === 0) hasMine = true;
  });
  function btn(k){
    var mine = sticker && k.indexOf("u_") === 0;
    return (mine ? '<span class="myill">' : "") +
      '<button type="button" ' + attr + '="' + k + '" title="' + esc(ILL[k][1]) + '"' +
      ' data-q="' + esc(kana(ILL[k][1] + " " + ILL[k][0] + " " + k)) + '" data-st="' + illStyle(k) + '"' +
      (sticker ? ' draggable="true"' : "") + ">" + illSvg(k) + "</button>" +
      (mine ? '<i class="mydel" data-mydel="' + k + '" title="一覧から消す">×</i></span>' : "");
  }
  function sec(title, keys, recent){
    return '<div class="illsec" data-g="' + esc(title) + '"' + (recent ? " data-recent" : "") + "><h5>" + esc(title) +
           "</h5><div class='illgrid'>" + keys.map(btn).join("") + "</div></div>";
  }
  var opts = '<option value="">ぜんぶの絵（' + ILL_KEYS.length + "）</option>" +
    '<option value="@kobo">工房の絵</option><option value="@fluent">Fluent の絵</option>' +
    (hasMine ? '<option value="@mine">じぶんの絵</option>' : "") +
    order.map(function (g){ return '<option value="' + esc(g) + '">' + esc(g) + "</option>"; }).join("");
  var h = '<div class="illtools"><input type="search" class="illq" placeholder="さがす（くま・ゆき・はみがき）" aria-label="イラストをさがす">' +
          '<select class="illg" aria-label="分類">' + opts + "</select></div>";
  var rec = recentIlls();
  if (rec.length) h += sec("さいきんつかった", rec, true);
  order.forEach(function (g){ h += sec(g, groups[g], false); });
  return h + '<p class="illnone hint" hidden>見つかりませんでした。ほかの言葉でさがすか、「AIに描いてもらう」を使ってください。</p>';
}

function filterIll(box){
  var qEl = box.querySelector(".illq"), gEl = box.querySelector(".illg");
  if (!qEl || !gEl) return;
  var q = kana(qEl.value.trim()), g = gEl.value, any = false;
  illFilter[box.id] = {q: qEl.value, g: g};
  Array.prototype.forEach.call(box.querySelectorAll(".illsec"), function (sec){
    var recent = sec.hasAttribute("data-recent"), secG = sec.getAttribute("data-g"), shown = 0;
    Array.prototype.forEach.call(sec.querySelectorAll("[data-q]"), function (b){
      var ok = (!q || b.getAttribute("data-q").indexOf(q) >= 0) &&
               (!g || (g.charAt(0) === "@" ? b.getAttribute("data-st") === g.slice(1) : secG === g));
      if (recent && (q || g)) ok = false;   // 絞りこんでいるあいだは「さいきん」を出さない
      (b.closest(".myill") || b).hidden = !ok;
      if (ok) shown++;
    });
    sec.hidden = !shown;
    if (shown) any = true;
  });
  var none = box.querySelector(".illnone");
  if (none) none.hidden = any;
}
function restoreIllFilter(box){
  var f = illFilter[box.id];
  if (!f || !box.querySelector(".illq")) return;
  box.querySelector(".illq").value = f.q;
  box.querySelector(".illg").value = f.g;
  filterIll(box);
}
["illpicker", "stickgrid"].forEach(function (id){
  $(id).addEventListener("input", function (e){ if (e.target.classList.contains("illq")) filterIll(this); });
  $(id).addEventListener("change", function (e){ if (e.target.classList.contains("illg")) filterIll(this); });
});
/* 差しかえの小窓は、初めて開くときに作る（絵が多いので、起動を重くしない） */
var pickerDirty = true;
function buildIllPicker(){ pickerDirty = true; }
function fillIllPicker(){
  $("illpicker").innerHTML = illGridHtml("data-ill", false);
  restoreIllFilter($("illpicker"));
  pickerDirty = false;
}
function place(box, el){
  box.hidden = false;
  var r = el.getBoundingClientRect(), w = box.offsetWidth, h = box.offsetHeight;
  var x = Math.min(Math.max(8, r.left + r.width / 2 - w / 2), window.innerWidth - w - 8);
  var y = r.bottom + 8;
  if (y + h > window.innerHeight - 8) y = Math.max(8, r.top - h - 8);
  box.style.left = x + "px"; box.style.top = y + "px";
}
function openIllPicker(el){
  pickerPath = el.getAttribute("data-slot");
  if (pickerDirty) fillIllPicker();
  place($("illpicker"), el);
  var q = $("illpicker").querySelector(".illq");
  if (q && window.matchMedia("(pointer: fine)").matches) q.focus();
}
$("illpicker").addEventListener("click", function (e){
  var b = e.target.closest("button[data-ill]");
  if (!b || !pickerPath) return;
  pushHistory();
  noteRecent(b.getAttribute("data-ill"));
  setPath(doc, pickerPath, b.getAttribute("data-ill"));
  this.hidden = true; pickerPath = null;
  render(); saveLocal();
});

function buildBlockPicker(){
  $("blockpicker").innerHTML = O.BLOCK_KINDS.map(function (p){
    return '<button type="button" data-kind="' + p[0] + '">' + esc(p[1]) + "</button>";
  }).join("");
}
function openBlockPicker(el, path){ blockAddPath = path; place($("blockpicker"), el); }
$("blockpicker").addEventListener("click", function (e){
  var b = e.target.closest("button[data-kind]");
  if (!b || !blockAddPath) return;
  var list = getPath(doc, blockAddPath);
  if (Array.isArray(list)){ pushHistory(); list.push(O.blockProto(b.getAttribute("data-kind"))); }
  this.hidden = true; blockAddPath = null;
  render(); saveLocal();
});
document.addEventListener("click", function (e){
  [["illpicker", "[data-slot]"], ["blockpicker", "[data-act='blk-add']"],
   ["decopicker", "[data-act='blk-deco']"]].forEach(function (pair){
    var box = $(pair[0]);
    if (box.hidden || box.contains(e.target)) return;
    if (e.target.closest && e.target.closest(pair[1])) return;
    box.hidden = true;
  });
}, true);
document.addEventListener("keydown", function (e){
  if (e.key === "Escape"){ $("illpicker").hidden = true; $("blockpicker").hidden = true; $("decopicker").hidden = true; }
});

/* ---------------- ブロックひとつのかざり ---------------- */
var decoPath = null;
var DECO_BOX = [["paper", "画用紙"], ["balloon", "ふきだし"], ["frame", "二重わく"], ["band", "いろおび"], ["plain", "なし"]];
var DECO_TAPE = [["auto", "おまかせ"], ["tape", "テープ"], ["taper", "いろテープ"], ["pin", "がびょう"], ["none", "なし"]];
var DECO_TILT = [[-1.5, "ひだり"], [0, "まっすぐ"], [1.5, "みぎ"]];
var DECO_GROW = [["no", "ふつう"], ["yes", "下までのばす"]];

function openDecoPicker(el, path){
  decoPath = path;
  fillDecoPicker();
  place($("decopicker"), el);
}
function fillDecoPicker(){
  var b = getPath(doc, decoPath);
  if (!b){ $("decopicker").hidden = true; return; }
  var box = b.box || (b.kind === "banner" ? "band" : "paper");
  var tape = b.tape || "auto", tilt = typeof b.tilt === "number" ? b.tilt : 0;
  function row(title, key, opts, cur, sample){
    return "<h5>" + title + '</h5><div class="dpro">' + opts.map(function (o){
      var on = key === "tilt" ? Math.sign(o[0]) === Math.sign(cur) : o[0] === cur;
      return '<button type="button" data-k="' + key + '" data-v="' + o[0] + '" aria-pressed="' + on + '">' +
             sample(o[0]) + "<small>" + o[1] + "</small></button>";
    }).join("") + "</div>";
  }
  var h = '<div style="' + palVars(curPal()) + '">';
  if (O.BOXED.indexOf(b.kind) >= 0){
    h += row("わく", "box", DECO_BOX, box, function (v){ return '<i class="mbx mb-' + v + '"></i>'; });
  }
  if (O.TAPED.indexOf(b.kind) >= 0){
    h += row("とめるもの", "tape", DECO_TAPE, tape, function (v){ return '<i class="mtp mt-' + v + '"></i>'; });
  }
  h += row("かたむき", "tilt", DECO_TILT, tilt, function (v){
    return '<i class="mbx mb-paper" style="transform:rotate(' + (v * 6) + 'deg)"></i>';
  });
  if (decoPath.indexOf(".columns.") >= 0){
    h += row("たかさ", "grow", DECO_GROW, b.grow ? "yes" : "no", function (v){
      return '<i class="mbx mb-paper mb-' + (v === "yes" ? "tall" : "short") + '"></i>';
    });
    h += '<p class="dhint">横幅は、段と段のあいだの ⇔ を左右にドラッグして変えます。</p>';
  }
  $("decopicker").innerHTML = h + "</div>";
}
$("decopicker").addEventListener("click", function (e){
  var btn = e.target.closest("button[data-k]");
  if (!btn || !decoPath) return;
  var b = getPath(doc, decoPath);
  if (!b) return;
  var k = btn.getAttribute("data-k"), v = btn.getAttribute("data-v");
  pushHistory();
  if (k === "tilt") b.tilt = parseFloat(v);
  else if (k === "grow"){ if (v === "yes") b.grow = true; else delete b.grow; }
  else if (k === "tape" && v === "auto") delete b.tape;
  else b[k] = v;
  render(); saveLocal(); fillDecoPicker();
});

/* ---------------- 写真 ----------------
   入れ方は三つ。枠を押す／紙の上にドラッグ／かざるタブの「写真をのせる」。
   どれも長い辺 1400px の JPEG に縮めてから載せる（自動保存の容量に収めるため）。 */
var PHOTO_MAX = 1400;

function loadPhoto(file){
  return new Promise(function (resolve, reject){
    var url = URL.createObjectURL(file), img = new Image();
    img.onload = function (){
      var s = Math.min(1, PHOTO_MAX / Math.max(img.naturalWidth, img.naturalHeight));
      var c = document.createElement("canvas");
      c.width = Math.round(img.naturalWidth * s); c.height = Math.round(img.naturalHeight * s);
      var g = c.getContext("2d");
      g.fillStyle = "#fff"; g.fillRect(0, 0, c.width, c.height);
      g.drawImage(img, 0, 0, c.width, c.height);
      URL.revokeObjectURL(url);
      resolve(c.toDataURL("image/jpeg", 0.85));
    };
    img.onerror = function (){ URL.revokeObjectURL(url); reject(new Error(file.name)); };
    img.src = url;
  });
}
async function loadPhotos(files){
  var out = [], bad = 0;
  for (var i = 0; i < files.length; i++){
    if (!/^image\//.test(files[i].type)) { bad++; continue; }
    try { out.push(await loadPhoto(files[i])); } catch (e){ bad++; }
  }
  if (bad) toast("読めない写真がありました（" + bad + "まい）。JPEG か PNG の写真にしてください。");
  return out;
}

function findBlocks(kind){
  var out = [];
  doc.pages.forEach(function (pg, pi){
    function scan(list, base){
      (list || []).forEach(function (b, i){ if (b && b.kind === kind) out.push({block: b, path: base + "." + i}); });
    }
    scan(pg.top, "pages." + pi + ".top");
    scan(pg.bottom, "pages." + pi + ".bottom");
    (pg.columns || []).forEach(function (c, ci){ scan(c.blocks, "pages." + pi + ".columns." + ci + ".blocks"); });
  });
  return out;
}
/** 写真の枠が紙になければ、いちばんすいている段に作る */
function ensurePhotoBlock(){
  var found = findBlocks("photo");
  if (found.length) return found[found.length - 1].block;
  var best = null;
  doc.pages.forEach(function (pg, pi){
    (pg.columns || []).forEach(function (c, ci){
      if (!best || c.blocks.length < best.n) best = {n: c.blocks.length, col: c, pi: pi, ci: ci};
    });
  });
  var b = O.blockProto("photo");
  b.heading = "写真で見る今月"; b.items = [];
  if (best) best.col.blocks.push(b);
  else doc.pages[0].bottom.push(b);
  toast(best ? (best.pi + 1) + "ページ目の " + (best.ci + 1) + "段目に写真の枠を作りました。枠の右上の ↑↓ で動かせます。"
             : "1ページ目の下に写真の枠を作りました。");
  return b;
}
/** 空いている枠から順に埋め、足りなければ枠を足す */
function putPhotos(list, srcs){
  srcs.forEach(function (src){
    var empty = list.filter(function (it){ return it && !it.src; })[0];
    if (empty) empty.src = src;
    else list.push({src: src, caption: "写真のせつめい"});
  });
}

var photoTarget = null;   // {slot: "…items.0"} か {list: "…items"} か {anywhere: true}
function pickPhotos(target){
  photoTarget = target;
  $("photo-in").multiple = !target.slot;
  $("photo-in").click();
}
async function placePhotos(files, target){
  if (!files.length) return;
  var srcs = await loadPhotos(files);
  if (!srcs.length) return;
  pushHistory();
  if (target.slot){
    var it = getPath(doc, target.slot);
    if (it) it.src = srcs[0];
    var rest = srcs.slice(1);
    if (rest.length) putPhotos(getPath(doc, target.slot.replace(/\.\d+$/, "")), rest);
  } else {
    var list = target.list ? getPath(doc, target.list) : null;
    if (!Array.isArray(list)) list = ensurePhotoBlock().items;
    putPhotos(list, srcs);
  }
  render(); saveLocal();
}
$("photo-in").addEventListener("change", function (){
  var files = Array.prototype.slice.call(this.files || []), t = photoTarget;
  this.value = ""; photoTarget = null;
  if (t) placePhotos(files, t);
});
$("btn-photo").addEventListener("click", function (){ pickPhotos({anywhere: true}); });

/* 紙の上へのドラッグ。枠の上なら その枠へ、写真ブロックの上なら そのブロックへ、ほかは自動で */
var scroller = $("scroller");
function hasFiles(e){ return e.dataTransfer && Array.prototype.indexOf.call(e.dataTransfer.types || [], "Files") >= 0; }
scroller.addEventListener("dragover", function (e){
  if (!hasFiles(e) && !hasIll(e)) return;
  e.preventDefault();
  e.dataTransfer.dropEffect = "copy";
  scroller.classList.add("dropping");
});
scroller.addEventListener("dragleave", function (e){
  if (!scroller.contains(e.relatedTarget)) scroller.classList.remove("dropping");
});
scroller.addEventListener("drop", function (e){
  if (hasIll(e)){ e.preventDefault(); scroller.classList.remove("dropping"); dropSticker(e); return; }
  if (!hasFiles(e)) return;
  e.preventDefault();
  scroller.classList.remove("dropping");
  var files = Array.prototype.slice.call(e.dataTransfer.files || []);
  var slot = e.target.closest && e.target.closest("[data-act='photo-slot']");
  var blk = e.target.closest && e.target.closest(".blk");
  var wrap = blk && blk.querySelector("[data-photos]");
  placePhotos(files, slot ? {slot: slot.getAttribute("data-path")}
                     : wrap ? {list: wrap.getAttribute("data-photos")} : {anywhere: true});
});

/* ---------------- イラストを貼る（シール） ----------------
   pages[].stickers に {k, x, y, s, r}。x, y は紙の上の中心（px）、s は一辺、r は回転（度）。 */
var ILL_MIME = "text/x-otayori-ill";
var selStk = null, stkDrag = null;

function clampNum(v, lo, hi){ return Math.min(hi, Math.max(lo, v)); }
function commitHistory(before){
  history.push(before);
  if (history.length > 15) history.shift();
  $("btn-undo").disabled = false;
}

function addSticker(k, pi, x, y){
  var pg = doc.pages[pi];
  if (!pg || !ILL[k]) return;
  if (!Array.isArray(pg.stickers)) pg.stickers = [];
  pushHistory();
  pg.stickers.push({k: k, x: Math.round(clampNum(x, 30, PAGE_W - 30)), y: Math.round(clampNum(y, 30, PAGE_H - 30)),
                    s: 90, r: Math.round(Math.random() * 24 - 12)});
  selStk = pi + "." + (pg.stickers.length - 1);
  render(); saveLocal();
}
/** いま画面にいちばん大きく見えているページの、見えている所の真ん中あたり */
function visibleSpot(){
  var sc = $("scroller").getBoundingClientRect(), best = null;
  allSheets().forEach(function (el, i){
    if (el.hidden) return;
    var r = el.getBoundingClientRect();
    var t = Math.max(r.top, sc.top), b = Math.min(r.bottom, sc.bottom);
    var l = Math.max(r.left, sc.left), rt = Math.min(r.right, sc.right);
    var area = Math.max(0, b - t) * Math.max(0, rt - l);
    if (!best || area > best.area) best = {area: area, i: i, r: r, cx: (l + rt) / 2, cy: (t + b) / 2};
  });
  if (!best) return {pi: 0, x: PAGE_W / 2, y: PAGE_H / 2};
  var f = best.r.width / PAGE_W;
  return {pi: best.i, x: (best.cx - best.r.left) / f + (Math.random() - 0.5) * 160,
          y: (best.cy - best.r.top) / f + (Math.random() - 0.5) * 120};
}
function markStickers(){
  Array.prototype.forEach.call(document.querySelectorAll(".stk.sel"), function (el){ el.classList.remove("sel"); });
  if (!selStk) return;
  var el = document.querySelector('.stk[data-stk="' + selStk + '"]');
  if (el) el.classList.add("sel"); else selStk = null;
}
function stkStyle(el, st){ el.setAttribute("style", O.stickerStyle(st)); }

$("scaler").addEventListener("pointerdown", function (e){
  var el = e.target.closest && e.target.closest(".stk");
  if (!el){
    if (selStk){ selStk = null; markStickers(); }
    return;
  }
  var ids = el.getAttribute("data-stk").split("."), pg = doc.pages[+ids[0]];
  var st = pg && pg.stickers && pg.stickers[+ids[1]];
  if (!st) return;
  e.preventDefault();
  var h = e.target.closest("[data-h]"), mode = h ? h.getAttribute("data-h") : "move";
  selStk = el.getAttribute("data-stk"); markStickers();
  if (mode === "del"){
    pushHistory();
    pg.stickers.splice(+ids[1], 1);
    selStk = null; render(); saveLocal();
    return;
  }
  var sr = el.closest(".sheet").getBoundingClientRect(), f = sr.width / PAGE_W;
  var cx = sr.left + st.x * f, cy = sr.top + st.y * f;
  stkDrag = {el: el, st: st, mode: mode, f: f, cx: cx, cy: cy, x0: e.clientX, y0: e.clientY,
             sx: st.x, sy: st.y, s0: st.s, d0: Math.hypot(e.clientX - cx, e.clientY - cy) || 1,
             before: clone(doc), moved: false};
  el.setPointerCapture(e.pointerId);
});
$("scaler").addEventListener("pointermove", function (e){
  if (!stkDrag) return;
  var d = stkDrag, st = d.st;
  if (d.mode === "move"){
    st.x = Math.round(clampNum(d.sx + (e.clientX - d.x0) / d.f, 0, PAGE_W));
    st.y = Math.round(clampNum(d.sy + (e.clientY - d.y0) / d.f, 0, PAGE_H));
  } else if (d.mode === "size"){
    st.s = Math.round(clampNum(d.s0 * Math.hypot(e.clientX - d.cx, e.clientY - d.cy) / d.d0, 24, 420));
  } else if (d.mode === "rot"){
    var a = Math.atan2(e.clientY - d.cy, e.clientX - d.cx) * 180 / Math.PI + 90;
    a = ((a + 540) % 360) - 180;
    st.r = Math.abs(a) < 4 ? 0 : Math.round(a);   // まっすぐの近くは吸いつける
  }
  d.moved = true;
  stkStyle(d.el, st);
});
function endStk(){
  if (!stkDrag) return;
  var d = stkDrag; stkDrag = null;
  if (!d.moved) return;
  commitHistory(d.before);
  saveLocal();
}
$("scaler").addEventListener("pointerup", endStk);
$("scaler").addEventListener("pointercancel", endStk);

/* ダブルクリックで別の絵にかえる */
$("scaler").addEventListener("dblclick", function (e){
  var el = e.target.closest && e.target.closest(".stk");
  if (!el) return;
  var ids = el.getAttribute("data-stk").split(".");
  pickerPath = "pages." + ids[0] + ".stickers." + ids[1] + ".k";
  place($("illpicker"), el);
});
/* 選んだシールは Delete でもはがせる（文字を打っている最中はのぞく） */
document.addEventListener("keydown", function (e){
  if (!selStk || (e.key !== "Delete" && e.key !== "Backspace")) return;
  var a = document.activeElement;
  if (a && (a.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(a.tagName))) return;
  var ids = selStk.split("."), pg = doc.pages[+ids[0]];
  if (!pg || !pg.stickers) return;
  e.preventDefault();
  pushHistory();
  pg.stickers.splice(+ids[1], 1);
  selStk = null; render(); saveLocal();
});

/* かざるタブのイラスト一覧：押すと貼る、紙へドラッグしても貼れる */
function renderStickGrid(){
  $("stickgrid").innerHTML = illGridHtml("data-stick", true);
  restoreIllFilter($("stickgrid"));
}
$("stickgrid").addEventListener("click", function (e){
  var del = e.target.closest("[data-mydel]");
  if (del){ removeMyIllust(del.getAttribute("data-mydel")); return; }
  var b = e.target.closest("button[data-stick]");
  if (!b) return;
  var spot = visibleSpot();
  noteRecent(b.getAttribute("data-stick"));
  addSticker(b.getAttribute("data-stick"), spot.pi, spot.x, spot.y);
  toast("貼りました。ドラッグで動かせます。");
});
$("stickgrid").addEventListener("dragstart", function (e){
  var b = e.target.closest && e.target.closest("button[data-stick]");
  if (!b) return;
  e.dataTransfer.setData(ILL_MIME, b.getAttribute("data-stick"));
  e.dataTransfer.effectAllowed = "copy";
});
function hasIll(e){ return e.dataTransfer && Array.prototype.indexOf.call(e.dataTransfer.types || [], ILL_MIME) >= 0; }
function dropSticker(e){
  var k = e.dataTransfer.getData(ILL_MIME);
  var sheet = e.target.closest && e.target.closest(".sheet");
  if (!k || !sheet) return;
  noteRecent(k);
  var r = sheet.getBoundingClientRect(), f = r.width / PAGE_W;
  addSticker(k, allSheets().indexOf(sheet), (e.clientX - r.left) / f, (e.clientY - r.top) / f);
}

/* ---------------- 自作のイラスト ----------------
   画面で縮めて（長い辺 600px）、白い背景を透明にし、余白を切ってから PNG でサーバへ。 */
var MY_GROUP = "じぶんの絵", MY_MAX = 600;

function makeIllust(file, dropWhite){
  return new Promise(function (resolve, reject){
    var url = URL.createObjectURL(file), img = new Image();
    img.onload = function (){
      URL.revokeObjectURL(url);
      var w0 = img.naturalWidth || 300, h0 = img.naturalHeight || 300;
      var s = Math.min(1, MY_MAX / Math.max(w0, h0));
      var c = document.createElement("canvas");
      c.width = Math.max(1, Math.round(w0 * s)); c.height = Math.max(1, Math.round(h0 * s));
      var g = c.getContext("2d");
      g.drawImage(img, 0, 0, c.width, c.height);
      var im = g.getImageData(0, 0, c.width, c.height), px = im.data;
      if (dropWhite){
        /* 白に近いほど透明に。紙の白やスキャンのうすい影を消し、線のふちはなめらかに残す */
        for (var i = 0; i < px.length; i += 4){
          var m = Math.min(px[i], px[i + 1], px[i + 2]);
          if (m >= 236) px[i + 3] = 0;
          else if (m > 206) px[i + 3] = Math.round(px[i + 3] * (236 - m) / 30);
        }
        g.putImageData(im, 0, 0);
      }
      /* まわりの透明な余白を切る。絵が枠いっぱいに出るように */
      var x0 = c.width, y0 = c.height, x1 = -1, y1 = -1;
      for (var y = 0; y < c.height; y++){
        for (var x = 0; x < c.width; x++){
          if (px[(y * c.width + x) * 4 + 3] > 16){
            if (x < x0) x0 = x; if (x > x1) x1 = x;
            if (y < y0) y0 = y; if (y > y1) y1 = y;
          }
        }
      }
      if (x1 < 0){ reject(new Error("empty")); return; }
      var pad = 4, cw = x1 - x0 + 1 + pad * 2, ch = y1 - y0 + 1 + pad * 2;
      var o = document.createElement("canvas");
      o.width = cw; o.height = ch;
      o.getContext("2d").drawImage(c, x0, y0, x1 - x0 + 1, y1 - y0 + 1, pad, pad, x1 - x0 + 1, y1 - y0 + 1);
      resolve(o.toDataURL("image/png"));
    };
    img.onerror = function (){ URL.revokeObjectURL(url); reject(new Error(file.name)); };
    img.src = url;
  });
}

function registerMyIllust(items){
  for (var i = ILL_KEYS.length - 1; i >= 0; i--){
    if (ILL_KEYS[i].indexOf("u_") === 0){ delete ILL[ILL_KEYS[i]]; ILL_KEYS.splice(i, 1); }
  }
  (items || []).slice().reverse().forEach(function (it){
    var k = "u_" + it.id;
    ILL[k] = [MY_GROUP, it.name,
      '<image href="' + it.src + '" x="0" y="0" width="48" height="48" preserveAspectRatio="xMidYMid meet"/>'];
    ILL_KEYS.unshift(k);
  });
}
function refreshIllust(items){
  registerMyIllust(items);
  buildIllPicker(); renderStickGrid(); render();
}

async function addMyIllust(files){
  var dropWhite = $("my-white").checked, added = 0, bad = 0, last = null;
  for (var i = 0; i < files.length; i++){
    if (!/^image\//.test(files[i].type)){ bad++; continue; }
    try {
      var src = await makeIllust(files[i], dropWhite);
      var name = files[i].name.replace(/\.[^.]+$/, "").slice(0, 20);
      last = await api("/api/illust/add", {name: name, src: src});
      added++;
    } catch (e){ bad++; }
  }
  if (last) refreshIllust(last.items);
  if (added) toast(added + "まい追加しました。一覧のいちばん上「" + MY_GROUP + "」にあります。" + (bad ? "（読めなかった絵が " + bad + "まい）" : ""));
  else if (bad) toast("絵を読みとれませんでした。JPEG か PNG にしてください。白い背景を消すと何も残らない絵は、チェックを外してください。");
}
async function removeMyIllust(k){
  var name = ILL[k] ? ILL[k][1] : "";
  if (!window.confirm("「" + name + "」を一覧から消しますか？\n紙に貼ったものは消え、題字や見出しに使っているところは さくら に変わります。")) return;
  try { refreshIllust((await api("/api/illust/del", {id: k.slice(2)})).items); toast("消しました。"); }
  catch (e){ toast(e.message); }
}
/* ---------------- AIに描いてもらう ----------------
   3案を見せ、選んだ案を PNG にして「じぶんの絵」に保存する（貼る・題字に使う・控えに残る、が今のまま使える）。 */
var drawing = false;
function svgToPng(svg, size){
  return new Promise(function (resolve, reject){
    var url = URL.createObjectURL(new Blob([svg], {type: "image/svg+xml"}));
    var img = new Image();
    img.onload = function (){
      var c = document.createElement("canvas");
      c.width = c.height = size;
      c.getContext("2d").drawImage(img, 0, 0, size, size);
      URL.revokeObjectURL(url);
      resolve(c.toDataURL("image/png"));
    };
    img.onerror = function (){ URL.revokeObjectURL(url); reject(new Error("svg")); };
    img.src = url;
  });
}
async function aiDraw(){
  var what = $("ai-draw-in").value.trim(), out = $("ai-draw-out");
  if (!what){ toast("どんな絵がほしいか書いてください。"); $("ai-draw-in").focus(); return; }
  if (drawing) return;
  drawing = true; $("ai-draw-go").disabled = true;
  out.innerHTML = '<div class="note"><span class="thinking"><span class="dot"></span><span class="dot"></span>' +
                  '<span class="dot"></span>描いています（30秒ほど）</span></div>';
  try {
    var r = await api("/api/illust/draw", Object.assign({what: what}, aiOpts()));
    out.innerHTML = "";
    (r.svgs || []).forEach(function (svg, i){
      var d = document.createElement("div");
      d.className = "cand";
      d.innerHTML = svg + '<button class="btn sm" type="button">使う</button>';   // サーバで図形だけに組み直してある
      d.querySelector("button").addEventListener("click", async function (){
        var btn = this;
        btn.disabled = true; btn.textContent = "保存しています…";
        try {
          var src = await svgToPng(svg, MY_MAX);
          var res = await api("/api/illust/add", {name: what.slice(0, 20), src: src});
          refreshIllust(res.items);
          out.innerHTML = "";
          $("ai-draw-in").value = "";
          toast("「" + what.slice(0, 20) + "」を追加しました。一覧のいちばん上「" + MY_GROUP + "」にあります。");
        } catch (e){
          btn.disabled = false; btn.textContent = "使う";
          toast(e.message || "保存できませんでした。");
        }
      });
      out.appendChild(d);
    });
  } catch (e){
    out.innerHTML = "";
    toast(e.message);
  } finally {
    drawing = false; $("ai-draw-go").disabled = false;
  }
}
$("ai-draw-go").addEventListener("click", aiDraw);
$("ai-draw-in").addEventListener("keydown", function (e){ if (e.key === "Enter"){ e.preventDefault(); aiDraw(); } });

$("btn-myillust").addEventListener("click", function (){ $("illust-in").click(); });
$("illust-in").addEventListener("change", function (){
  var files = Array.prototype.slice.call(this.files || []);
  this.value = "";
  if (files.length) addMyIllust(files);
});
/* 一覧の上に画像ファイルを落としても追加できる */
$("stickbox").addEventListener("dragover", function (e){
  if (!hasFiles(e)) return;
  e.preventDefault(); this.classList.add("dropping");
});
$("stickbox").addEventListener("dragleave", function (e){
  if (!this.contains(e.relatedTarget)) this.classList.remove("dropping");
});
$("stickbox").addEventListener("drop", function (e){
  if (!hasFiles(e)) return;
  e.preventDefault(); this.classList.remove("dropping");
  addMyIllust(Array.prototype.slice.call(e.dataTransfer.files || []));
});

/* ---------------- 段の横幅をドラッグで変える ---------------- */
var grip = null;
$("scaler").addEventListener("pointerdown", function (e){
  var g = e.target.closest && e.target.closest("[data-grip]");
  if (!g) return;
  e.preventDefault();
  var ids = g.getAttribute("data-grip").split("."), pg = doc.pages[+ids[0]], ci = +ids[1];
  var colA = g.parentNode, colB = colA.nextElementSibling;
  while (colB && !colB.classList.contains("col")) colB = colB.nextElementSibling;
  if (!pg || !colB) return;
  grip = {el: g, pg: pg, ci: ci, a: colA, b: colB, x: e.clientX, before: clone(doc),
          pa: colA.getBoundingClientRect().width, pb: colB.getBoundingClientRect().width,
          scale: colA.getBoundingClientRect().width / colA.offsetWidth,
          wsum: pg.columns[ci].w + pg.columns[ci + 1].w};
  g.setPointerCapture(e.pointerId);
  g.classList.add("on");
});
$("scaler").addEventListener("pointermove", function (e){
  if (!grip) return;
  /* 段は紙の上で 260px より細くしない。それより細いと文字が1行に数文字しか入らない */
  var total = grip.pa + grip.pb, min = Math.min(total / 2, 260 * grip.scale);
  var pa = Math.min(total - min, Math.max(min, grip.pa + (e.clientX - grip.x)));
  var wa = +(grip.wsum * pa / total).toFixed(2), wb = +(grip.wsum - wa).toFixed(2);
  grip.wa = wa; grip.wb = wb;
  grip.a.style.flex = wa; grip.b.style.flex = wb;
});
function endGrip(){
  if (!grip) return;
  var g = grip; grip = null;
  g.el.classList.remove("on");
  if (g.wa == null) return;
  history.push(g.before);
  if (history.length > 15) history.shift();
  $("btn-undo").disabled = false;
  g.pg.columns[g.ci].w = g.wa; g.pg.columns[g.ci + 1].w = g.wb;
  render(); saveLocal();
}
$("scaler").addEventListener("pointerup", endGrip);
$("scaler").addEventListener("pointercancel", endGrip);

/* ---------------- 段組みパネル ---------------- */
function renderStructure(){
  var h = "";
  doc.pages.forEach(function (pg, pi){
    h += '<div class="pagebox"><h5>' + (pi + 1) + "ページ　帯 上" + pg.top.length +
         " ／ 下" + pg.bottom.length + "</h5>";
    if (!pg.columns.length) h += '<div class="hint">段がありません</div>';
    pg.columns.forEach(function (c, ci){
      h += '<div class="colrow"><span class="nm">' + (ci + 1) + "段目　ブロック" + c.blocks.length + "こ</span>" +
        '<span class="w">' + c.w.toFixed(1) + "</span>" +
        '<button class="btn sm" type="button" data-s="w-" data-p="' + pi + '" data-c="' + ci + '">－</button>' +
        '<button class="btn sm" type="button" data-s="w+" data-p="' + pi + '" data-c="' + ci + '">＋</button>' +
        '<button class="btn sm ghost" type="button" data-s="col-del" data-p="' + pi + '" data-c="' + ci + '">✕</button></div>';
    });
    h += '<div class="uirow" style="margin-top:9px"><button class="btn sm" type="button" data-s="col-add" data-p="' + pi + '">＋ 段を足す</button></div></div>';
  });
  $("structure").innerHTML = h;
}
$("structure").addEventListener("click", function (e){
  var b = e.target.closest("button[data-s]");
  if (!b) return;
  var s = b.getAttribute("data-s"), pi = +b.getAttribute("data-p"), ci = +b.getAttribute("data-c");
  var pg = doc.pages[pi];
  if (!pg) return;
  pushHistory();
  if (s === "w-") pg.columns[ci].w = Math.max(0.5, +(pg.columns[ci].w - 0.2).toFixed(2));
  else if (s === "w+") pg.columns[ci].w = Math.min(4, +(pg.columns[ci].w + 0.2).toFixed(2));
  else if (s === "col-del") pg.columns.splice(ci, 1);
  else if (s === "col-add" && pg.columns.length < 4) pg.columns.push({w: 1, blocks: []});
  render(); saveLocal();
});

/* ---------------- かざる（見て選ぶパネル） ----------------
   どれも押せばすぐ紙に反映する。気に入らなければ「もどす」。 */
var MOODS = [
  {k: "fuwari",   name: "ふんわり",     desc: "やさしい水玉",
   theme: {pattern: "dots", titleFont: "pop", headingFont: "maru", level: "mori"},
   boxes: ["paper", "balloon", "paper", "frame"], tilt: 1},
  {k: "nigiyaka", name: "にぎやか",     desc: "紙ふぶきで元気に",
   theme: {pattern: "confetti", titleFont: "pop", headingFont: "pop", level: "max"},
   boxes: ["paper", "band", "balloon", "frame"], tilt: 1.5},
  {k: "tegaki",   name: "手がき風",     desc: "ほっこりチェック",
   theme: {pattern: "check", titleFont: "tegaki", headingFont: "tegaki", level: "mori"},
   boxes: ["paper", "paper", "frame"], tilt: 1.2},
  {k: "kirakira", name: "きらきら",     desc: "おほしさま",
   theme: {pattern: "star", titleFont: "pop", headingFont: "maru", level: "max"},
   boxes: ["frame", "balloon", "paper"], tilt: 0.8},
  {k: "ohana",    name: "おはなばたけ", desc: "小花とふきだし",
   theme: {pattern: "flower", titleFont: "maru", headingFont: "tegaki", level: "mori"},
   boxes: ["balloon", "paper", "band"], tilt: 0.8},
  {k: "sukkiri",  name: "すっきり",     desc: "読みやすさ優先",
   theme: {pattern: "plain", titleFont: "maru", headingFont: "maru", level: "futsu"},
   boxes: ["frame", "plain"], tilt: 0}
];
var LEVELS = [["futsu", "ひかえめ", 1], ["mori", "もりもり", 3], ["max", "てんこもり", 5]];
var SEASONS = [["haru", "はる", "sakura"], ["tsuyu", "つゆ", "ajisai"], ["natsu", "なつ", "himawari"],
               ["aki", "あき", "momiji"], ["fuyu", "ふゆ", "yukidaruma"], ["mix", "とりまぜ", "kuma"]];
var PATTERNS = [["dots", "みずたま"], ["check", "チェック"], ["stripe", "ストライプ"], ["grid", "ほうがん"],
                ["star", "ほし"], ["heart", "ハート"], ["flower", "こばな"], ["confetti", "かみふぶき"], ["plain", "むじ"]];
var FONT_NAMES = [["pop", "はちまるポップ"], ["maru", "まるゴシック"], ["tegaki", "てがき風"], ["kyo", "きょうかしょ体"]];

function curPal(){ return PALETTES[doc.theme.palette] || PALETTES.wakaba; }
/** 見本の小さな紙に使う色。CSS の .mbx / .mtp がこれを読む */
function palVars(p){
  return "--a:" + p.accent + ";--a3:" + p.accent3 + ";--r:" + p.rule + ";--t:" + p.tint + ";--tp:" + p.tape;
}
function eachBlock(fn){
  doc.pages.forEach(function (pg){
    (pg.top || []).forEach(fn); (pg.bottom || []).forEach(fn);
    (pg.columns || []).forEach(function (c){ (c.blocks || []).forEach(fn); });
  });
}

function renderDecoPanel(){
  var p = curPal(), t = doc.theme, vars = palVars(p);

  $("moods").innerHTML = MOODS.map(function (m){
    var on = ["pattern", "titleFont", "headingFont", "level"].every(function (k){ return t[k] === m.theme[k]; });
    return '<button type="button" class="mood" data-mood="' + m.k + '" aria-pressed="' + on + '" style="' + vars + '">' +
      '<span class="mini" style="background:' + p.paper + '">' + O.bgPattern(m.theme.pattern, p.tint2, "mp-" + m.k) +
      '<span class="mt" style="font-family:' + FONTS[m.theme.titleFont] + ';color:' + p.accent + '">おたより</span>' +
      '<span class="mrow"><i class="mbx mb-' + m.boxes[0] + '"></i><i class="mbx mb-' + (m.boxes[1] || m.boxes[0]) + '"></i></span>' +
      "</span><b>" + esc(m.name) + "</b><small>" + esc(m.desc) + "</small></button>";
  }).join("");

  $("levels").innerHTML = LEVELS.map(function (l){
    var ic = "";
    for (var i = 0; i < l[2]; i++) ic += illSvg(["hana", "hoshi", "onpu", "chouchou", "tentou"][i]);
    return '<button type="button" class="lvl" data-level="' + l[0] + '" aria-pressed="' + (t.level === l[0]) + '">' +
      '<span class="ics">' + ic + "</span><b>" + l[1] + "</b></button>";
  }).join("");

  $("palettes").innerHTML = Object.keys(PALETTES).map(function (k){
    var q = PALETTES[k];
    return '<button class="sw" type="button" data-pal="' + k + '" aria-pressed="' + (t.palette === k) + '">' +
      '<span class="bars"><i style="background:' + q.accent + '"></i><i style="background:' + q.accent2 + '"></i>' +
      '<i style="background:' + q.accent3 + '"></i><i style="background:' + q.tint2 + '"></i></span>' +
      "<small>" + q.name + "</small></button>";
  }).join("");

  $("seasons").innerHTML = SEASONS.map(function (x){
    return '<button type="button" class="ssn" data-season="' + x[0] + '">' + illSvg(x[2]) + "<small>" + x[1] + "</small></button>";
  }).join("");

  $("patterns").innerHTML = PATTERNS.map(function (x){
    return '<button type="button" class="pat" data-pattern="' + x[0] + '" aria-pressed="' + (t.pattern === x[0]) + '">' +
      '<span class="tile" style="background:' + p.paper + '">' + O.bgPattern(x[0], p.rule, "pp-" + x[0]) + "</span>" +
      "<small>" + x[1] + "</small></button>";
  }).join("");

  ["tfonts", "hfonts"].forEach(function (id){
    var key = id === "tfonts" ? "titleFont" : "headingFont";
    $(id).innerHTML = FONT_NAMES.map(function (f){
      return '<button type="button" class="fnt" data-key="' + key + '" data-font="' + f[0] + '" aria-pressed="' + (t[key] === f[0]) + '">' +
        '<span style="font-family:' + FONTS[f[0]] + ';color:' + p.accent + '">' + (id === "tfonts" ? "ひまわり組" : "今月の予定") + "</span>" +
        "<small>" + f[1] + "</small></button>";
    }).join("");
  });
}

/** ふんいきを当てる。紙全体の体裁に加えて、囲みのわく・テープ・かたむきも着せかえる */
function applyMood(m){
  for (var k in m.theme) doc.theme[k] = m.theme[k];
  var i = 0;
  eachBlock(function (b){
    if (!b) return;
    if (O.TAPED.indexOf(b.kind) >= 0){
      b.box = m.boxes[i % m.boxes.length];
      if (m.tilt) delete b.tape; else b.tape = "none";
    }
    b.tilt = m.tilt ? +(((i % 2) ? 1 : -1) * m.tilt * (0.4 + Math.random() * 0.6)).toFixed(1) : 0;
    i++;
  });
}
function shuffleIlls(season){
  doc.pages.forEach(function (pg){
    pg.deco.corners = someIlls(4, season);
    pg.deco.edge = someIlls(10, season);
  });
  eachBlock(function (b){
    if (!b) return;
    if (b.kind === "illband") b.items = someIlls((b.items || []).length || 7, season);
    else if (b.ill) b.ill = someIlls(1, season)[0];
    if (b.illR) b.illR = someIlls(1, season)[0];
    if (b.ill2) b.ill2 = someIlls(1, season)[0];
  });
}

var lastOmakase = null;
$("p-style").addEventListener("click", function (e){
  var b = e.target.closest("button");
  if (!b || busy) return;
  var d = b.dataset;
  if (d.mood){
    pushHistory();
    applyMood(MOODS.filter(function (m){ return m.k === d.mood; })[0]);
  } else if (d.level){ pushHistory(); doc.theme.level = d.level; }
  else if (d.pal){ pushHistory(); doc.theme.palette = d.pal; }
  else if (d.season){ pushHistory(); shuffleIlls(d.season); toast("イラストを入れかえました。もう一度押すと、また変わります。"); }
  else if (d.pattern){ pushHistory(); doc.theme.pattern = d.pattern; }
  else if (d.font){ pushHistory(); doc.theme[d.key] = d.font; }
  else if (b.id === "btn-omakase"){
    pushHistory();
    var pool = MOODS.filter(function (m){ return m.k !== lastOmakase && m.k !== "sukkiri"; });
    var m = pool[Math.floor(Math.random() * pool.length)];
    lastOmakase = m.k;
    applyMood(m);
    shuffleIlls(curPal().season || "mix");
    toast("「" + m.name + "」でかざりました。気に入るまで何度でも押せます。");
  } else return;
  render(); saveLocal();
});

[["m-school", "meta.school"], ["m-class", "meta.className"], ["m-issue", "meta.issue"],
 ["m-date", "meta.dateText"], ["m-teacher", "meta.teacher"]].forEach(function (p){
  $(p[0]).addEventListener("input", function (){
    setPath(doc, p[1], this.value);
    clearTimeout(saveTimer); saveTimer = setTimeout(function (){ render(); saveLocal(); }, 450);
  });
});
function syncControls(){
  $("m-school").value = doc.meta.school; $("m-class").value = doc.meta.className;
  $("m-issue").value = doc.meta.issue; $("m-date").value = doc.meta.dateText;
  $("m-teacher").value = doc.meta.teacher;
}

/* ---------------- タブ・表示切り替え ---------------- */
var TABS = [["t-form", "p-form"], ["t-concept", "p-concept"], ["t-revise", "p-revise"], ["t-comment", "p-comment"],
            ["t-layout", "p-layout"], ["t-style", "p-style"]];
TABS.forEach(function (pair){
  $(pair[0]).addEventListener("click", function (){
    TABS.forEach(function (p){
      var on = p[0] === pair[0];
      $(p[0]).setAttribute("aria-selected", on ? "true" : "false");
      $(p[1]).hidden = !on;
    });
  });
});
$("viewswitch").addEventListener("click", function (e){
  var b = e.target.closest("button[data-view]"); if (!b) return;
  document.body.setAttribute("data-view", b.getAttribute("data-view"));
  Array.prototype.forEach.call(this.querySelectorAll("button"), function (x){
    x.setAttribute("aria-pressed", x === b ? "true" : "false");
  });
  setTimeout(fit, 30);
});
$("pageview").addEventListener("click", function (e){
  var b = e.target.closest("button[data-p]"); if (!b) return;
  pageView = b.getAttribute("data-p");
  Array.prototype.forEach.call(this.querySelectorAll("button"), function (x){
    x.setAttribute("aria-pressed", x === b ? "true" : "false");
  });
  applyPageView(); fit();
});
$("themeswitch").addEventListener("click", function (e){
  var b = e.target.closest("button[data-t]"); if (!b) return;
  var t = b.getAttribute("data-t");
  if (t === "system") document.documentElement.removeAttribute("data-theme");
  else document.documentElement.setAttribute("data-theme", t);
  Array.prototype.forEach.call(this.querySelectorAll("button"), function (x){
    x.setAttribute("aria-pressed", x === b ? "true" : "false");
  });
});
$("btn-zoomin").addEventListener("click", function (){ zoom = Math.min(1.6, (zoom || currentFit()) * 1.25); fit(); });
$("btn-zoomout").addEventListener("click", function (){ zoom = Math.max(0.08, (zoom || currentFit()) / 1.25); fit(); });
$("btn-zoomfit").addEventListener("click", function (){ zoom = null; fit(); });

/* ---------------- ヒアリング ---------------- */
function addBub(role, text){
  var b = document.createElement("div");
  b.className = "bub " + (role === "user" ? "me" : role === "sys" ? "sys" : "ai");
  b.textContent = text;
  $("chat").appendChild(b); b.scrollIntoView({block: "nearest"});
  return b;
}
function renderChips(list, onPick){
  var box = $("chips"); box.innerHTML = "";
  (list || []).forEach(function (c){
    var b = document.createElement("button");
    b.type = "button"; b.className = "chip"; b.textContent = c;
    b.addEventListener("click", function (){ onPick(c); });
    box.appendChild(b);
  });
}
function thinkingBub(label){
  var b = document.createElement("div");
  b.className = "bub ai";
  b.innerHTML = '<span class="thinking"><span class="dot"></span><span class="dot"></span><span class="dot"></span><span class="lb"></span></span>';
  b.querySelector(".lb").textContent = label || "考えています";
  $("chat").appendChild(b); b.scrollIntoView({block: "nearest"});
  return b;
}
function aiOpts(){ return {model: $("model").value, effort: $("effort").value}; }

$("btn-send").addEventListener("click", sendTurn);
$("ask").addEventListener("keydown", function (e){
  if ((e.metaKey || e.ctrlKey) && e.key === "Enter"){ e.preventDefault(); sendTurn(); }
});
async function sendTurn(){
  var v = $("ask").value.trim();
  if (!v || busy) return;
  $("ask").value = "";
  addBub("user", v); turns.push({role: "user", content: v});
  renderChips([], function (){}); setBusy(true);
  var tb = thinkingBub();
  try {
    var r = await api("/api/chat", Object.assign({turns: turns.slice(-12)}, aiOpts()));
    tb.remove();
    addBub("ai", r.message); turns.push({role: "assistant", content: r.message});
    if (r.status === "ready") renderChips(["この内容で作る"], function (){ $("btn-make").click(); });
    else renderChips(r.chips || [], function (c){ $("ask").value = c; $("ask").focus(); });
    saveLocal();
  } catch (e){ tb.remove(); addBub("sys", e.message); }
  finally { setBusy(false); }
}

$("btn-make").addEventListener("click", compose);
async function compose(){
  if (busy) return;
  var extra = $("ask").value.trim();
  if (extra){ addBub("user", extra); turns.push({role: "user", content: extra}); $("ask").value = ""; }
  var brief = turns.filter(function (t){ return t.role === "user"; })
                   .map(function (t){ return t.content; }).join("\n");
  if (!brief.trim()){ toast("まず、どんなおたよりにしたいか一言教えてください。"); $("ask").focus(); return; }
  setBusy(true);
  var tb = thinkingBub("紙面を組んでいます（1分ほどかかります）");
  try {
    var d = await api("/api/compose", Object.assign({
      brief: brief, illustrations: illListForPrompt()
    }, aiOpts()));
    tb.remove();
    pushHistory();
    doc = normalize(d);
    render(); saveLocal();
    addBub("ai", "おたよりを組みました。紙の上の文字はクリックで直せます。イラストもクリックで差し替えられます。");
    renderChips(["かざりを選ぶ", "やさしい言葉にして", "本文を短く"], function (c){
      if (c === "かざりを選ぶ"){ $("t-style").click(); return; }
      $("t-revise").click(); $("rev").value = c; $("rev").focus();
    });
    toast("おたよりができました。");
  } catch (e){ tb.remove(); addBub("sys", e.message); }
  finally { setBusy(false); }
}

/* ---------------- 修正 ---------------- */
["もっとやさしい言葉に", "本文をすこし短く", "段組みを変えて", "1ページ目を2段にして",
 "クイズを足して", "行事の予定を増やして", "季節の色あいに変えて", "イラストを季節のものに",
 "題字と副題を作り直して", "表で持ち物をまとめて"].forEach(function (c){
  var b = document.createElement("button");
  b.type = "button"; b.className = "chip"; b.textContent = c;
  b.addEventListener("click", function (){
    var cur = $("rev").value.trim();
    $("rev").value = cur ? (cur + "、" + c) : c; $("rev").focus();
  });
  $("revchips").appendChild(b);
});
$("btn-revise").addEventListener("click", revise);
async function revise(){
  var ins = $("rev").value.trim();
  if (!ins || busy) return;
  setBusy(true); $("revlog").textContent = "直しています…";
  try {
    var d = await api("/api/revise", Object.assign({
      doc: doc, instruction: ins, illustrations: illListForPrompt()
    }, aiOpts()));
    pushHistory();
    doc = normalize(d);
    render(); saveLocal();
    $("revlog").textContent = "直しました：" + ins;
    $("rev").value = "";
    toast("おたよりを直しました。");
  } catch (e){ $("revlog").textContent = ""; toast(e.message); }
  finally { setBusy(false); }
}
$("btn-undo").addEventListener("click", function (){
  if (!history.length) return;
  doc = history.pop();
  this.disabled = history.length === 0;
  render(); saveLocal();
  toast("ひとつ前にもどしました。");
});

/* ---------------- コメント ---------------- */
var CMT_ILL = ["hana", "hoshi", "ashiato", "kotori", "usagi", "kuma", "neko", "onigiri", "ehon"];
$("btn-compose").addEventListener("click", composeComment);
async function composeComment(){
  var memo = $("c-memo").value.trim();
  if (!memo || busy){ if (!memo) toast("まず、子どもの様子をメモで入れてください。"); return; }
  var name = $("c-name").value.trim(), yobi = $("c-yobi").value;
  var called = name ? (name + yobi) : "名前は使わない";
  setBusy(true);
  $("drafts").innerHTML = '<div class="note"><span class="thinking"><span class="dot"></span><span class="dot"></span><span class="dot"></span>文章を考えています</span></div>';
  try {
    var r = await api("/api/comment", Object.assign({
      called: called, memo: memo, tone: $("c-tone").value,
      length: $("c-len").value, count: $("c-count").value
    }, aiOpts()));
    drafts = r.drafts || [];
    renderDrafts(name ? (name + yobi) : "");
  } catch (e){ $("drafts").innerHTML = ""; toast(e.message); }
  finally { setBusy(false); }
}
function findCommentsBlocks(){
  var out = [];
  doc.pages.forEach(function (pg, pi){
    function scan(list, base){
      (list || []).forEach(function (b, i){
        if (b && b.kind === "comments") out.push({block: b, path: base + "." + i});
      });
    }
    scan(pg.top, "pages." + pi + ".top");
    scan(pg.bottom, "pages." + pi + ".bottom");
    (pg.columns || []).forEach(function (c, ci){ scan(c.blocks, "pages." + pi + ".columns." + ci + ".blocks"); });
  });
  return out;
}
function renderDrafts(label){
  var box = $("drafts");
  if (!drafts.length){ box.innerHTML = '<div class="empty">案が出ませんでした。メモを変えてお試しください。</div>'; return; }
  box.innerHTML = "";
  drafts.forEach(function (t, i){
    var d = document.createElement("div");
    d.className = "draft";
    d.innerHTML = '<div class="tx"></div><div class="bar"><span class="n">案 ' + (i + 1) + " ・ " + t.length + '字</span>' +
      '<span style="display:flex;gap:6px"><button class="btn sm" type="button" data-copy>コピー</button>' +
      '<button class="btn sm primary" type="button" data-use>おたよりに載せる</button></span></div>';
    d.querySelector(".tx").textContent = t;
    d.querySelector("[data-use]").addEventListener("click", function (){
      var targets = findCommentsBlocks();
      if (!targets.length){ toast("「こどもたちのすがた」のブロックが紙面にありません。レイアウトのタブから足してください。"); return; }
      pushHistory();
      var tgt = targets[targets.length - 1].block;
      if (!Array.isArray(tgt.items)) tgt.items = [];
      tgt.items.push({ill: CMT_ILL[tgt.items.length % CMT_ILL.length], name: label || "なまえ", text: t});
      render(); saveLocal();
      toast("紙面に載せました。");
    });
    d.querySelector("[data-copy]").addEventListener("click", function (){
      var btn = this;
      navigator.clipboard.writeText(t).then(
        function (){ btn.textContent = "コピーしました"; setTimeout(function (){ btn.textContent = "コピー"; }, 1600); },
        function (){ toast("コピーできませんでした。"); });
    });
    box.appendChild(d);
  });
}

/* ---------------- 控えの保存・読み込み ---------------- */
$("btn-save").addEventListener("click", async function (){
  var name = $("save-name").value.trim();
  if (!name){ toast("保存する名前を入れてください。"); return; }
  try {
    var r = await api("/api/save", {name: name, doc: doc});
    fillSaved(r.list);
    toast("data/" + r.saved + ".json に保存しました。");
  } catch (e){ toast(e.message); }
});
$("btn-open").addEventListener("click", async function (){
  var name = $("saved-list").value;
  if (!name){ toast("読み込む控えを選んでください。"); return; }
  try {
    var r = await api("/api/load", {name: name});
    pushHistory();
    doc = normalize(r.doc);
    render(); saveLocal();
    toast(name + " を読み込みました。");
  } catch (e){ toast(e.message); }
});
function fillSaved(list){
  $("saved-list").innerHTML = '<option value="">（控えを選ぶ）</option>' +
    (list || []).map(function (n){ return '<option value="' + esc(n) + '">' + esc(n) + "</option>"; }).join("");
}

/* ---------------- 出力 ---------------- */
$("btn-print").addEventListener("click", function (){
  var prev = pageView;
  pageView = "both"; applyPageView();
  setTimeout(function (){
    window.print();
    pageView = prev; applyPageView(); fit();
  }, 60);
});

$("btn-pdf").addEventListener("click", exportImagePdf);
function raf2(){
  return new Promise(function (r){
    requestAnimationFrame(function (){ requestAnimationFrame(function (){ setTimeout(r, 40); }); });
  });
}
async function exportImagePdf(){
  if (busy) return;
  if (!window.html2canvas || !window.jspdf){ toast("PDFの部品が読み込めていません。ネットにつながっているか確認してください。"); return; }
  var ov = $("overlay"), bar = $("o-bar");
  var prevView = pageView, prevZoom = zoom;
  setBusy(true); ov.hidden = false; bar.style.width = "4%";
  $("illpicker").hidden = true; $("blockpicker").hidden = true; $("decopicker").hidden = true;
  try {
    pageView = "both"; applyPageView(); zoom = 1; fit();
    if (document.fonts && document.fonts.ready) await document.fonts.ready;
    await raf2();
    var jsPDF = window.jspdf.jsPDF;
    var pdf = new jsPDF({orientation: "landscape", unit: "mm", format: "a3", compress: true});
    var sheets = allSheets();
    for (var i = 0; i < sheets.length; i++){
      $("o-text").textContent = (i + 1) + "ページ目を描いています…";
      bar.style.width = (10 + i * (80 / sheets.length)) + "%";
      await raf2();
      var canvas = await html2canvas(sheets[i], {
        scale: 2.4, backgroundColor: "#ffffff",
        width: PAGE_W, height: PAGE_H, windowWidth: PAGE_W, windowHeight: PAGE_H,
        scrollX: 0, scrollY: 0, useCORS: true, logging: false,
        ignoreElements: function (n){ return n.nodeType === 1 && n.hasAttribute && n.hasAttribute("data-ui"); },
        onclone: function (cdoc){ cdoc.documentElement.classList.add("capturing"); }
      });
      if (i > 0) pdf.addPage("a3", "landscape");
      pdf.addImage(canvas.toDataURL("image/jpeg", 0.95), "JPEG", 0, 0, 420, 297, undefined, "FAST");
      canvas.width = canvas.height = 0;
    }
    bar.style.width = "96%";
    pdf.save(fileName());
    toast("保存しました：" + fileName());
  } catch (e){
    toast("PDFを作れませんでした。" + (e && e.message ? "（" + e.message + "）" : ""));
    if (window.console) console.error(e);
  } finally {
    pageView = prevView; zoom = prevZoom; applyPageView(); fit();
    ov.hidden = true; bar.style.width = "0%"; setBusy(false);
  }
}
function fileName(){
  var a = (doc.meta.issue || "").replace(/[\\/:*?"<>|]/g, "").trim();
  var b = (doc.meta.className || "").replace(/[\\/:*?"<>|]/g, "").trim();
  var parts = ["おたより"]; if (a) parts.push(a); if (b) parts.push(b);
  return parts.join("_") + ".pdf";
}

$("btn-reset").addEventListener("click", function (){
  var b = this;
  if (b.dataset.armed !== "1"){
    b.dataset.armed = "1"; b.textContent = "本当に消す？";
    setTimeout(function (){ b.dataset.armed = ""; b.textContent = "はじめから"; }, 4000);
    return;
  }
  b.dataset.armed = ""; b.textContent = "はじめから";
  pushHistory();
  doc = starterDoc(); turns = []; drafts = [];
  $("chat").innerHTML = ""; $("drafts").innerHTML = ""; $("rev").value = ""; $("revlog").textContent = "";
  bootChat(); render(); saveLocal();
  toast("見本の状態にもどしました。");
});

/* ---------------- 起動 ---------------- */
function bootChat(){
  addBub("ai", "どんなおたよりを作りましょうか。園名・クラス・発行月・今月の行事・クラスの様子など、思いつくままに教えてください。");
  renderChips(["5月号／ひまわり組／遠足", "6月号／うさぎ組／梅雨あそび", "クラスの様子から相談したい"], function (c){
    $("ask").value = c.replace(/／/g, "、"); $("ask").focus();
  });
}

/* フォーム連携（form.js）から使うつなぎ口 */
window.OtayoriApp = {
  getDoc: function (){ return doc; },
  setDoc: function (d){ pushHistory(); doc = normalize(d); render(); saveLocal(); },
  commit: function (){ render(); saveLocal(); },
  pushHistory: pushHistory, toast: toast, api: api,
  someIlls: someIlls, emptyPage: emptyPage,
  config: function (){ return config; }
};

/* ---------------- AIにつなぐ（APIキー） ----------------
   キーはサーバが .env に保存する。画面には末尾4文字しか返ってこない。 */
var aiReady = false;

function applyConfig(c){
  config = c;
  aiReady = !!c.ready;
  var conn = $("conn"), bn = $("keybanner");
  if (!c.ready){
    conn.innerHTML = '<span class="dot-ng"></span> AIにつながっていません';
    bn.hidden = false;
  } else if (!c.hasKey){
    conn.innerHTML = '<span class="dot-ng"></span> AIにつながっていません';
    bn.hidden = false;
  } else {
    conn.innerHTML = '<span class="dot-ok"></span> AIにつながっています';
    bn.hidden = true;
  }
  setBusy(busy);

  var st = $("key-status");
  if (c.keySource === "screen"){
    st.innerHTML = '<span class="dot-ok"></span> この画面で設定したキーでつながっています（' + esc(c.keyHint) + "）";
  } else if (c.keySource === "env"){
    st.innerHTML = '<span class="dot-ok"></span> パソコンの環境変数のキーを使っています。ここで設定すると、こちらが優先されます。';
  } else if (c.keySource === "other"){
    st.innerHTML = '<span class="dot-ok"></span> ログイン済みの資格情報でつながっています。';
  } else {
    st.innerHTML = '<span class="dot-ng"></span> まだキーが設定されていません。';
  }
  $("btn-key-clear").hidden = c.keySource !== "screen";
}

function openKeyDialog(){
  $("key-in").value = ""; $("key-in").type = "password"; $("btn-key-show").textContent = "表示";
  $("key-err").textContent = "";
  $("keydlg").hidden = false;
  setTimeout(function (){ $("key-in").focus(); }, 30);
}
function closeKeyDialog(){ $("keydlg").hidden = true; }

$("conn").addEventListener("click", openKeyDialog);
$("btn-keybanner").addEventListener("click", openKeyDialog);
$("btn-key-open").addEventListener("click", openKeyDialog);
$("btn-key-close").addEventListener("click", closeKeyDialog);
$("keydlg").addEventListener("click", function (e){ if (e.target === this) closeKeyDialog(); });
document.addEventListener("keydown", function (e){ if (e.key === "Escape" && !$("keydlg").hidden) closeKeyDialog(); });
$("btn-key-show").addEventListener("click", function (){
  var show = $("key-in").type === "password";
  $("key-in").type = show ? "text" : "password";
  this.textContent = show ? "かくす" : "表示";
});
$("key-in").addEventListener("keydown", function (e){ if (e.key === "Enter"){ e.preventDefault(); $("btn-key-save").click(); } });

$("btn-key-save").addEventListener("click", async function (){
  var key = $("key-in").value.trim(), btn = this;
  if (!key){ $("key-err").textContent = "キーを貼りつけてください。"; return; }
  btn.disabled = true; btn.textContent = "たしかめています…"; $("key-err").textContent = "";
  try {
    applyConfig(await api("/api/key", {key: key}));
    $("key-in").value = "";
    closeKeyDialog();
    toast("AIにつながりました。");
  } catch (e){
    $("key-err").textContent = e.message;
  } finally {
    btn.disabled = false; btn.textContent = "つなぐ";
  }
});
$("btn-key-clear").addEventListener("click", async function (){
  var b = this;
  if (b.dataset.armed !== "1"){
    b.dataset.armed = "1"; b.textContent = "本当に消す？";
    setTimeout(function (){ b.dataset.armed = ""; b.textContent = "キーを消す"; }, 4000);
    return;
  }
  b.dataset.armed = ""; b.textContent = "キーを消す";
  try { applyConfig(await api("/api/key/clear", {})); toast("保存したキーを消しました。"); }
  catch (e){ $("key-err").textContent = e.message; }
});

async function boot(){
  /* 自作の絵を先に読む。下書きに使われていても、正しく描けるように */
  try { registerMyIllust((await api("/api/illust/list", {})).items); } catch (e){}
  if (!loadLocal()) doc = starterDoc();
  buildIllPicker(); buildBlockPicker(); renderStickGrid(); render();
  if (document.fonts && document.fonts.ready) document.fonts.ready.then(autofit);
  if (turns.length) turns.forEach(function (t){ addBub(t.role === "user" ? "user" : "ai", t.content); });
  else bootChat();

  try {
    var c = await (await fetch("/api/config")).json();
    $("model").innerHTML = c.models.map(function (m){
      return '<option value="' + m.id + '"' + (m.id === c.defaultModel ? " selected" : "") + ">" + esc(m.label) + "</option>";
    }).join("");
    $("effort").innerHTML = c.efforts.map(function (e){
      return '<option value="' + e + '"' + (e === "high" ? " selected" : "") + ">" + e + "</option>";
    }).join("");
    fillSaved(c.saved);
    applyConfig(c);
    if (window.OtayoriForm) window.OtayoriForm.onConfig(c);
    if (c.keySource === "none" && !(c.form && c.form.configured)) openKeyDialog();
  } catch (e){
    $("conn").innerHTML = '<span class="dot-ng"></span> サーバに接続できません';
  }
}
boot();

})();
