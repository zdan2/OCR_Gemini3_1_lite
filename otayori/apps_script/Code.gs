/**
 * 光の原だより 原稿提出フォーム → おたより工房
 *
 * 区分ごとに「いちばん新しい回答」を1件ずつ JSON で返す。
 * 「回答を編集」で出し直した回答も、編集した時刻で新しい方として扱われる。
 *
 * 置き方（フォームの持ち主のアカウントで1回だけ）
 *   1. フォームの編集画面 → 右上の︙ →「スクリプト エディタ」
 *   2. このファイルの中身を全部貼り付け、下の KEY を長いでたらめな文字列に変える
 *   3. 「デプロイ」→「新しいデプロイ」→ 種類「ウェブアプリ」
 *        次のユーザーとして実行: 自分
 *        アクセスできるユーザー: 全員
 *   4. 出てきた URL の末尾に ?key=（KEYと同じ文字列）を付けて、おたより工房の「フォーム連携」に貼る
 *
 * URL と KEY を知っている人なら誰でも、提出された原稿を読めます。外に出さないでください。
 */
const KEY = 'ここを長いでたらめな文字列に変える';

function doGet(e) {
  if (!e || !e.parameter || e.parameter.key !== KEY || KEY.indexOf('ここを') === 0) {
    return json_({ ok: false, error: 'key が違うか、まだ KEY を設定していません。' });
  }
  const form = FormApp.getActiveForm();
  const tz = Session.getScriptTimeZone();
  const latest = {};

  form.getResponses().forEach(function (r) {
    const answers = {};
    r.getItemResponses().forEach(function (ir) {
      const v = ir.getResponse();
      answers[ir.getItem().getTitle()] = Array.isArray(v) ? v.join('、') : String(v);
    });
    const kubun = answers['区分'];
    if (!kubun) return;
    const t = r.getTimestamp();
    if (!latest[kubun] || latest[kubun].t < t) latest[kubun] = { t: t, answers: answers };
  });

  const responses = Object.keys(latest).map(function (k) {
    return {
      time: Utilities.formatDate(latest[k].t, tz, "yyyy-MM-dd'T'HH:mm:ss"),
      answers: latest[k].answers
    };
  });
  return json_({
    ok: true,
    form: form.getTitle(),
    fetchedAt: Utilities.formatDate(new Date(), tz, "yyyy-MM-dd'T'HH:mm:ss"),
    responses: responses
  });
}

function json_(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON);
}
