/* おたより工房 — 自由レイアウトの組版
   紙面は「全幅の帯（top）／可変の段組み（columns）／全幅の帯（bottom）」の三層。
   段の本数も幅も、どのブロックをどこに置くかも、AIか先生が決める。 */

(function (global) {
"use strict";

var PAGE_W = 1587, PAGE_H = 1123;
var DOC = null;

/* ---------------- 小道具 ---------------- */
function esc(s){
  return String(s == null ? "" : s)
    .replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;");
}
function getPath(o, p){
  var ks = String(p).split("."), v = o;
  for (var i = 0; i < ks.length; i++){ if (v == null) return v; v = v[ks[i]]; }
  return v;
}
function setPath(o, p, val){
  var ks = String(p).split("."), t = o;
  for (var i = 0; i < ks.length - 1; i++){ if (t[ks[i]] == null) t[ks[i]] = {}; t = t[ks[i]]; }
  t[ks[ks.length - 1]] = val;
}
function pal(){ return PALETTES[(DOC.theme || {}).palette] || PALETTES.wakaba; }

/** 本文の編集できる欄。data-path で原稿のどこかを指す。 */
function ed(path, cls, tag){
  var t = tag || "span";
  return "<" + t + ' class="ed ' + (cls || "") + '" contenteditable="true" data-path="' + path +
         '" spellcheck="false">' + esc(getPath(DOC, path)) + "</" + t + ">";
}
/** クリックで差し替えできるイラスト。 */
function illAt(path, cls, style){
  var k = getPath(DOC, path);
  if (!ILL[k]) k = "sakura";
  return '<span class="ill ' + (cls || "") + '"' + (style ? ' style="' + style + '"' : "") +
         ' data-slot="' + path + '" title="クリックで差し替え">' + illSvg(k) + "</span>";
}

/* ---------------- 飾りの部品 ---------------- */
function wave(color){
  var d = "M0 3 q 2.5 -2 5 0";
  for (var i = 0; i < 19; i++) d += " t 5 0";
  return '<svg class="wv" viewBox="0 0 100 6" preserveAspectRatio="none" aria-hidden="true">' +
         '<path d="' + d + '" fill="none" stroke="' + color + '" stroke-width="1.6" stroke-linecap="round"/></svg>';
}
function garland(colors){
  var W = 1471, H = 72, n = 15, sag = 22;
  var d = "M0 6 Q " + (W/2) + " " + (6 + sag*2) + " " + W + " 6", fl = "";
  for (var i = 0; i < n; i++){
    var t = (i + 0.5) / n;
    var x = 2*(1-t)*t*(W/2) + t*t*W;
    var y = (1-t)*(1-t)*6 + 2*(1-t)*t*(6 + sag*2) + t*t*6;
    fl += '<path d="M' + (x-15).toFixed(1) + " " + y.toFixed(1) + "L" + (x+15).toFixed(1) + " " + y.toFixed(1) +
          "L" + x.toFixed(1) + " " + (y+34).toFixed(1) + 'Z" fill="' + colors[i % colors.length] + '"/>';
  }
  return '<svg class="garland" viewBox="0 0 ' + W + " " + H + '" width="' + W + '" height="' + H + '" aria-hidden="true">' +
         '<path d="' + d + '" fill="none" stroke="#b8a287" stroke-width="3"/>' + fl + "</svg>";
}
function sunburst(color){
  var n = 20, cx = 735, cy = 66, R = 1200, out = "";
  for (var i = 0; i < n; i++){
    var a0 = (2*i)*Math.PI/n - Math.PI/2, a1 = (2*i+1)*Math.PI/n - Math.PI/2;
    out += '<path d="M' + cx + " " + cy + "L" + (cx + R*Math.cos(a0)).toFixed(0) + " " + (cy + R*Math.sin(a0)).toFixed(0) +
           "L" + (cx + R*Math.cos(a1)).toFixed(0) + " " + (cy + R*Math.sin(a1)).toFixed(0) + 'Z" fill="' + color + '"/>';
  }
  return '<svg class="sunburst" viewBox="0 0 1471 150" preserveAspectRatio="none" aria-hidden="true">' + out + "</svg>";
}
function wavyFrame(color){
  function hl(x0,x1,y,amp,step){
    var d = "M"+x0+" "+y+" q "+(step/2)+" "+(-amp)+" "+step+" 0", n = Math.floor((x1-x0)/step)-1;
    for (var i = 0; i < n; i++) d += " t "+step+" 0";
    return d;
  }
  function vl(y0,y1,x,amp,step){
    var d = "M"+x+" "+y0+" q "+(-amp)+" "+(step/2)+" 0 "+step, n = Math.floor((y1-y0)/step)-1;
    for (var i = 0; i < n; i++) d += " t 0 "+step;
    return d;
  }
  var d = hl(120,1467,36,7,26) + " " + hl(120,1467,1087,7,26) + " " +
          vl(120,1003,36,7,26) + " " + vl(120,1003,1551,7,26);
  return '<svg class="wavyframe" viewBox="0 0 1587 1123" width="1587" height="1123" aria-hidden="true">' +
         '<path d="' + d + '" fill="none" stroke="' + color + '" stroke-width="2.6" stroke-linecap="round" opacity=".5"/></svg>';
}
function bgPattern(kind, color, id){
  var pid = id || "pt", p = "";
  if (kind === "dots"){
    p = '<pattern id="'+pid+'" width="34" height="34" patternUnits="userSpaceOnUse">' +
        '<circle cx="9" cy="9" r="4.2" fill="'+color+'"/><circle cx="26" cy="26" r="4.2" fill="'+color+'"/></pattern>';
  } else if (kind === "check"){
    p = '<pattern id="'+pid+'" width="40" height="40" patternUnits="userSpaceOnUse">' +
        '<rect width="20" height="20" fill="'+color+'"/><rect x="20" y="20" width="20" height="20" fill="'+color+'"/>' +
        '<rect x="20" width="20" height="20" fill="'+color+'" opacity=".45"/>' +
        '<rect y="20" width="20" height="20" fill="'+color+'" opacity=".45"/></pattern>';
  } else if (kind === "stripe"){
    p = '<pattern id="'+pid+'" width="26" height="26" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">' +
        '<rect width="13" height="26" fill="'+color+'"/></pattern>';
  } else if (kind === "grid"){
    p = '<pattern id="'+pid+'" width="34" height="34" patternUnits="userSpaceOnUse">' +
        '<path d="M34 0H0v34" fill="none" stroke="'+color+'" stroke-width="2"/></pattern>';
  } else if (kind === "star"){
    p = '<pattern id="'+pid+'" width="44" height="44" patternUnits="userSpaceOnUse">' +
        '<path d="M11 3l2.4 4.9 5.4.8-3.9 3.8 1 5.4L11 15.3l-4.9 2.6 1-5.4-3.9-3.8 5.4-.8z" fill="'+color+'"/>' +
        '<path d="M33 25l2.4 4.9 5.4.8-3.9 3.8 1 5.4L33 37.3l-4.9 2.6 1-5.4-3.9-3.8 5.4-.8z" fill="'+color+'" opacity=".65"/></pattern>';
  } else if (kind === "heart"){
    p = '<pattern id="'+pid+'" width="42" height="42" patternUnits="userSpaceOnUse">' +
        '<path d="M11 19S3 13.2 3 8.2A4.8 4.8 0 0 1 11 5.2a4.8 4.8 0 0 1 8 3C19 13.2 11 19 11 19z" fill="'+color+'"/>' +
        '<path d="M32 40s-8-5.8-8-10.8a4.8 4.8 0 0 1 8-3a4.8 4.8 0 0 1 8 3C40 34.2 32 40 32 40z" fill="'+color+'" opacity=".65"/></pattern>';
  } else if (kind === "flower"){
    p = '<pattern id="'+pid+'" width="46" height="46" patternUnits="userSpaceOnUse">' +
        '<g fill="'+color+'"><circle cx="12" cy="6" r="4.2"/><circle cx="18" cy="12" r="4.2"/><circle cx="12" cy="18" r="4.2"/><circle cx="6" cy="12" r="4.2"/></g>' +
        '<g fill="'+color+'" opacity=".6"><circle cx="34" cy="28" r="3.6"/><circle cx="39" cy="33" r="3.6"/><circle cx="34" cy="38" r="3.6"/><circle cx="29" cy="33" r="3.6"/></g></pattern>';
  } else if (kind === "confetti"){
    p = '<pattern id="'+pid+'" width="58" height="58" patternUnits="userSpaceOnUse"><g fill="'+color+'">' +
        '<circle cx="9" cy="11" r="4.4"/><rect x="28" y="6" width="9" height="9" rx="2.4" transform="rotate(22 32 10)"/>' +
        '<path d="M47 29l5.5 10h-11z"/><circle cx="21" cy="39" r="3.6"/>' +
        '<rect x="39" y="47" width="10" height="5.4" rx="2.7"/><path d="M6 33l4.6 8H1.4z"/>' +
        '<rect x="16" y="20" width="7" height="7" rx="1.8" transform="rotate(-18 19 23)"/></g></pattern>';
  } else return "";
  return '<svg class="bgpat" aria-hidden="true"><defs>' + p + '</defs><rect width="100%" height="100%" fill="url(#'+pid+')"/></svg>';
}

/* ---------------- 紙のふち ---------------- */
function chrome(pi){
  var p = pal(), base = "pages." + pi + ".deco";
  var h = bgPattern((DOC.theme || {}).pattern, p.tint2, "pt" + pi) +
    '<div class="fr1"></div><div class="fr2"></div>' +
    wavyFrame(p.accent) +
    garland([p.accent, p.accent2, p.accent3, p.tint2, p.accent2, p.accent3]) +
    illAt(base + ".corners.0", "corner c-tl") + illAt(base + ".corners.1", "corner c-tr") +
    illAt(base + ".corners.2", "corner c-bl") + illAt(base + ".corners.3", "corner c-br");
  var ys = [15, 31, 47, 63, 79], side = ["left:12px", "right:12px"];
  for (var s = 0; s < 2; s++){
    for (var i = 0; i < 5; i++){
      var idx = s*5 + i;
      var extra = (i === 1 || i === 3) ? " extra" : "";
      var rot = ((idx*53) % 34) - 17;
      h += illAt(base + ".edge." + idx, "edge-ill" + extra,
        side[s] + ";top:" + (ys[i] + (s ? 7 : 0)) + "%;transform:rotate(" + rot + "deg)");
    }
  }
  return h;
}

/* ---------------- ブロック ---------------- */
var BLOCK_KINDS = [
  ["text",     "本文（見出し＋文章）"],
  ["section",  "記事（ラベル付きの段落）"],
  ["list",     "箇条書き（おねがい など）"],
  ["schedule", "予定（日付＋行事）"],
  ["pair",     "ラベルと値（うた・えほん）"],
  ["chips",    "丸いピル（誕生児 など）"],
  ["lead",     "吹き出しのあいさつ"],
  ["quiz",     "クイズ"],
  ["banner",   "一行の帯"],
  ["note",     "編集後記"],
  ["comments", "こどもたちのすがた"],
  ["photo",    "写真"],
  ["table",    "表"],
  ["illband",  "イラストの帯"],
  ["head",     "ページ見出し"],
  ["title",    "題字"]
];

/* わくを選べるブロックと、テープを貼れるブロック。ほかは形が決まっている */
var BOXED = ["text","section","list","schedule","pair","chips","table","photo","comments","banner"];
var TAPED = ["text","section","list","schedule","pair","chips","table","photo","comments"];

function blockProto(kind){
  var b = {kind: kind, ill: "hana"};
  if (kind === "text"){ b.heading = "みだし"; b.body = "ここに本文を書きます。"; }
  else if (kind === "section"){ b.heading = "みだし"; b.parts = [{k:"ねらい", v:"ここに文章を書きます。"}]; }
  else if (kind === "list"){ b.heading = "おねがい"; b.items = ["おねがいの内容"]; }
  else if (kind === "schedule"){ b.heading = "今月の予定"; b.items = [{date:"5/1", label:"行事"}]; }
  else if (kind === "pair"){ b.heading = "今月のうた・えほん"; b.items = [{k:"うた", v:"曲名"}, {k:"えほん", v:"題名"}]; }
  else if (kind === "chips"){ b.heading = "おたんじょうびおめでとう"; b.items = [{name:"なまえ", note:"5/1"}]; }
  else if (kind === "lead"){ b.heading = "ごあいさつ"; b.body = "ここにあいさつ文を書きます。"; b.box = "balloon"; }
  else if (kind === "quiz"){ b.heading = "なぞなぞ"; b.q = "もんだい"; b.a = "こたえ"; b.box = "balloon"; }
  else if (kind === "banner"){ b.text = "おしらせの一行"; b.box = "band"; }
  else if (kind === "note"){ b.heading = "編集後記"; b.body = "ここに後記を書きます。"; b.box = "balloon"; }
  else if (kind === "comments"){ b.heading = "こどもたちのすがた"; b.cols = 3; b.items = []; }
  else if (kind === "photo"){ b.heading = "写真"; b.items = [{caption:"写真のせつめい"}]; }
  else if (kind === "table"){ b.heading = "表"; b.head = ["こうもく","ないよう"]; b.rows = [["",""]]; }
  else if (kind === "illband"){ b.items = ["hana","hoshi","chouchou","ehon","onpu","ashiato","tulip"]; }
  else if (kind === "head"){ b.text = "おしらせ"; }
  else if (kind === "title"){ b.title = "◯◯組だより"; b.sub = "副題"; b.ill = "koinobori"; b.illR = "himawari"; }
  return b;
}

function itemProto(kind){
  if (kind === "schedule") return {date:"5/1", label:"行事"};
  if (kind === "pair") return {k:"ラベル", v:"ないよう"};
  if (kind === "chips") return {name:"なまえ", note:"5/1"};
  if (kind === "photo") return {caption:"写真のせつめい"};
  if (kind === "comments") return {name:"なまえ", text:"", ill:"hana"};
  if (kind === "illband") return "hoshi";
  if (kind === "section") return {k:"ラベル", v:"ここに文章を書きます。"};
  return "あたらしい行";
}

/** フォームの提出時刻を「11/8 10:02」の形に。 */
function shortTime(t){
  var m = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/.exec(String(t || ""));
  return m ? (+m[2]) + "/" + (+m[3]) + " " + m[4] + ":" + m[5] : "";
}
function blkui(path, b){
  var src = (b && b.src)
    ? '<span class="src" title="フォームの「' + esc(b.src) + '」から。新しい提出があると差し替わります">フォーム：' +
      esc(b.src) + (b.srcTime ? "　" + shortTime(b.srcTime) : "　未提出") + "</span>"
    : "";
  return '<div class="blkui" data-ui>' + src +
    '<button type="button" class="deco" data-act="blk-deco" data-path="' + path + '" title="わく・テープ・かたむき">かざる</button>' +
    '<button type="button" data-act="blk-up" data-path="' + path + '" title="上へ">↑</button>' +
    '<button type="button" data-act="blk-down" data-path="' + path + '" title="下へ">↓</button>' +
    '<button type="button" data-act="blk-del" data-path="' + path + '" title="消す">×</button></div>';
}
function tapeDeco(b, i){
  var box = b.box || "paper";
  var tape = b.tape || (box === "paper" ? ["tape","taper","pin"][i % 3] : "none");
  var h = "";
  if (tape === "tape") h = '<span class="tape"></span>';
  else if (tape === "taper") h = '<span class="tape r"></span>';
  else if (tape === "pin") h = '<span class="pin"></span>';
  if (box === "paper") h += '<span class="fold"></span>';
  return h;
}
function heading(b, path){
  if (!b.heading) return "";
  return '<div class="hd">' + illAt(path + ".ill") + '<span class="tx">' + ed(path + ".heading") + "</span></div>" +
         wave(pal().rule);
}
function itemBtns(path, kind){
  return '<div class="uirow" data-ui>' +
    '<button class="uibtn" type="button" data-act="item-add" data-path="' + path + '" data-k="' + kind + '">＋ 足す</button>' +
    '<button class="uibtn" type="button" data-act="item-del" data-path="' + path + '">－ 最後を消す</button></div>';
}

function renderBlock(b, path, i){
  if (!b || !b.kind) return "";
  var p = pal(), box = b.box || "paper", kind = b.kind;
  var tilt = (typeof b.tilt === "number" && isFinite(b.tilt)) ? b.tilt : 0;
  /* grow: 段の下のあまりまで高さをのばす */
  var gcls = b.grow ? " grow" : "";
  var st = "";
  if (tilt) st += "transform:rotate(" + Math.max(-3, Math.min(3, tilt)) + "deg);";
  /* bg: 色画用紙の色（パレットの cards の番号）。フォームのクラス記事で使う */
  if (typeof b.bg === "number" && p.cards) st += "background:" + p.cards[Math.abs(b.bg) % p.cards.length] + ";";
  var style = st ? ' style="' + st + '"' : "";
  var inner = "";

  if (kind === "title"){
    inner = '<div class="titlewrap"><div class="titlebox">' + sunburst(p.tint2) +
      illAt(path + ".ill", "big") +
      '<div class="tt"><div class="school">' + ed("meta.school") + "</div>" +
      '<h1 class="ttl">' + ed(path + ".title") + "</h1>" +
      '<div class="sub">' + ed(path + ".sub") + "</div></div>" +
      illAt(path + ".illR", "big") + "</div>" +
      '<div class="issuebox"><div class="i1">' + ed("meta.issue") + "</div>" +
      '<div class="i2">' + ed("meta.dateText") + "</div></div>" +
      ((DOC.meta && (DOC.meta.className || DOC.meta.teacher))
        ? '<div class="teacherbox">' + ed("meta.className") + "　" + ed("meta.teacher") + "</div>" : "") +
      "</div>";
    return '<div class="blk' + gcls + ' box-plain"' + style + ">" + blkui(path, b) + inner + "</div>";
  }

  if (kind === "head"){
    inner = '<div class="shead">' +
      '<svg class="rb l" viewBox="0 0 26 34" aria-hidden="true"><path d="M26 0L0 7v20l26 7z" fill="' + p.accent + '"/></svg>' +
      '<svg class="rb r" viewBox="0 0 26 34" aria-hidden="true"><path d="M0 0l26 7v20L0 34z" fill="' + p.accent + '"/></svg>' +
      illAt(path + ".ill") + "<h2>" + ed(path + ".text") + "</h2>" + illAt(path + ".ill2") + "</div>";
    return '<div class="blk' + gcls + ' box-plain"' + style + ">" + blkui(path, b) + inner + "</div>";
  }

  if (kind === "lead" || kind === "note" || kind === "quiz"){
    var body;
    if (kind === "quiz"){
      body = '<div class="quiz"><div class="qq"><span class="mk">Q</span><span>' + ed(path + ".q") + "</span></div>" +
             '<div class="aa"><span class="mk">A</span><span>' + ed(path + ".a") + "</span></div></div>";
    } else {
      body = '<p style="margin:0">' + ed(path + ".body") + "</p>";
    }
    var h2 = b.heading ? '<div class="leadh">' + ed(path + ".heading") + "</div>" : "";
    var rev = (kind === "note") ? " rev" : "";
    inner = '<div class="balloonwrap' + rev + '">' + illAt(path + ".ill", "who") +
      '<div class="bl box-balloon"><svg class="tail" viewBox="0 0 20 26" aria-hidden="true">' +
      '<path d="M20 0L0 13l20 13z" fill="' + p.accent + '"/><path d="M20 5L7 13l13 8z" fill="#fff"/></svg>' +
      h2 + body + "</div></div>";
    return '<div class="blk' + gcls + ' box-plain"' + style + ">" + blkui(path, b) + inner + "</div>";
  }

  if (kind === "banner"){
    inner = '<div class="bandtx">' + illAt(path + ".ill") + "<span>" + ed(path + ".text") + "</span></div>";
    return '<div class="blk' + gcls + ' box-' + (b.box || "band") + '"' + style + ">" + blkui(path, b) + inner + "</div>";
  }

  if (kind === "illband"){
    var items = Array.isArray(b.items) ? b.items : [];
    inner = '<div class="illband">';
    for (var k = 0; k < items.length; k++) inner += illAt(path + ".items." + k);
    inner += "</div>" + itemBtns(path + ".items", "illband");
    return '<div class="blk' + gcls + ' box-plain"' + style + ">" + blkui(path, b) + inner + "</div>";
  }

  /* ここから下は囲みのあるブロック */
  inner = heading(b, path);

  if (kind === "text"){
    inner += '<div class="bodytx">' + ed(path + ".body") + "</div>";

  } else if (kind === "section"){
    var parts = Array.isArray(b.parts) ? b.parts : [];
    inner += '<div class="secparts">';
    for (var q = 0; q < parts.length; q++){
      var aim = parts[q] && parts[q].k === "ねらい" ? " aim" : "";
      inner += '<div class="secpart' + aim + '"><span class="k">' + ed(path + ".parts." + q + ".k") + "</span>" +
               '<div class="v">' + ed(path + ".parts." + q + ".v") + "</div></div>";
    }
    inner += "</div>" + itemBtns(path + ".parts", "section");

  } else if (kind === "list"){
    var li = Array.isArray(b.items) ? b.items : [];
    inner += '<ul class="reqs">';
    for (var a = 0; a < li.length; a++){
      inner += '<li><span class="mk">' + illSvg(ILL[b.ill] ? b.ill : "hana") + "</span>" + ed(path + ".items." + a) + "</li>";
    }
    inner += "</ul>" + itemBtns(path + ".items", "list");

  } else if (kind === "schedule"){
    var sc = Array.isArray(b.items) ? b.items : [];
    inner += '<ul class="cal">';
    for (var c = 0; c < sc.length; c++){
      inner += '<li><span class="d">' + ed(path + ".items." + c + ".date") + "</span>" +
               '<span class="l">' + ed(path + ".items." + c + ".label") + "</span></li>";
    }
    inner += "</ul>" + itemBtns(path + ".items", "schedule");

  } else if (kind === "pair"){
    var pr = Array.isArray(b.items) ? b.items : [];
    inner += '<div class="pairs">';
    for (var d2 = 0; d2 < pr.length; d2++){
      inner += '<div class="one"><span class="k">' + ed(path + ".items." + d2 + ".k") + "</span>" +
               '<span class="v">' + ed(path + ".items." + d2 + ".v") + "</span></div>";
    }
    inner += "</div>" + itemBtns(path + ".items", "pair");

  } else if (kind === "chips"){
    var ch = Array.isArray(b.items) ? b.items : [];
    inner += '<div class="bdays">';
    for (var e2 = 0; e2 < ch.length; e2++){
      inner += '<span class="bday"><span class="bdi">' + illSvg("hoshi") + "</span>" +
               "<span>" + ed(path + ".items." + e2 + ".name") + "</span>" +
               '<span class="dt">' + ed(path + ".items." + e2 + ".note") + "</span></span>";
    }
    inner += "</div>" + itemBtns(path + ".items", "chips");

  } else if (kind === "table"){
    var head = Array.isArray(b.head) ? b.head : [], rows = Array.isArray(b.rows) ? b.rows : [];
    inner += '<table class="tbl"><thead><tr>';
    for (var f2 = 0; f2 < head.length; f2++) inner += "<th>" + ed(path + ".head." + f2) + "</th>";
    inner += "</tr></thead><tbody>";
    for (var g2 = 0; g2 < rows.length; g2++){
      inner += "<tr>";
      for (var h2i = 0; h2i < (rows[g2] || []).length; h2i++) inner += "<td>" + ed(path + ".rows." + g2 + "." + h2i) + "</td>";
      inner += "</tr>";
    }
    inner += "</tbody></table>" +
      '<div class="uirow" data-ui><button class="uibtn" type="button" data-act="row-add" data-path="' + path + '">＋ 行</button>' +
      '<button class="uibtn" type="button" data-act="row-del" data-path="' + path + '">－ 最後の行</button></div>';

  } else if (kind === "photo"){
    var ph = Array.isArray(b.items) ? b.items : [];
    inner += '<div class="phwrap" data-photos="' + path + '.items">';
    for (var m2 = 0; m2 < ph.length; m2++){
      var src = ph[m2] && ph[m2].src;
      inner += '<div class="ph"><button class="del" type="button" data-ui data-act="item-at-del" data-path="' +
               path + '.items" data-i="' + m2 + '" aria-label="消す">×</button>' +
               '<span class="im" data-act="photo-slot" data-path="' + path + ".items." + m2 + '" title="クリックで写真をえらぶ">' +
               (src ? '<img src="' + esc(src) + '" alt="">'
                    : '<span class="phhint"><b>＋</b>クリックで<br>写真をえらぶ</span>') + "</span>" +
               '<div class="cap">' + ed(path + ".items." + m2 + ".caption") + "</div></div>";
    }
    inner += "</div>" +
      '<div class="uirow" data-ui><button class="uibtn" type="button" data-act="photo-pick" data-path="' + path + '.items">＋ 写真をえらぶ</button>' +
      '<button class="uibtn" type="button" data-act="item-add" data-path="' + path + '.items" data-k="photo">＋ 空の枠</button></div>';

  } else if (kind === "comments"){
    var cm = Array.isArray(b.items) ? b.items : [];
    var cols = Math.max(1, Math.min(4, parseInt(b.cols, 10) || 3));
    inner += '<div class="cgrid" style="grid-template-columns:repeat(' + cols + ',1fr)">';
    if (!cm.length){
      inner += '<div style="grid-column:1/-1;border:2.5px dashed ' + p.rule + ';border-radius:16px;padding:26px;' +
               'text-align:center;color:' + p.accent + ';font-size:14px">「コメント」で子どもの様子を入れると、ここに色紙のカードで並びます</div>';
    }
    for (var n2 = 0; n2 < cm.length; n2++){
      inner += '<div class="cmt" style="background:' + p.cards[n2 % p.cards.length] + '">' +
        '<button class="del" type="button" data-ui data-act="item-at-del" data-path="' + path + '.items" data-i="' + n2 + '" aria-label="消す">×</button>' +
        '<span class="ctape"></span>' +
        '<div class="nm">' + illAt(path + ".items." + n2 + ".ill") + "<span>" + ed(path + ".items." + n2 + ".name") + "</span></div>" +
        '<div class="tx">' + ed(path + ".items." + n2 + ".text") + "</div></div>";
    }
    inner += "</div>";
  }

  return '<div class="blk' + gcls + ' box-' + box + '"' + style + ">" + blkui(path, b) + tapeDeco(b, i) + inner + "</div>";
}

/* ---------------- ページ ---------------- */
function renderStrip(list, path, cls){
  if (!Array.isArray(list) || !list.length) return "";
  var h = '<div class="' + cls + '">';
  for (var i = 0; i < list.length; i++) h += renderBlock(list[i], path + "." + i, i);
  return h + "</div>";
}

/** 位置は左上の px で書く。translate(-50%) は画像PDF（html2canvas）が読めず、左上に小さく出てしまう */
function stickerStyle(st){
  return "left:" + (st.x - st.s / 2) + "px;top:" + (st.y - st.s / 2) + "px;width:" + st.s + "px;height:" + st.s +
         "px;transform:rotate(" + st.r + "deg)";
}

/** 好きな所に貼ったイラスト。x, y は紙の上の中心（px）、s は一辺、r は回転（度） */
function renderStickers(page, pi){
  var list = Array.isArray(page.stickers) ? page.stickers : [], h = "";
  for (var i = 0; i < list.length; i++){
    var st = list[i];
    if (!st || !ILL[st.k]) continue;
    h += '<div class="stk" data-stk="' + pi + "." + i + '" style="' + stickerStyle(st) + '">' + illSvg(st.k) +
         '<i class="stk-h stk-rot" data-ui data-h="rot" title="まわす"></i>' +
         '<i class="stk-h stk-size" data-ui data-h="size" title="大きさ"></i>' +
         '<button class="stk-h stk-del" type="button" data-ui data-h="del" title="はがす">×</button></div>';
  }
  return h;
}

function renderPage(page, pi){
  var h = chrome(pi) + '<div class="inner">';
  h += renderStrip(page.top, "pages." + pi + ".top", "band-top");

  var cols = Array.isArray(page.columns) ? page.columns : [];
  if (cols.length){
    h += '<div class="cols">';
    for (var c = 0; c < cols.length; c++){
      var w = parseFloat(cols[c] && cols[c].w);
      if (!isFinite(w) || w <= 0) w = 1;
      var blocks = Array.isArray(cols[c].blocks) ? cols[c].blocks : [];
      h += '<div class="col" style="flex:' + w.toFixed(2) + '">';
      if (c < cols.length - 1){
        h += '<div class="colgrip" data-ui data-grip="' + pi + "." + c + '" title="ドラッグで横幅を変える"><i>⇔</i></div>';
      }
      for (var b = 0; b < blocks.length; b++){
        h += renderBlock(blocks[b], "pages." + pi + ".columns." + c + ".blocks." + b, b);
      }
      h += '<button class="addblk" type="button" data-ui data-act="blk-add" data-path="pages.' + pi +
           ".columns." + c + '.blocks">＋ ブロックを足す</button></div>';
    }
    h += "</div>";
  }

  h += renderStrip(page.bottom, "pages." + pi + ".bottom", "band-bottom");
  /* フッター：題字と同じく囲みに分けない1行。足すかどうかはページごと */
  if (typeof page.footer === "string"){
    h += '<div class="pfoot"><span class="pfl"></span>' +
         '<span class="ed pftx" contenteditable="true" data-oneline data-path="pages.' + pi + '.footer" spellcheck="false">' +
         esc(page.footer) + "</span><span class=\"pfl\"></span>" +
         '<button class="pfdel" type="button" data-ui data-act="foot-del" data-path="pages.' + pi + '">× フッターを消す</button></div>';
  }
  h += "</div>";
  h += renderStickers(page, pi);
  if (typeof page.footer !== "string"){
    h += '<button class="pfadd" type="button" data-ui data-act="foot-add" data-path="pages.' + pi + '">＋ フッターを足す</button>';
  }
  h += '<div class="pnum">' + (pi + 1) + " / " + Math.max(2, (DOC.pages || []).length) + "</div>";
  return h;
}

function sheetVars(){
  var p = pal(), t = DOC.theme || {};
  return "--accent:" + p.accent + ";--accent2:" + p.accent2 + ";--accent3:" + p.accent3 +
    ";--tint:" + p.tint + ";--tint2:" + p.tint2 + ";--paper:" + p.paper + ";--rule:" + p.rule +
    ";--tape:" + p.tape +
    ";--h-font:" + (FONTS[t.headingFont] || FONTS.maru) +
    ";--t-font:" + (FONTS[t.titleFont] || FONTS.pop) + ";";
}

/** 原稿から紙面のHTMLを組む。戻り値は 1 ページ 1 要素の配列。 */
function renderDoc(doc){
  DOC = doc;
  var vars = sheetVars(), lv = (doc.theme || {}).level || "mori", out = [];
  var pages = Array.isArray(doc.pages) ? doc.pages : [];
  for (var i = 0; i < pages.length; i++){
    out.push('<div class="sheet" id="sheet' + (i + 1) + '" data-level="' + lv + '" style="' + vars + '">' +
             renderPage(pages[i], i) + "</div>");
  }
  return out;
}

global.Otayori = {
  PAGE_W: PAGE_W, PAGE_H: PAGE_H,
  renderDoc: renderDoc, getPath: getPath, setPath: setPath, esc: esc,
  blockProto: blockProto, itemProto: itemProto, BLOCK_KINDS: BLOCK_KINDS,
  bgPattern: bgPattern, BOXED: BOXED, TAPED: TAPED, stickerStyle: stickerStyle
};

})(window);
