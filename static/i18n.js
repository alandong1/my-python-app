"use strict";
// Dev Lab 中英文切换（全站共用，见 docs/requirements.md「中英文切换」）
//
// 原理：页面上的中文原文就是「键」。英文译文放在字典里（i18n.add），按中文查找；
// 查不到就显示中文，所以新增文字时漏翻译也不会出现空白。
//
// 用法（HTML）：
//   <span data-i18n>登录</span>                 文字内容
//   <p data-i18n-html>点击<b>右键</b>进军</p>   含标签的 HTML（键是 innerHTML 原文）
//   <input data-i18n-ph="密码">                 placeholder
//   <button data-i18n-title="回到主城">         title 提示
//   <button data-i18n-aria="关闭">              aria-label
//   <button data-lang-toggle></button>          切换按钮（自动接管，显示「EN」或「中文」）
// 用法（JS）：
//   i18n.t("共 {0} 件", n)                      带占位符的文字
//   i18n.onChange(render)                       语言切换后重新渲染动态内容
(function () {
  const STORE_KEY = "lang";
  const dict = {};                 // 英文译文：中文原文 -> English
  const listeners = [];
  const originals = new WeakMap(); // 元素 -> {text, html}：第一次处理时记下的中文原文
  let lang = readSaved();

  function readSaved() {
    try { return localStorage.getItem(STORE_KEY) === "en" ? "en" : "zh"; } catch (e) { return "zh"; }
  }
  function save(v) {
    try { localStorage.setItem(STORE_KEY, v); } catch (e) { /* 隐私模式等情况下无法保存，就只在本次页面有效 */ }
  }

  function t(zh, ...args) {
    let s = lang === "en" && dict[zh] !== undefined ? dict[zh] : zh;
    args.forEach((a, i) => { s = s.split(`{${i}}`).join(String(a)); });
    return s;
  }

  // 第一次看到元素时记下中文原文，之后切换语言都从原文翻译，不会越翻越乱
  function original(el, kind) {
    let rec = originals.get(el);
    if (!rec) originals.set(el, rec = {});
    if (rec[kind] === undefined) rec[kind] = kind === "text" ? el.textContent.trim() : el.innerHTML.trim();
    return rec[kind];
  }

  function applyStatic(root = document) {
    root.querySelectorAll("[data-i18n]").forEach((el) => {
      el.textContent = t(original(el, "text"));
    });
    root.querySelectorAll("[data-i18n-html]").forEach((el) => {
      el.innerHTML = t(original(el, "html"));
    });
    // 属性类：源文字就写在 data-i18n-xxx 属性里，直接翻译后写回对应属性
    const attrs = { "data-i18n-ph": "placeholder", "data-i18n-title": "title", "data-i18n-aria": "aria-label" };
    for (const [src, attr] of Object.entries(attrs)) {
      root.querySelectorAll(`[${src}]`).forEach((el) => el.setAttribute(attr, t(el.getAttribute(src))));
    }
  }

  function renderToggles() {
    document.querySelectorAll("[data-lang-toggle]").forEach((b) => {
      b.textContent = lang === "en" ? "中文" : "EN";
      b.title = t("切换语言");
      b.setAttribute("aria-label", t("切换语言"));
    });
  }

  function setLang(v) {
    lang = v === "en" ? "en" : "zh";
    save(lang);
    document.documentElement.lang = lang === "en" ? "en" : "zh-CN";
    applyStatic();
    renderToggles();
    listeners.forEach((fn) => {
      try { fn(lang); } catch (e) { console.error(e); }
    });
  }

  document.addEventListener("click", (e) => {
    if (e.target.closest("[data-lang-toggle]")) setLang(lang === "en" ? "zh" : "en");
  });

  function init() {
    document.documentElement.lang = lang === "en" ? "en" : "zh-CN";
    applyStatic();
    renderToggles();
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();

  window.i18n = {
    t,
    get lang() { return lang; },
    setLang,
    // 注册译文后立即重新翻译页面（脚本加载顺序不确定时，译文可能晚于页面初始化）
    add(obj) { Object.assign(dict, obj); applyStatic(); },
    onChange(fn) { listeners.push(fn); },
    apply: applyStatic,
  };
})();
