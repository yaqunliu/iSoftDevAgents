import test from "node:test";
import assert from "node:assert/strict";

import { RequestTimeoutError, fetchWithTimeout } from "./api-request.ts";

test("fetchWithTimeout aborts a hung request and returns a timeout error", async () => {
  const startedSignals: AbortSignal[] = [];

  const fetchImpl = async (_input: RequestInfo | URL, init?: RequestInit): Promise<Response> =>
    new Promise<Response>((_resolve, reject) => {
      const signal = init?.signal;
      if (!signal) {
        reject(new Error("signal is required"));
        return;
      }
      startedSignals.push(signal);
      signal.addEventListener("abort", () => {
        reject(new DOMException("The operation was aborted.", "AbortError"));
      });
    });

  await assert.rejects(
    () =>
      fetchWithTimeout({
        url: "http://example.test/api/projects/demo",
        timeoutMs: 20,
        fetchImpl,
      }),
    (error: unknown) => {
      assert.ok(error instanceof RequestTimeoutError);
      assert.match(error.message, /timed out/i);
      return true;
    },
  );

  assert.equal(startedSignals.length, 1);
  assert.equal(startedSignals[0]?.aborted, true);
});
