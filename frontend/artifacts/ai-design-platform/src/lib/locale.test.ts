import test from "node:test";
import assert from "node:assert/strict";

import {
  backendLocaleForLanguage,
  dateLocaleForLanguage,
  moduleTranslationLocaleForLanguage,
  normalizeSupportedLocale,
  SUPPORTED_LANGUAGE_OPTIONS,
} from "./locale.ts";

test("normalizeSupportedLocale supports all configured languages and browser-style locale strings", () => {
  assert.equal(normalizeSupportedLocale("zh-CN"), "en");
  assert.equal(normalizeSupportedLocale("en-US"), "en");
  assert.equal(normalizeSupportedLocale("ja-JP"), "ja");
  assert.equal(normalizeSupportedLocale("ko-KR"), "ko");
  assert.equal(normalizeSupportedLocale("ru-RU"), "ru");
  assert.equal(normalizeSupportedLocale("fr-FR"), "fr");
  assert.equal(normalizeSupportedLocale("de-DE"), "de");
  assert.equal(normalizeSupportedLocale("pt-BR"), "en");
  assert.equal(normalizeSupportedLocale(null), "en");
});

test("SUPPORTED_LANGUAGE_OPTIONS exposes the full dropdown language set in the expected order", () => {
  assert.deepEqual(
    SUPPORTED_LANGUAGE_OPTIONS.map((item) => item.value),
    ["en", "ja", "ko", "ru", "fr", "de"],
  );
});

test("backendLocaleForLanguage keeps backend requests compatible while extra frontend languages are enabled", () => {
  assert.equal(backendLocaleForLanguage("zh"), "en");
  assert.equal(backendLocaleForLanguage("ja"), "en");
  assert.equal(backendLocaleForLanguage("ko"), "en");
  assert.equal(backendLocaleForLanguage("ru"), "en");
});

test("moduleTranslationLocaleForLanguage follows the full supported locale set", () => {
  assert.equal(moduleTranslationLocaleForLanguage("zh"), "en");
  assert.equal(moduleTranslationLocaleForLanguage("fr"), "fr");
  assert.equal(moduleTranslationLocaleForLanguage("ja-JP"), "ja");
});

test("dateLocaleForLanguage chooses a native browser locale for each supported language", () => {
  assert.equal(dateLocaleForLanguage("zh"), "en-US");
  assert.equal(dateLocaleForLanguage("en"), "en-US");
  assert.equal(dateLocaleForLanguage("ja"), "ja-JP");
  assert.equal(dateLocaleForLanguage("ko"), "ko-KR");
  assert.equal(dateLocaleForLanguage("ru"), "ru-RU");
  assert.equal(dateLocaleForLanguage("fr"), "fr-FR");
  assert.equal(dateLocaleForLanguage("de"), "de-DE");
});
