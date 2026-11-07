/* おたより工房 — Googleフォーム「光の原だより 原稿提出」との連携

   区分ごとの最新の提出を取り込んで、紙面のブロックに流し込む。
   流し込んだブロックは src（区分）と srcTime（どの提出を入れたか）を覚えていて、
   それより新しい提出が来たときだけ中身を差し替える。
   イラスト・囲み・見出し・段組みと、提出後に紙の上でした手直しは、次の提出まで残る。 */

(function () {
"use strict";

var A = window.OtayoriApp;
var esc = window.Otayori.esc;
var $ = function (id){ return document.getElementById(id); };

var EN = [
  {k: "園長挨拶",     limit: 540, heading: "園長より",           ill: "kodomo"},
  {k: "来月の予定",   limit: 280, heading: "来月の予定",         ill: "hoshi"},
  {k: "園からのお願い", limit: 220, heading: "園からのおねがい",   ill: "ashiato"},
  {k: "保健から",     limit: 560, heading: "ほけんだより",       ill: "usagi"},
  {k: "給食室から",   limit: 560, heading: "きゅうしょくしつより", ill: "onigiri"}
];
var CLASSES = [
  {k: "ひよこ", ill: "hiyoko"}, {k: "りす", ill: "risu"},   {k: "ばんび", ill: "banbi"},
  {k: "ほし",   ill: "hoshi"},  {k: "つき", ill: "tsuki"},  {k: "たいよう", ill: "taiyou"}
];
var AIM_LIMIT = 330;
var PART_ORDER = ["ねらい", "保育", "食事", "お知らせ", "お願い"];
var KEEP = ["heading", "ill", "box", "tape", "tilt", "bg"];   // 差し替えても残す見た目
var EMPTY = "（まだ提出されていません）";
var LS = "otayori-form.v1";

var latest = null;            // {fetchedAt, form, sections: {区分: {time, fields}}}
var timer = null;
var prefs = {auto: 0, apply: true};
var configured = false;

function enOf(k){ for (var i = 0; i < EN.length; i++) if (EN[i].k === k) return EN[i]; return null; }
function classOf(k){ for (var i = 0; i < CLASSES.length; i++) if (CLASSES[i].k === k) return i; return -1; }
function chars(s){ return String(s || "").replace(/\s/g, "").length; }
function firstValue(f){ for (var k in f) if (Object.prototype.hasOwnProperty.call(f, k)) return f[k]; return ""; }
function shortTime(t){
  var m = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/.exec(String(t || ""));
  return m ? (+m[2]) + "/" + (+m[3]) + " " + m[4] + ":" + m[5] : String(t || "");
}

function loadPrefs(){
  try { var v = JSON.parse(localStorage.getItem(LS) || "{}"); prefs.auto = +v.auto || 0; prefs.apply = v.apply !== false; }
  catch (e) {}
}
function savePrefs(){ try { localStorage.setItem(LS, JSON.stringify(prefs)); } catch (e) {} }

/* ---------------- 本文の読み取り ---------------- */

var SCHEDULE_LINE = /^\s*[・●○◎\-－]?\s*(?:(\d{1,2})\s*[\/／月]\s*)?(\d{1,2})\s*日?\s*(?:[（(]\s*([^）)]{1,3})\s*[）)])?\s*[:：]?\s*(.+)$/;

/** 「11日(月) 山の日」のような行が多ければ予定表に。日付の無い行は前の行の続きにする。 */
function parseSchedule(text){
  var lines = text.split("\n").map(function (l){ return l.trim(); }).filter(Boolean);
  if (lines.length < 2) return null;
  var items = [], hits = 0;
  lines.forEach(function (line){
    var m = SCHEDULE_LINE.exec(line);
    if (m && +m[2] >= 1 && +m[2] <= 31){
      hits++;
      var date = (m[1] ? (+m[1]) + "/" + (+m[2]) : (+m[2]) + "日") + (m[3] ? "（" + m[3] + "）" : "");
      items.push({date: date, label: m[4].trim()});
    } else if (items.length && !/^※/.test(line)){
      items[items.length - 1].label += "\n" + line;
    } else {
      items.push({date: /^※/.test(line) ? "※" : "・", label: line.replace(/^※\s*/, "")});
    }
  });
  return hits >= Math.ceil(lines.length * 0.5) ? items : null;
}

/** 行頭が「・」などの箇条書きか、どの行も「。」で終わっていれば、箇条書きにする。
 *  15行に収めるために途中で改行した文章を、ばらばらにしないため。 */
function parseList(text){
  var lines = text.split("\n").map(function (l){ return l.trim(); }).filter(Boolean);
  if (lines.length < 2) return null;
  var bullets = lines.filter(function (l){ return /^[・●○◎\-－*＊]/.test(l); }).length;
  var sentences = lines.filter(function (l){ return /[。！？!?）)]$/.test(l); }).length;
  if (bullets < Math.ceil(lines.length / 2) && sentences < lines.length) return null;
  return lines.map(function (l){ return l.replace(/^[・●○◎\-－*＊]\s*/, ""); });
}

