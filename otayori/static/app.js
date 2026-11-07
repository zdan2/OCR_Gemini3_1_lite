/* おたより工房 ローカル版 — 画面の組み立てとサーバとのやりとり */
(function () {
"use strict";

var O = window.Otayori;
var PAGE_W = O.PAGE_W, PAGE_H = O.PAGE_H;
var LS_KEY = "otayori-local.v1";

var doc = null, history = [], drafts = [], config = null;
var busy = false, zoom = null, pageView = "both", turns = [];
var pickerPath = null, blockAddPath = null, photoPath = null;

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
    pg.deco.corners = pg.deco.corners.slice(0, 4).map(function (k){ return ILL[k] ? k : "hana"; });
    pg.deco.edge = pg.deco.edge.slice(0, 10).map(function (k){ return ILL[k] ? k : "hoshi"; });
    ["top", "bottom"].forEach(function (s){ if (!Array.isArray(pg[s])) pg[s] = []; });
    if (!Array.isArray(pg.columns)) pg.columns = [];
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
function saveLocal(){
  try { localStorage.setItem(LS_KEY, JSON.stringify({doc: doc, turns: turns})); } catch (e) {}
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
  renderStructure();
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
  ["btn-send", "btn-make", "btn-revise", "btn-compose", "btn-pdf", "btn-print"].forEach(function (id){
    var el = $(id); if (el) el.disabled = b;
  });
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
  document.execCommand("insertText", false, t);
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
  if (act === "photo-pick"){ photoPath = path; $("photo-in").click(); return; }

  pushHistory();
  if (act === "blk-up" || act === "blk-down"){
    var s = splitPath(path);
    var to = s.index + (act === "blk-up" ? -1 : 1);
    if (Array.isArray(s.list) && to >= 0 && to < s.list.length){
      var it = s.list.splice(s.index, 1)[0];
      s.list.splice(to, 0, it);
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
function buildIllPicker(){
  var groups = {}, order = [];
  ILL_KEYS.forEach(function (k){
    var g = ILL[k][0];
    if (!groups[g]){ groups[g] = []; order.push(g); }
    groups[g].push(k);
  });
  var h = "";
  order.forEach(function (g){
    h += "<h5>" + esc(g) + "</h5><div class='illgrid'>";
    groups[g].forEach(function (k){
      h += '<button type="button" data-ill="' + k + '" title="' + esc(ILL[k][1]) + '">' + illSvg(k) + "</button>";
    });
    h += "</div>";
  });
  $("illpicker").innerHTML = h;
}
function place(box, el){
  box.hidden = false;
  var r = el.getBoundingClientRect(), w = box.offsetWidth, h = box.offsetHeight;
  var x = Math.min(Math.max(8, r.left + r.width / 2 - w / 2), window.innerWidth - w - 8);
  var y = r.bottom + 8;
  if (y + h > window.innerHeight - 8) y = Math.max(8, r.top - h - 8);
  box.style.left = x + "px"; box.style.top = y + "px";
}
function openIllPicker(el){ pickerPath = el.getAttribute("data-slot"); place($("illpicker"), el); }
$("illpicker").addEventListener("click", function (e){
  var b = e.target.closest("button[data-ill]");
  if (!b || !pickerPath) return;
  pushHistory();
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
  [["illpicker", "[data-slot]"], ["blockpicker", "[data-act='blk-add']"]].forEach(function (pair){
    var box = $(pair[0]);
    if (box.hidden || box.contains(e.target)) return;
    if (e.target.closest && e.target.closest(pair[1])) return;
    box.hidden = true;
  });
}, true);
document.addEventListener("keydown", function (e){
  if (e.key === "Escape"){ $("illpicker").hidden = true; $("blockpicker").hidden = true; }
});

/* ---------------- 写真 ---------------- */
$("photo-in").addEventListener("change", function (){
  var files = Array.prototype.slice.call(this.files || []), self = this;
  if (!files.length || !photoPath) { self.value = ""; return; }
  var list = getPath(doc, photoPath);
  if (!Array.isArray(list)) { self.value = ""; return; }
  pushHistory();
  var left = files.length;
  files.slice(0, 4).forEach(function (f){
    var r = new FileReader();
    r.onload = function (){
      list.push({src: r.result, caption: "写真のせつめい"});
      if (--left <= 0){ render(); saveLocal(); self.value = ""; photoPath = null; }
    };
    r.onerror = function (){ if (--left <= 0){ render(); self.value = ""; photoPath = null; } };
    r.readAsDataURL(f);
  });
});

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

/* ---------------- 体裁 ---------------- */
function renderPalettes(){
  $("palettes").innerHTML = Object.keys(PALETTES).map(function (k){
    var p = PALETTES[k];
    return '<button class="sw" type="button" data-pal="' + k + '" aria-pressed="' + (doc.theme.palette === k) + '">' +
      '<span class="bars"><i style="background:' + p.accent + '"></i><i style="background:' + p.accent2 + '"></i>' +
      '<i style="background:' + p.accent3 + '"></i><i style="background:' + p.tint2 + '"></i></span>' +
      "<small>" + p.name + "</small></button>";
  }).join("");
}
$("palettes").addEventListener("click", function (e){
  var b = e.target.closest("button[data-pal]");
  if (!b) return;
  doc.theme.palette = b.getAttribute("data-pal");
  renderPalettes(); render(); saveLocal();
});
[["tfont", "titleFont"], ["hfont", "headingFont"], ["pattern", "pattern"], ["level", "level"]].forEach(function (p){
  $(p[0]).addEventListener("change", function (){ doc.theme[p[1]] = this.value; render(); saveLocal(); });
});
[["m-school", "meta.school"], ["m-class", "meta.className"], ["m-issue", "meta.issue"],
 ["m-date", "meta.dateText"], ["m-teacher", "meta.teacher"]].forEach(function (p){
  $(p[0]).addEventListener("input", function (){
    setPath(doc, p[1], this.value);
    clearTimeout(saveTimer); saveTimer = setTimeout(function (){ render(); saveLocal(); }, 450);
  });
});
function syncControls(){
  $("tfont").value = doc.theme.titleFont;
  $("hfont").value = doc.theme.headingFont;
  $("pattern").value = doc.theme.pattern;
  $("level").value = doc.theme.level;
  $("m-school").value = doc.meta.school; $("m-class").value = doc.meta.className;
  $("m-issue").value = doc.meta.issue; $("m-date").value = doc.meta.dateText;
  $("m-teacher").value = doc.meta.teacher;
}
$("btn-shuffle").addEventListener("click", function (){
  pushHistory();
  var season = $("season-pick").value;
  doc.pages.forEach(function (pg){
    pg.deco.corners = someIlls(4, season);
    pg.deco.edge = someIlls(10, season);
    function walk(list){
      (list || []).forEach(function (b){
        if (!b) return;
        if (b.kind === "illband") b.items = someIlls((b.items || []).length || 7, season);
        else if (b.ill) b.ill = someIlls(1, season)[0];
        if (b.illR) b.illR = someIlls(1, season)[0];
        if (b.ill2) b.ill2 = someIlls(1, season)[0];
      });
    }
    walk(pg.top); walk(pg.bottom);
    (pg.columns || []).forEach(function (c){ walk(c.blocks); });
  });
  render(); saveLocal();
  toast("かざりを入れかえました。");
});

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
    renderPalettes(); render(); saveLocal();
    addBub("ai", "おたよりを組みました。紙の上の文字はクリックで直せます。イラストもクリックで差し替えられます。");
    renderChips(["やさしい言葉にして", "段組みを変えて", "本文を短く"], function (c){
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
    renderPalettes(); render(); saveLocal();
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
  renderPalettes(); render(); saveLocal();
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
    renderPalettes(); render(); saveLocal();
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
  $("illpicker").hidden = true; $("blockpicker").hidden = true;
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
  bootChat(); renderPalettes(); render(); saveLocal();
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
  setDoc: function (d){ pushHistory(); doc = normalize(d); renderPalettes(); render(); saveLocal(); },
  commit: function (){ render(); saveLocal(); },
  pushHistory: pushHistory, toast: toast, api: api,
  someIlls: someIlls, emptyPage: emptyPage,
  config: function (){ return config; }
};

function warnBanner(text){
  var bn = document.createElement("div");
  bn.className = "banner warnish";
  bn.textContent = text;
  $("p-concept").insertBefore(bn, $("p-concept").firstChild);
}

async function boot(){
  if (!loadLocal()) doc = starterDoc();
  buildIllPicker(); buildBlockPicker(); renderPalettes(); render();
  if (document.fonts && document.fonts.ready) document.fonts.ready.then(autofit);
  if (turns.length) turns.forEach(function (t){ addBub(t.role === "user" ? "user" : "ai", t.content); });
  else bootChat();

  try {
    config = await (await fetch("/api/config")).json();
    $("model").innerHTML = config.models.map(function (m){
      return '<option value="' + m.id + '"' + (m.id === config.defaultModel ? " selected" : "") + ">" + esc(m.label) + "</option>";
    }).join("");
    $("effort").innerHTML = config.efforts.map(function (e){
      return '<option value="' + e + '"' + (e === "high" ? " selected" : "") + ">" + e + "</option>";
    }).join("");
    fillSaved(config.saved);
    if (window.OtayoriForm) window.OtayoriForm.onConfig(config);
    if (!config.ready){
      $("conn").innerHTML = '<span class="dot-ng"></span> Claude を使えません';
      warnBanner(config.message + "（直したらこのページを再読み込みしてください。文字とイラストの編集、段組みの変更、印刷は今のままでもできます。）");
      ["btn-send", "btn-make", "btn-revise", "btn-compose"].forEach(function (id){ $(id).disabled = true; });
    } else if (!config.hasKey){
      $("conn").innerHTML = '<span class="dot-ng"></span> APIキー未確認';
      warnBanner(config.message);
    } else {
      $("conn").innerHTML = '<span class="dot-ok"></span> Claude につながっています';
    }
  } catch (e){
    $("conn").innerHTML = '<span class="dot-ng"></span> サーバに接続できません';
  }
}
boot();

})();
