import test from "node:test";
import assert from "node:assert/strict";

import {
  CONTACT_FIELD_ORDER,
  CONTACT_MESSAGE_MAX_LENGTH,
  EMPTY_CONTACT_FORM,
  hasContactFormErrors,
  isPlausibleEmail,
  validateContactForm,
} from "./landing-contact-form.ts";

test("an untouched form reports the three required fields and not the optional one", () => {
  const errors = validateContactForm(EMPTY_CONTACT_FORM);
  assert.equal(errors.name, "nameRequired");
  assert.equal(errors.email, "emailRequired");
  assert.equal(errors.message, "messageRequired");
  // Company 是选填，空着不应该拦人。
  assert.equal(errors.company, undefined);
});

test("a complete enquiry passes", () => {
  const errors = validateContactForm({
    name: "Wei Chen",
    email: "wei@example.com",
    company: "Example Pte Ltd",
    message: "We would like a walkthrough of the delivery pipeline.",
  });
  assert.equal(hasContactFormErrors(errors), false);
});

// 回归：只输空格的必填字段必须被当成空。
// 不 trim 的话 " " 能通过校验，用户提交一封只有空格的信，
// 前端显示成功、后端收到一封空信，两边都不报错。
test("whitespace-only input does not satisfy a required field", () => {
  const errors = validateContactForm({
    name: "   ",
    email: "wei@example.com",
    company: "",
    message: "\n\t  ",
  });
  assert.equal(errors.name, "nameRequired");
  assert.equal(errors.message, "messageRequired");
});

test("isPlausibleEmail rejects the common typos", () => {
  assert.equal(isPlausibleEmail("wei@example.com"), true);
  assert.equal(isPlausibleEmail("wei.chen+tag@sub.example.co"), true);
  // 漏掉 @
  assert.equal(isPlausibleEmail("wei.example.com"), false);
  // 只有主机名没有域
  assert.equal(isPlausibleEmail("wei@company"), false);
  // 两个 @
  assert.equal(isPlausibleEmail("wei@@example.com"), false);
  // @ 一侧为空
  assert.equal(isPlausibleEmail("@example.com"), false);
  assert.equal(isPlausibleEmail("wei@"), false);
  // 域名的点在首尾
  assert.equal(isPlausibleEmail("wei@.com"), false);
  assert.equal(isPlausibleEmail("wei@example."), false);
  // 中间有空格（粘贴 "Name <a@b.com>" 时最常见）
  assert.equal(isPlausibleEmail("wei chen@example.com"), false);
});

// 设计约束：宽松优于严格。带 + 号、长顶级域这类合法但少见的地址不能被误杀，
// 因为被误杀的访客没有任何补救手段，只能放弃咨询。
test("isPlausibleEmail does not kill valid but unusual addresses", () => {
  assert.equal(isPlausibleEmail("a+b@example.engineering"), true);
  assert.equal(isPlausibleEmail("first.last@mail.example.com.sg"), true);
});

test("an over-long message is rejected rather than silently truncated", () => {
  const errors = validateContactForm({
    ...EMPTY_CONTACT_FORM,
    name: "Wei",
    email: "wei@example.com",
    message: "x".repeat(CONTACT_MESSAGE_MAX_LENGTH + 1),
  });
  assert.equal(errors.message, "messageTooLong");
});

test("a message exactly at the limit is accepted", () => {
  const errors = validateContactForm({
    ...EMPTY_CONTACT_FORM,
    name: "Wei",
    email: "wei@example.com",
    message: "x".repeat(CONTACT_MESSAGE_MAX_LENGTH),
  });
  assert.equal(hasContactFormErrors(errors), false);
});

// 渲染顺序和数据结构必须对齐，否则新加字段时会出现
// "字段存在于类型里、但页面上没有" 这种不报错的遗漏。
test("every form field appears exactly once in the render order", () => {
  const keys = Object.keys(EMPTY_CONTACT_FORM).sort();
  assert.deepEqual([...CONTACT_FIELD_ORDER].sort(), keys);
  assert.equal(new Set(CONTACT_FIELD_ORDER).size, CONTACT_FIELD_ORDER.length);
});