function rank(k){ var i = PART_ORDER.indexOf(k); return i < 0 ? 99 : i; }

/** 提出1件からブロックの中身（見た目以外）を作る。 */
function contentFor(kubun, sec){
  var f = (sec && sec.fields) || {};
  if (classOf(kubun) >= 0){
    var parts = Object.keys(f).sort(function (a, b){ return rank(a) - rank(b); })
                    .map(function (k){ return {k: k, v: f[k]}; });
    return {kind: "section", parts: parts.length ? parts : [{k: "ねらい", v: EMPTY}]};
  }
  var body = f["本文"] || firstValue(f) || "";
  if (!body) return {kind: "text", body: EMPTY};
  if (kubun === "来月の予定"){ var sch = parseSchedule(body); if (sch) return {kind: "schedule", items: sch}; }
  if (kubun === "園からのお願い"){ var li = parseList(body); if (li) return {kind: "list", items: li}; }
  return {kind: "text", body: body};
}

function lookFor(kubun){
  var en = enOf(kubun);
  if (en) return {heading: en.heading, ill: en.ill};
  var ci = classOf(kubun);
  return {heading: kubun + "ぐみ", ill: CLASSES[ci].ill, bg: ci};
}

/** 区分に結びついたブロック。prev があれば、その見た目を引き継ぐ。 */
function boundBlock(kubun, sec, prev){
  var look = {};
  var from = prev || lookFor(kubun);
  KEEP.forEach(function (k){ if (from[k] !== undefined) look[k] = from[k]; });
  var b = Object.assign(look, contentFor(kubun, sec));
  b.src = kubun;
  b.srcTime = sec ? sec.time : "";
  return b;
}

/* ---------------- 紙面との対応 ---------------- */

function eachBound(doc, fn){
  (doc.pages || []).forEach(function (pg){
    function walk(list){ (list || []).forEach(function (b, i){ if (b && b.src) fn(b, list, i); }); }
    walk(pg.top); walk(pg.bottom);
    (pg.columns || []).forEach(function (c){ walk(c.blocks); });
  });
}
function blocksBySrc(doc){
  var map = {};
  eachBound(doc, function (b){ map[b.src] = b; });
  return map;
}

/** 新しい提出のあるブロックだけ差し替える。戻り値は差し替えた区分の一覧。 */
function applyToDoc(){
  var doc = A.getDoc();
  if (!latest || !doc) return [];
  var changed = [];
  eachBound(doc, function (b, list, i){
    var sec = latest.sections[b.src];
    if (sec && (!b.srcTime || sec.time > b.srcTime)){
      list[i] = boundBlock(b.src, sec, b);
      changed.push(b.src);
    }
  });
  if (changed.length) A.commit();
  return changed;
}

function issueOf(now){
  var y = now.getFullYear(), m = now.getMonth() + 1;
  if (now.getDate() >= 15){ m++; if (m > 12){ m = 1; y++; } }   // 月の後半に作るのは翌月号
  return {y: y, m: m};
}
function seasonOf(m){
  if (m >= 3 && m <= 5) return "haru";
  if (m === 6) return "tsuyu";
  if (m === 7 || m === 8) return "natsu";
  if (m >= 9 && m <= 11) return "aki";
  return "fuyu";
}

