import test from "node:test";
import assert from "node:assert/strict";

import { resolveLiveQueryRefetchInterval } from "./live-query-interval.ts";

test("任务运行中和等待确认时开启兜底轮询", () => {
  assert.equal(resolveLiveQueryRefetchInterval("running"), 2500);
  assert.equal(resolveLiveQueryRefetchInterval("waiting_user"), 2500);
});

test("任务结束后关闭兜底轮询", () => {
  assert.equal(resolveLiveQueryRefetchInterval("completed"), false);
  assert.equal(resolveLiveQueryRefetchInterval("failed"), false);
  assert.equal(resolveLiveQueryRefetchInterval("cancelled"), false);
  assert.equal(resolveLiveQueryRefetchInterval("idle"), false);
  assert.equal(resolveLiveQueryRefetchInterval(null), false);
});
