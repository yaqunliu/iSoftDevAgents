import test from "node:test";
import assert from "node:assert/strict";

import { resolveMermaidRuntime } from "./mermaid-runtime.ts";

function createRuntime() {
  return {
    initialize() {},
    render() {
      return { svg: "<svg />" };
    },
  };
}

test("resolveMermaidRuntime prefers window.mermaid when it exists", () => {
  const runtime = createRuntime();

  assert.equal(resolveMermaidRuntime({ mermaid: runtime }), runtime);
});

test("resolveMermaidRuntime reads the esbuild bundled default export shape", () => {
  const runtime = createRuntime();

  assert.equal(
    resolveMermaidRuntime({
      __esbuild_esm_mermaid_nm: {
        mermaid: {
          default: runtime,
        },
      },
    }),
    runtime,
  );
});

test("resolveMermaidRuntime accepts direct bundled mermaid objects too", () => {
  const runtime = createRuntime();

  assert.equal(
    resolveMermaidRuntime({
      __esbuild_esm_mermaid_nm: {
        mermaid: runtime,
      },
    }),
    runtime,
  );
});
