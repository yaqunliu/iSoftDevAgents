import test from "node:test";
import assert from "node:assert/strict";

import { baseLocaleResources } from "../i18n.ts";

test("runtime log translations only keep the elapsed label", () => {
  const english = baseLocaleResources.en.translation;
  const chinese = baseLocaleResources.zh.translation;

  assert.equal(english["chat.logFrame.runtime.elapsed"], "Elapsed");
  assert.equal(chinese["chat.logFrame.runtime.elapsed"], "已运行");

  assert.equal("chat.logFrame.runtime.title" in english, false);
  assert.equal("chat.logFrame.runtime.pid" in english, false);
  assert.equal("chat.logFrame.runtime.state" in english, false);
  assert.equal("chat.logFrame.runtime.idle" in english, false);
  assert.equal("chat.logFrame.runtime.summary.running" in english, false);
  assert.equal("chat.logFrame.runtime.title" in chinese, false);
  assert.equal("chat.logFrame.runtime.pid" in chinese, false);
  assert.equal("chat.logFrame.runtime.state" in chinese, false);
  assert.equal("chat.logFrame.runtime.idle" in chinese, false);
  assert.equal("chat.logFrame.runtime.summary.running" in chinese, false);
});
