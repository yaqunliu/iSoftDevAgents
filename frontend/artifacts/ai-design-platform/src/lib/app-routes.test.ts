/**
 * 接口注释：
 * app-routes 的单测。这些断言保护的是"用户点了按钮之后落在哪个页面"，
 * 而路径错误在运行时不报错，只能靠测试拦。
 */

import test from "node:test";
import assert from "node:assert/strict";

import { APP_HOME_PATH, resolveAppNextPath } from "./app-routes.ts";

test("resolveAppNextPath falls back to the app home for empty input", () => {
  assert.equal(resolveAppNextPath(null), APP_HOME_PATH);
  assert.equal(resolveAppNextPath(undefined), APP_HOME_PATH);
  assert.equal(resolveAppNextPath(""), APP_HOME_PATH);
});

test("resolveAppNextPath sends bare '/' to the app, not to the marketing site", () => {
  // 这条是本次路径搬迁最关键的一条断言：官网占了 "/"，
  // 登录成功后回跳 "/" 会把用户丢在营销页上，看起来像登录没生效。
  assert.equal(resolveAppNextPath("/"), APP_HOME_PATH);
});

test("resolveAppNextPath preserves a genuine in-app destination", () => {
  assert.equal(resolveAppNextPath("/project/42"), "/project/42");
  assert.equal(resolveAppNextPath("/app"), "/app");
});

test("resolveAppNextPath rejects anything that could leave the origin", () => {
  // 开放重定向：这三种写法浏览器都会当成跨站地址。
  assert.equal(resolveAppNextPath("//evil.example"), APP_HOME_PATH);
  assert.equal(resolveAppNextPath("/\\evil.example"), APP_HOME_PATH);
  assert.equal(resolveAppNextPath("https://evil.example"), APP_HOME_PATH);
  assert.equal(resolveAppNextPath("javascript:alert(1)"), APP_HOME_PATH);
});
