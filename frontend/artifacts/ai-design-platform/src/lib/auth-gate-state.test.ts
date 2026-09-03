import test from "node:test";
import assert from "node:assert/strict";

import { resolveAuthGateState } from "./auth-gate-state.ts";

test("resolveAuthGateState keeps the page in loading only while auth is still fetching", () => {
  assert.deepEqual(
    resolveAuthGateState({
      hasToken: true,
      hasCurrentUser: false,
      isLoading: true,
      isFetching: false,
      hasError: false,
    }),
    { screen: "loading" },
  );
});

test("resolveAuthGateState shows an error screen when the backend stops responding", () => {
  assert.deepEqual(
    resolveAuthGateState({
      hasToken: true,
      hasCurrentUser: false,
      isLoading: false,
      isFetching: false,
      hasError: true,
    }),
    { screen: "error" },
  );
});
