/**
 * 接口注释：
 * 官网所有对外落点（邮箱、法务页）集中在这里。
 *
 * 原因注释：
 * 集中成一个文件而不是散在九个组件的 href 里，是为了后面接真实地址时
 * 只改这一处。散着写的话，漏掉一个按钮不会报错、不会白屏，
 * 只会安静地把访客送到一个不存在的地址，而且通常是转化率最高的那个按钮。
 *
 * 登录入口不在这里——它由 lib/landing-app-url.ts 的 landingLoginUrl 负责，
 * 组件侧统一走 components/landing/LandingLoginLink.tsx。
 * 分开的理由是登录地址还要决定链接元素的类型（站内 Link 还是跨域 <a>），
 * 那是一段有行为的逻辑，不属于这个纯常量文件。
 */

/** 客服邮箱。 */
export const SUPPORT_EMAIL = "support@gmonkey.ai";

/** 邮件咨询。mailto 里带上主题，客服那边好分流。 */
export function ctaEmailHref(): string {
  const subject = encodeURIComponent("gmonkey.ai enquiry");
  return `mailto:${SUPPORT_EMAIL}?subject=${subject}`;
}

/**
 * 官网内部路由。
 *
 * 设计注释：写成常量而不是在 JSX 里手打字符串，是因为 wouter 的 Link
 * 对不存在的路径不会报错，只会渲染出一个点了跳到 404 的链接。
 * 页脚有三处引用这些路径，手打三遍就有三次拼错的机会。
 */
export const LANDING_ROUTES = {
  // 官网已占用根路径。产品首页在 lib/app-routes.ts 的 APP_HOME_PATH。
  home: "/",
  terms: "/terms",
  privacy: "/privacy",
  contact: "/contact",
} as const;
