import test from "node:test";
import assert from "node:assert/strict";

import { APP_AUTH_PATH, buildAppAuthUrl, isExternalUrl } from "./landing-app-url.ts";

// 行为变更（2026-09）：origin 缺省不再兜底成 app 子域，而是产出同源相对路径。
// 原因见 landing-app-url.ts 顶部注释——官网和产品现在是同一个应用。
test("buildAppAuthUrl produces a same-origin path when no origin is configured", () => {
  assert.equal(buildAppAuthUrl(), APP_AUTH_PATH);
  assert.equal(buildAppAuthUrl({ origin: "   " }), APP_AUTH_PATH);
  assert.equal(buildAppAuthUrl({ origin: null }), APP_AUTH_PATH);
});

test("buildAppAuthUrl still supports an explicit cross-origin deployment", () => {
  assert.equal(buildAppAuthUrl({ origin: "https://app.example.com/" }), "https://app.example.com/auth");
  assert.equal(buildAppAuthUrl({ origin: "https://app.example.com///" }), "https://app.example.com/auth");
});

test("buildAppAuthUrl appends an encoded next parameter for post-login redirects", () => {
  assert.equal(
    buildAppAuthUrl({ origin: "https://a.test", next: "/project/42" }),
    "https://a.test/auth?next=%2Fproject%2F42",
  );
  assert.equal(buildAppAuthUrl({ next: "/app" }), "/auth?next=%2Fapp");
});

// 安全回归：next 只允许站内绝对路径，否则官网会变成开放重定向的钓鱼跳板。
test("buildAppAuthUrl rejects any next value that could leave the app origin", () => {
  assert.equal(buildAppAuthUrl({ origin: "https://a.test", next: "https://evil.test" }), "https://a.test/auth");
  assert.equal(buildAppAuthUrl({ origin: "https://a.test", next: "//evil.test" }), "https://a.test/auth");
  assert.equal(buildAppAuthUrl({ origin: "https://a.test", next: "/\\evil.test" }), "https://a.test/auth");
  assert.equal(buildAppAuthUrl({ origin: "https://a.test", next: "project/42" }), "https://a.test/auth");
  assert.equal(buildAppAuthUrl({ origin: "https://a.test", next: "" }), "https://a.test/auth");
});

// 这条决定登录按钮渲染成 wouter 的 Link 还是原生 <a>。判错的后果是
// 站内跳转变成整页刷新（能用但闪一下），或者跨域跳转被前端路由吃掉（点了没反应）。
test("isExternalUrl distinguishes in-app paths from cross-origin destinations", () => {
  assert.equal(isExternalUrl("/auth"), false);
  assert.equal(isExternalUrl("/auth?next=%2Fapp"), false);
  assert.equal(isExternalUrl("https://app.gmonkey.ai/auth"), true);
  assert.equal(isExternalUrl("//app.gmonkey.ai/auth"), true);
  // mailto / tel 同样会离开前端路由，必须渲染成原生 <a>
  assert.equal(isExternalUrl("mailto:support@gmonkey.ai"), true);
});
