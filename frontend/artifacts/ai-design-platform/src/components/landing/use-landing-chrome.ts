/**
 * 接口注释：
 * 官网三个页面（/landing、/terms、/privacy）共用的"页面外壳"副作用：
 * 切换到浅色主题、设置标题、进入时回到页首。
 *
 * 原因注释：
 * 这三件事必须在同一个地方成对做（进入时设置、离开时还原），
 * 分散到各页面里迟早会漏掉一处清理，症状是"从官网点进产品后产品变成了白底"——
 * 而且只在特定跳转路径下出现，很难复现。集中成一个 hook 是唯一可靠的做法。
 */

import { useEffect } from "react";

/**
 * 设计注释：
 * data-lp-root 是整套浅色/深色隔离的开关，挂在 <html> 上。
 * landing.css 里所有接管全局外观的规则（body 底色、字体、滚动条）都写在
 * html[data-lp-root] 之下，所以这个属性一移除，产品的深色主题就自动完整恢复，
 * 不需要任何逆向的"改回去"逻辑。产品的 Tailwind token（--color-*）
 * 从头到尾没被碰过，60 多个 shadcn 组件因此零风险。
 */
const LP_ROOT_ATTRIBUTE = "data-lp-root";

export function useLandingChrome(pageTitle: string): void {
  useEffect(() => {
    if (typeof document === "undefined") {
      return;
    }

    const root = document.documentElement;
    const previousTitle = document.title;

    root.setAttribute(LP_ROOT_ATTRIBUTE, "");
    document.title = pageTitle;

    // 原因注释：wouter 的路由切换不会重置滚动位置。
    // 从产品页某个滚到一半的位置点到条款页，会直接落在条款正文中段，
    // 看起来像页面加载错误。这里显式回到页首。
    window.scrollTo({ top: 0, behavior: "auto" });

    return () => {
      root.removeAttribute(LP_ROOT_ATTRIBUTE);
      document.title = previousTitle;
    };
  }, [pageTitle]);
}
