import test from "node:test";
import assert from "node:assert/strict";

import { buildProjectsQueryKey } from "./projects-query-key.ts";

test("buildProjectsQueryKey uses authScope so different accounts do not share the same project cache", () => {
  const accountAKey = buildProjectsQueryKey({
    authScope: "token-a",
    search: "",
    page: 1,
    limit: 12,
  });
  const accountBKey = buildProjectsQueryKey({
    authScope: "token-b",
    search: "",
    page: 1,
    limit: 12,
  });

  assert.notDeepEqual(accountAKey, accountBKey);
});

test("buildProjectsQueryKey trims search text to avoid duplicated cache entries for the same query", () => {
  const spacedKey = buildProjectsQueryKey({
    authScope: "token-a",
    search: "  demo  ",
    page: 2,
    limit: 12,
  });
  const trimmedKey = buildProjectsQueryKey({
    authScope: "token-a",
    search: "demo",
    page: 2,
    limit: 12,
  });

  assert.deepEqual(spacedKey, trimmedKey);
});
