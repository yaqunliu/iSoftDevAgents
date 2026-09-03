import test from "node:test";
import assert from "node:assert/strict";

import {
  CURSOR_EASE,
  easeToward,
  LANDING_SECTION_IDS,
  NAV_ITEMS,
  NAV_SECTIONS,
  TOP_NAV_SECTIONS,
  toMaskPercent,
} from "./landing-nav-sections.ts";

test("NAV_SECTIONS only points at section ids that actually exist on the page", () => {
  for (const section of NAV_SECTIONS) {
    assert.ok(
      LANDING_SECTION_IDS.includes(section),
      `nav entry ${section} has no matching section id`,
    );
  }
});

// 教学注释：企业站导航超过五项就会被整体忽略，所以这条约束值得用测试钉住。
test("NAV_SECTIONS stays short enough to be read rather than ignored", () => {
  assert.ok(NAV_SECTIONS.length <= 5, "top nav should keep at most five entries");
});

test("LANDING_SECTION_IDS contains no duplicates so anchors stay unambiguous", () => {
  assert.equal(new Set(LANDING_SECTION_IDS).size, LANDING_SECTION_IDS.length);
});

// NAV_ITEMS 里的锚点项必须和 TOP_NAV_SECTIONS 完全一致。
// 两者一旦漂移，NAV_ITEMS 就会渲染出一个 TOP_NAV_SECTIONS 里没有的入口，
// 而"顶部导航该放什么"这个决定本来只应该由 TOP_NAV_SECTIONS 表达。
test("NAV_ITEMS keeps its anchor entries in sync with TOP_NAV_SECTIONS", () => {
  const anchors = NAV_ITEMS.filter((item) => item.kind === "section").map((item) => item.key);
  assert.deepEqual(anchors, TOP_NAV_SECTIONS);
});

// 关键约束：顶部导航是页脚的子集，不是另一份独立清单。
// 如果有人只往 TOP_NAV_SECTIONS 加一项而忘了 NAV_SECTIONS，
// 就会出现"顶部能点进去、页脚却找不到这一项"的不一致，
// 而且不报错——正是需要用测试钉死的那类静默漂移。
test("TOP_NAV_SECTIONS is a subset of the footer's anchor list", () => {
  for (const section of TOP_NAV_SECTIONS) {
    assert.ok(
      NAV_SECTIONS.includes(section),
      `${section} is in the top nav but missing from the footer's Product column`,
    );
  }
});

// 回归：Observability 只是从顶部横排里拿掉了，区块和页脚入口都还在。
// 如果哪天有人"顺手"把它从 NAV_SECTIONS 也删掉，这个区块就再没有任何直达入口。
test("Observability stays reachable from the footer even though the top nav drops it", () => {
  assert.ok(!TOP_NAV_SECTIONS.includes("observability"));
  assert.ok(NAV_SECTIONS.includes("observability"));
  assert.ok(LANDING_SECTION_IDS.includes("observability"));
});

// 回归：Contact 是独立页面，不是同页锚点。
// 如果哪天有人把它改回 kind: "section"，导航会去找一个不存在的 #contact，
// 点击后页面纹丝不动、控制台也不报错——正是最难排查的那类故障。
test("the Contact entry is a route, not an anchor, and points at a real page path", () => {
  const contact = NAV_ITEMS.find((item) => item.key === "contact");
  assert.ok(contact, "Contact entry is missing from the top nav");
  assert.equal(contact.kind, "route");
  assert.equal(contact.kind === "route" ? contact.href : null, "/contact");
  assert.ok(
    !LANDING_SECTION_IDS.includes(contact.key as never),
    "contact must not double as a section id",
  );
});

test("NAV_ITEMS stays short enough to be read rather than ignored", () => {
  assert.ok(NAV_ITEMS.length <= 5, "top nav should keep at most five entries");
});

test("toMaskPercent converts pointer coordinates into gradient percentages", () => {
  assert.equal(toMaskPercent(0, 1000), 0);
  assert.equal(toMaskPercent(500, 1000), 50);
  assert.equal(toMaskPercent(1000, 1000), 100);
});

// 边界回归：元素尚未完成布局时宽高为 0，除零会写出 "NaN%"，
// 那会让整条 mask-image 失效、Hero 的网格直接消失。
test("toMaskPercent never produces NaN for unlaid-out elements", () => {
  assert.equal(toMaskPercent(120, 0), 50);
  assert.equal(toMaskPercent(Number.NaN, 800), 50);
  assert.equal(toMaskPercent(120, Number.NaN), 50);
});

test("toMaskPercent clamps far-out values to keep the spotlight near the viewport", () => {
  assert.equal(toMaskPercent(-9999, 1000), -20);
  assert.equal(toMaskPercent(9999, 1000), 120);
});

test("easeToward moves partway toward the target to produce trailing motion", () => {
  assert.equal(easeToward(0, 100, 0.5), 50);
  assert.equal(easeToward(50, 100, 0.5), 75);
  // ease 为 1 表示立即到位，为 0 表示完全不动。
  assert.equal(easeToward(0, 100, 1), 100);
  assert.equal(easeToward(0, 100, 0), 0);
});

test("easeToward tolerates non-finite input instead of poisoning the animation loop", () => {
  assert.equal(easeToward(Number.NaN, 100), 100);
  assert.equal(easeToward(10, Number.NaN), 0);
});

test("CURSOR_EASE keeps the ring trailing but not lagging on long scrolls", () => {
  assert.ok(CURSOR_EASE > 0 && CURSOR_EASE < 1);
});