/** 光の原だよりの紙面を、いま取り込んである提出から組む。 */
function buildDoc(){
  var iss = issueOf(new Date()), season = seasonOf(iss.m);
  var S = (latest && latest.sections) || {};
  function bound(k){ return boundBlock(k, S[k], null); }
  var ills = A.someIlls(4, season);
  var p1 = A.emptyPage(season), p2 = A.emptyPage(season);

  p1.top = [{kind: "title", title: "光の原だより", sub: iss.m + "月の園のようすをお届けします",
             ill: ills[0], illR: ills[1]}];
  // 上限の字数で釣り合うように振り分ける：540+220 ／ 560+予定 ／ 560
  p1.columns = [
    {w: 1.05, blocks: [bound("園長挨拶"), bound("園からのお願い")]},
    {w: 1.22, blocks: [bound("保健から"), bound("来月の予定")]},
    {w: 0.83, blocks: [bound("給食室から")]}
  ];
  p1.bottom = [{kind: "illband", items: A.someIlls(7, season)}];

  p2.top = [{kind: "head", text: "クラスだより", ill: ills[2], ill2: ills[3]}];
  p2.columns = [0, 1, 2].map(function (c){
    return {w: 1, blocks: [bound(CLASSES[c * 2].k), bound(CLASSES[c * 2 + 1].k)]};
  });

  return {
    meta: {school: "光の原保育園", className: "", issue: iss.y + "年" + iss.m + "月号",
           dateText: iss.y + "年" + iss.m + "月1日発行", teacher: ""},
    theme: {palette: {haru: "sakura", tsuyu: "ajisai", natsu: "himawari", aki: "momiji", fuyu: "yuki"}[season],
            titleFont: "pop", headingFont: "maru", pattern: "dots", level: "mori"},
    pages: [p1, p2]
  };
}

/* ---------------- 提出状況 ---------------- */

function statusPills(kubun, sec, block){
  var out = [];
  if (!sec){
    out.push('<span class="pill no">未提出</span>');
  } else {
    var ci = classOf(kubun), en = enOf(kubun);
    var n = ci >= 0 ? chars(sec.fields["ねらい"]) : chars(sec.fields["本文"] || firstValue(sec.fields));
    var lim = ci >= 0 ? AIM_LIMIT : en.limit;
    if (n > lim) out.push('<span class="pill over">' + (n - lim) + "字オーバー</span>");
    var t = new Date(sec.time);
    if (!isNaN(t) && (Date.now() - t.getTime()) > 35 * 864e5) out.push('<span class="pill old">前の号かも</span>');
  }
  if (!block) out.push('<span class="pill no">紙面になし</span>');
  else if (sec && (!block.srcTime || sec.time > block.srcTime)) out.push('<span class="pill new">未反映</span>');
  else if (sec) out.push('<span class="pill ok">反映済み</span>');
  return out.join(" ");
}

function renderStatus(){
  var S = (latest && latest.sections) || {};
  var have = blocksBySrc(A.getDoc() || {pages: []});
  function row(k, limitText){
    var sec = S[k];
    var n = "";
    if (sec){
      n = classOf(k) >= 0
        ? "ねらい " + chars(sec.fields["ねらい"]) + "／" + AIM_LIMIT
        : chars(sec.fields["本文"] || firstValue(sec.fields)) + "／" + limitText;
    }
    return "<tr><td>" + esc(k) + '</td><td class="n">' + (sec ? esc(shortTime(sec.time)) : "—") +
           '</td><td class="n">' + n + "</td><td>" + statusPills(k, sec, have[k]) + "</td></tr>";
  }
  var h = "<thead><tr><th>区分</th><th>提出</th><th>字数</th><th>状態</th></tr></thead><tbody>";
  h += '<tr class="grp"><td colspan="4">園から</td></tr>';
  EN.forEach(function (e){ h += row(e.k, e.limit); });
  h += '<tr class="grp"><td colspan="4">クラス</td></tr>';
  CLASSES.forEach(function (c){ h += row(c.k, AIM_LIMIT); });
  $("f-table").innerHTML = h + "</tbody>";

  var got = Object.keys(S).length;
  $("f-fetched").textContent = latest
    ? "取り込み " + shortTime(latest.fetchedAt) + "　提出あり " + got + "／" + (EN.length + CLASSES.length) + " 区分"
    : (configured ? "まだ取り込んでいません。" : "");
}

