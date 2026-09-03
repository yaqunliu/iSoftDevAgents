/**
 * 接口注释：
 * 产品应用（需要登录的那部分）的首页路径。
 *
 * 原因注释：
 * 官网占用了 "/" 之后，产品首页搬到了 /app。这个路径散落在五个地方——
 * 路由表、登录成功回跳、未登录时的 next 参数、项目页返回、404 页返回。
 * 五处手写字符串意味着改路径时有五次漏改的机会，而漏改不会报错、不会白屏，
 * 只会把已登录用户安静地送到市场官网页，看起来像"点了返回结果退出登录了"。
 * 这类故障没有异常堆栈，只能靠人肉复现，所以路径必须只有一个来源。
 */

/** 产品应用首页（项目列表）。官网在 "/"，产品在这里。 */
export const APP_HOME_PATH = "/app";

/**
 * 把 next 参数收敛成一个安全的应用内路径。
 *
 * 设计注释：
 * 两件事在这里一起做，因为它们的失败方式相同——都会把用户送到错误的地方。
 *   1. 安全：只接受以单个 "/" 开头的相对路径。"//evil.com" 和 "https://evil.com"
 *      都会被浏览器当作跨站地址，是标准的开放重定向漏洞。
 *   2. 正确：next 是 "/" 时要改成 APP_HOME_PATH。"/" 现在是官网营销页，
 *      登录成功后把用户丢到官网是这次路径搬迁最容易踩的坑。
 */
export function resolveAppNextPath(rawNext: string | null | undefined): string {
  if (!rawNext) {
    return APP_HOME_PATH;
  }
  // 必须以 "/" 开头，且第二个字符不能是 "/" 或 "\"——
  // "//host" 和 "/\host" 在浏览器里都会被解析成协议相对的跨站地址。
  if (!rawNext.startsWith("/") || rawNext[1] === "/" || rawNext[1] === "\\") {
    return APP_HOME_PATH;
  }
  if (rawNext === "/") {
    return APP_HOME_PATH;
  }
  return rawNext;
}
