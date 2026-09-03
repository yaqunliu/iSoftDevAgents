import test from "node:test";
import assert from "node:assert/strict";

import { buildProjectWebSocketUrl } from "./project-websocket-url.ts";

test("空的 API 基础地址会回退到当前页面 origin 来构造 WebSocket 地址", () => {
  const result = buildProjectWebSocketUrl({
    apiBaseUrl: "",
    projectId: "project-123",
    accessToken: "token-abc",
    currentOrigin: "http://localhost:3000",
  });

  assert.equal(result, "ws://localhost:3000/api/projects/project-123/ws?access_token=token-abc");
});

test("https API 基础地址会自动切换成 wss 协议", () => {
  const result = buildProjectWebSocketUrl({
    apiBaseUrl: "https://demo.example.com/",
    projectId: "project-456",
    accessToken: "token-xyz",
  });

  assert.equal(result, "wss://demo.example.com/api/projects/project-456/ws?access_token=token-xyz");
});
