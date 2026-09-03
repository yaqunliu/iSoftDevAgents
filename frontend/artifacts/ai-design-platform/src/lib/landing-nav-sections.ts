/**
 * 接口注释：
 * 官网是单页长滚动结构，导航靠锚点跳转。这里集中定义所有区块的 id、
 * 以及哪些区块要出现在顶部导航里。
 *
 * 设计注释：
 * 区块 id 在导航、锚点滚动、以及各区块组件里都要用到。
 * 如果散落在 JSX 字符串里，改一个 id 就会出现"导航点了没反应"这类静默故障——
 * 因为拼错的锚点不会报错，只会什么都不发生。集中成常量后，
 * 拼错的 id 会在编译期被 TypeScript 拦下来。
 */

// 教学注释：相对 import 带 .ts 后缀是本仓库惯例，单测跑在 node 的 test runner 上，
// 它按真实文件名解析模块，省掉后缀会报 ERR_MODULE_NOT_FOUND。
import { LANDING_ROUTES } from "./landing-cta.ts";

export const LANDING_SECTION_IDS = [
  "pipeline",
  "control",
  "observability",
  "views",
  "stack",
  "roadmap",
  "company",
  // 原因注释：这个区块以前叫 "contact"，现在改叫 "cta"。
  // 改名是因为 Contact 已经成了一个独立页面（/contact），
  // 再让首页底部的收尾区块占着同一个名字，就会出现
  // "导航的 Contact 跳页面、页脚的 Contact 滚锚点" 这种同名不同义，
  // 而这种不一致不会报错，只会让后来改代码的人跳错地方。
  "cta",
] as const;

export type LandingSectionId = (typeof LANDING_SECTION_IDS)[number];

/**
 * 首页内部锚点区块的完整列表，页脚 Product 那一列消费它。
 *
 * 这个数组只包含"同页锚点"，不含跳转到独立页面的项。
 * 页脚也会出现在 /terms、/privacy、/contact 这些没有这些锚点的页面上——
 * 所以它必须保持纯锚点语义，跳转类的入口另外单独渲染。
 */
export const NAV_SECTIONS: LandingSectionId[] = ["pipeline", "observability", "stack", "company"];

/**
 * 顶部导航实际渲染的锚点，是 NAV_SECTIONS 的子集。
 *
 * 原因注释：
 * 为什么顶部和页脚要用两个数组，而不是共用 NAV_SECTIONS？
 * 因为两者的约束根本不同。顶部导航是一条横排，宽度有限，
 * "Observability" 这个词本身就长，加上 Contact 之后整条导航挤到影响观感，
 * 所以顶部把它去掉了。页脚是纵向列表，不存在挤的问题。
 *
 * 关键是 #observability 区块本身仍然存在于首页上。如果两处共用一个数组，
 * 为了让顶部变短就得把它从页脚也删掉，那这个区块就再没有任何直达入口，
 * 只能靠访客一路往下滚才碰得到。拆成两个数组的成本是多一行常量，
 * 收益是顶部的排版约束不会反过来砍掉页脚的可达性。
 *
 * 维护约束：这里的每一项都必须同时出现在 NAV_SECTIONS 里（有单测钉住）。
 * 想在顶部加一项，先确认它在页脚也有——否则会出现"顶部能点、页脚找不到"的不一致。
 */
export const TOP_NAV_SECTIONS: LandingSectionId[] = ["pipeline", "stack", "company"];

/**
 * 顶部导航的完整项目表：三个同页锚点 + 一个跳转到 /contact 的路由项。
 *
 * 设计注释：
 * 为什么要引入这个带 kind 的联合类型，而不是往 TOP_NAV_SECTIONS 里塞一个 "contact"？
 * 因为这两类导航项的行为根本不同：锚点项要平滑滚动并扣掉导航高度，
 * 路由项要走 wouter 的 Link 做 SPA 跳转。
 * 如果混在同一个字符串数组里，渲染方只能靠"如果 id 等于 contact 就特殊处理"
 * 这种硬编码分支来区分，下一个人加第二个路由项时一定会漏掉那个分支。
 * 把差异编码进类型，TypeScript 会在渲染方漏处理某个 kind 时直接报错。
 */
export type LandingNavItem =
  | { kind: "section"; key: LandingSectionId }
  | { kind: "route"; key: "contact"; href: string };

export const NAV_ITEMS: LandingNavItem[] = [
  ...TOP_NAV_SECTIONS.map((key): LandingNavItem => ({ kind: "section", key })),
  { kind: "route", key: "contact", href: LANDING_ROUTES.contact },
];

/**
 * 平滑滚动到指定区块。
 *
 * 原因注释：
 * 顶部导航是 sticky 的，浏览器原生的 scrollIntoView 会把目标区块顶到视口最上沿，
 * 结果标题正好被导航条盖住。所以这里手动算偏移，扣掉导航高度。
 */
export const NAV_SCROLL_OFFSET = 88;

export function scrollToSection(sectionId: LandingSectionId, offset: number = NAV_SCROLL_OFFSET): void {
  if (typeof document === "undefined") {
    return;
  }
  const element = document.getElementById(sectionId);
  if (!element) {
    return;
  }
  const top = element.getBoundingClientRect().top + window.scrollY - offset;
  window.scrollTo({ top, behavior: "smooth" });
}

/**
 * 把鼠标坐标换算成聚焦遮罩需要的百分比位置。
 *
 * 设计注释：
 * 网格聚焦遮罩用的是 radial-gradient(circle at X% Y%)，需要百分比而不是像素，
 * 这样元素尺寸变化时光圈位置仍然正确。抽成纯函数是为了能直接测边界情况——
 * 尤其是宽或高为 0 时（元素还没布局完成），必须避免除零产出 NaN，
 * 否则 CSS 变量会被写成 "NaN%"，遮罩直接失效、整片网格消失。
 */
export function toMaskPercent(value: number, extent: number): number {
  if (!Number.isFinite(value) || !Number.isFinite(extent) || extent <= 0) {
    return 50;
  }
  const percent = (value / extent) * 100;
  return Math.min(Math.max(percent, -20), 120);
}

/**
 * 光标缓动追赶的一步计算。
 *
 * 教学注释：
 * 这就是参考稿 Sanctuary 里那个 `cursorX += (mouseX - cursorX) * ease` 的公式，
 * 也叫线性插值（lerp）。每一帧只走剩余距离的一小部分，
 * 于是环会"追"着鼠标跑而不是黏在鼠标上——这份滑动惯性正是原稿手感的来源。
 * ease 取 0.12 比原稿的 0.1 略快，因为官网是长滚动页面，
 * 环追得太慢会在快速滚动时明显掉队。
 */
export const CURSOR_EASE = 0.12;

export function easeToward(current: number, target: number, ease: number = CURSOR_EASE): number {
  if (!Number.isFinite(current) || !Number.isFinite(target)) {
    return Number.isFinite(target) ? target : 0;
  }
  const factor = Math.min(Math.max(ease, 0), 1);
  return current + (target - current) * factor;
}
