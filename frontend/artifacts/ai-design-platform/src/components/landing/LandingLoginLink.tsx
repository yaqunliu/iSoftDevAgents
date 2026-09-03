/**
 * 接口注释：
 * 官网所有登录入口共用的链接元素（Hero 主 CTA、导航登录按钮、
 * 结尾 CTA 的 Open the platform、页脚的 Log in）。
 *
 * 原因注释：
 * 四个入口的目标地址必须一致，否则会出现"导航点进去是登录页、页脚点进去是别处"
 * 这种没人会主动去核对、但客户一定会遇到的不一致。
 *
 * 元素类型不能写死：地址是站内相对路径时要用 wouter 的 Link（SPA 跳转，无白屏），
 * 配了 VITE_APP_URL 变成跨域绝对地址时必须用原生 <a>（前端路由跳不出去）。
 * 把这个判断收在一个组件里，四个调用点就都不会选错。
 */

import type { ReactNode } from "react";
import { Link } from "wouter";

import { isExternalUrl, landingLoginUrl } from "@/lib/landing-app-url";

type LandingLoginLinkProps = {
  className?: string;
  children: ReactNode;
  /** 登录成功后回跳的产品内路径。留空走 landingLoginUrl 的默认值（产品首页）。 */
  next?: string;
};

export function LandingLoginLink({ className, children, next }: LandingLoginLinkProps) {
  const href = landingLoginUrl(next);

  if (isExternalUrl(href)) {
    // 跨域部署时才走到这里。不加 target="_blank"——登录是流程的延续，
    // 新开标签页会把访客留在一个已经读完的官网标签上，凭空多出一个待处理窗口。
    return (
      <a href={href} rel="noreferrer" className={className}>
        {children}
      </a>
    );
  }

  return (
    <Link href={href} className={className}>
      {children}
    </Link>
  );
}
