/**
 * 接口注释：
 * 官网 "Log in" / "Open the platform" 按钮的目标地址。
 *
 * 设计注释（2026-09 修订）：
 * 官网和产品现在同处一个前端应用、同一个域名——官网在 "/"，产品认证页在 "/auth"。
 * 所以默认行为已经从"跳到 app 子域"改成了"站内跳转 /auth"。
 *
 * 这个文件没有被删掉，是因为跨域的可能性仍然存在：官网将来若拆成独立站点、
 * 或者要从预发环境的官网指向生产的产品，都需要绝对地址。
 * 那种情况下构建时传 VITE_APP_URL 即可，组件侧一行都不用改。
 * 换句话说，这里保留的是一个开关，不是一段死代码。
 */

// 教学注释：相对 import 带上 .ts 后缀，这是本仓库的既有惯例
// （见 artifact-render-mode.ts、interaction-guidance.ts 等）。
// 原因是单测跑在 node 的 test runner 上，它按真实文件名解析模块，
// 省掉后缀会报 ERR_MODULE_NOT_FOUND；Vite 和 tsconfig 的
// allowImportingTsExtensions 都接受带后缀的写法。
import { APP_HOME_PATH } from "./app-routes.ts";

/**
 * 官网与产品分域部署时，产品所在的源。
 *
 * ⚠️ 这个值现在只作为 VITE_APP_URL 的文档示例存在，不再是静默兜底。
 * 原因注释：以前它是兜底值，于是"忘记配环境变量"的后果是按钮悄悄指向一个
 * 可能还不存在的子域——页面不报错，点了才发现打不开。
 * 改成不配就走站内之后，忘记配置的后果变成"站内跳转"，那是安全的默认。
 */
export const DEFAULT_APP_ORIGIN = "https://app.gmonkey.ai";

/** 产品认证页在应用内的路径。 */
export const APP_AUTH_PATH = "/auth";

export type BuildAppAuthUrlOptions = {
  /** 产品所在的源。留空表示同源，产出相对路径。 */
  origin?: string | null | undefined;
  /** 登录成功后回跳的产品内路径，必须以 "/" 开头。 */
  next?: string | null | undefined;
};

/**
 * 原因注释：
 * 环境变量在不同构建里可能带尾部斜杠（https://app.gmonkey.ai/），
 * 直接拼接会产出 //auth 这种双斜杠地址。这里统一削掉尾部斜杠。
 * 空值返回空串，代表"同源"，交给调用方拼成相对路径。
 */
function normalizeOrigin(origin: string | null | undefined): string {
  const trimmed = String(origin ?? "").trim();
  if (!trimmed) {
    return "";
  }
  return trimmed.replace(/\/+$/, "");
}

/**
 * 设计注释：
 * next 参数只接受站内绝对路径。这不是洁癖，而是防开放重定向：
 * 如果放任 next 传 https://evil.example，攻击者就能拿官网当跳板做钓鱼。
 * 认证页那边（resolveAppNextPath）也做了同样的校验，这里属于第二道防线。
 */
function normalizeNext(next: string | null | undefined): string | null {
  const trimmed = String(next ?? "").trim();
  if (!trimmed || !trimmed.startsWith("/")) {
    return null;
  }
  // 以 "//" 或 "/\" 开头的地址会被浏览器当成协议相对 URL，必须一并拦掉。
  if (trimmed.startsWith("//") || trimmed.startsWith("/\\")) {
    return null;
  }
  return trimmed;
}

/**
 * 拼出产品认证页地址。origin 为空时产出相对路径（同源）。
 */
export function buildAppAuthUrl(options: BuildAppAuthUrlOptions = {}): string {
  const origin = normalizeOrigin(options.origin);
  const next = normalizeNext(options.next);
  const base = `${origin}${APP_AUTH_PATH}`;
  if (!next) {
    return base;
  }
  return `${base}?next=${encodeURIComponent(next)}`;
}

/**
 * 读取构建时配置的产品源。没配就返回空串 = 同源。
 *
 * 教学注释：
 * import.meta.env 的读取集中在这一层，组件完全不用关心环境变量存在与否。
 * 类型上用可选索引访问，避免 VITE_APP_URL 没声明时 TS 报错。
 */
export function resolveAppOrigin(): string {
  const fromEnv = (import.meta.env as Record<string, string | undefined>)["VITE_APP_URL"];
  return normalizeOrigin(fromEnv);
}

/**
 * 官网各处登录按钮的最终地址。
 *
 * 原因注释：默认回跳目标是 APP_HOME_PATH 而不是 "/"。
 * "/" 现在是官网营销页，用它当 next 会让用户登录成功后又回到官网，
 * 看起来像"登录了但什么都没发生"。
 */
export function landingLoginUrl(next?: string): string {
  return buildAppAuthUrl({ origin: resolveAppOrigin(), next: next ?? APP_HOME_PATH });
}

/**
 * 判断一个地址是否会离开当前的前端路由。
 *
 * 教学注释：
 * 官网的登录链接现在多数时候是站内相对路径，应该走 wouter 的 Link 做 SPA 跳转——
 * 用 <a> 会整页刷新，白屏一次、React 重新挂载一次，体感上像是"网站重新加载了"。
 * 但配了 VITE_APP_URL 之后同一个地址会变成跨域绝对地址，那时必须用 <a>，
 * 因为前端路由跳不出自己的应用。所以链接元素要按地址形态动态选择。
 *
 * 判据写成"是不是以单个 / 开头"而不是匹配 https:// 这类协议头，
 * 因为要拦的东西比协议头多：mailto:、tel:、以及 //host 这种协议相对地址，
 * 它们都会离开前端路由，但只有最后一种长得像路径。用白名单比用黑名单可靠。
 */
export function isExternalUrl(url: string): boolean {
  return !url.startsWith("/") || url.startsWith("//") || url.startsWith("/\\");
}