/* ---------------- 取り込み ---------------- */

var fetching = false;
async function fetchLatest(silent){
  if (fetching) return;
  if (!configured){ if (!silent) A.toast("先に取り込み先の URL を設定してください。"); return; }
  fetching = true;
  $("f-fetch").disabled = true;
  $("f-fetch").textContent = "取り込んでいます…";
  try {
    latest = await A.api("/api/form/fetch", {});
    var changed = prefs.apply ? applyToDoc() : [];
    renderStatus();
    if (changed.length) A.toast("新しい提出を紙面に入れました：" + changed.join("、"));
    else if (!silent) A.toast("最新を取り込みました。紙面に入れる新しい提出はありませんでした。");
  } catch (e){
    if (!silent) A.toast(e.message);
    $("f-fetched").textContent = "取り込めませんでした：" + e.message;
  } finally {
    fetching = false;
    $("f-fetch").disabled = false;
    $("f-fetch").textContent = "最新を取り込む";
  }
}

function setTimer(){
  clearInterval(timer); timer = null;
  if (prefs.auto > 0 && configured) timer = setInterval(function (){ fetchLatest(true); }, prefs.auto * 60000);
}

function showConfig(form){
  configured = !!(form && form.configured);
  $("f-current").textContent = configured ? "設定済み：" + form.url : "まだ設定されていません。";
  setTimer();
  renderStatus();
}

/* ---------------- 画面 ---------------- */

$("f-save").addEventListener("click", async function (){
  try {
    var r = await A.api("/api/form/config", {url: $("f-url").value.trim()});
    $("f-url").value = "";
    showConfig(r);
    A.toast(r.configured ? "取り込み先を設定しました。" : "取り込み先を外しました。");
    if (r.configured) fetchLatest(false);
  } catch (e){ A.toast(e.message); }
});
$("f-fetch").addEventListener("click", function (){ fetchLatest(false); });
$("f-build").addEventListener("click", function (){
  var b = this;
  if (b.dataset.armed !== "1"){
    b.dataset.armed = "1"; b.textContent = "いまの紙面を置きかえます。もう一度押す";
    setTimeout(function (){ b.dataset.armed = ""; b.textContent = "この内容で紙面を作る"; }, 4500);
    return;
  }
  b.dataset.armed = ""; b.textContent = "この内容で紙面を作る";
  A.setDoc(buildDoc());
  renderStatus();
  A.toast(latest ? "光の原だよりを組みました。「ひとつ戻す」で前の紙面にもどせます。"
                 : "まだ取り込んでいないので、空の枠で組みました。");
});
$("f-apply").addEventListener("change", function (){
  prefs.apply = this.checked; savePrefs();
  if (prefs.apply){ var c = applyToDoc(); renderStatus(); if (c.length) A.toast("紙面に入れました：" + c.join("、")); }
});
$("f-auto").addEventListener("change", function (){ prefs.auto = +this.value || 0; savePrefs(); setTimer(); });

$("t-form").addEventListener("click", renderStatus);

loadPrefs();
$("f-apply").checked = prefs.apply;
$("f-auto").value = String(prefs.auto);
renderStatus();

window.OtayoriForm = {
  onConfig: function (cfg){
    showConfig(cfg && cfg.form);
    if (configured) fetchLatest(true);
  },
  /* テストや他の画面から使う */
  _parseSchedule: parseSchedule, _parseList: parseList, _contentFor: contentFor
};

/* 設定の取得が、このファイルより先に終わっていた場合 */
var early = A.config && A.config();
if (early) window.OtayoriForm.onConfig(early);

})();
