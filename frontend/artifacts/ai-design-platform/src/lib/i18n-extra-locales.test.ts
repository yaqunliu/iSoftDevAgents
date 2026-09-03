import test from "node:test";
import assert from "node:assert/strict";

import { baseLocaleResources } from "../i18n.ts";
import { extraLocaleResources } from "./i18n-extra-locales.ts";

function sortedKeys(record: Record<string, string>): string[] {
  return Object.keys(record).sort();
}

test("extra locale translation dictionaries keep the same keys as the English base copy", () => {
  const englishKeys = sortedKeys(baseLocaleResources.en.translation as Record<string, string>);

  for (const [locale, resource] of Object.entries(extraLocaleResources)) {
    assert.deepEqual(
      sortedKeys(resource.translation as Record<string, string>),
      englishKeys,
      `locale ${locale} is missing or adding translation keys`,
    );
  }
});
