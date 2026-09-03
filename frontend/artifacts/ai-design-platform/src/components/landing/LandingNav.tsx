/**
 * 接口注释：
 * 官网顶部导航。固定在视口顶部，高度与 NAV_SCROLL_OFFSET 保持一致。
 *
 * 设计注释：
 * 参考稿 SYMPHONY 的导航是"三段式 + 一条 1px 下边框"：左侧字标、中间四项链接、
 * 右侧一个操作按钮。那条下边框不是装饰——整站的区块切分全靠 1px 细线而不是阴影，
 * 导航这条线是这套语言的第一次出场，所以不能换成投影或者渐变。
 */

import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "wouter";

import {
  NAV_ITEMS,
  NAV_SCROLL_OFFSET,
  scrollToSection,
  type LandingSectionId,
} from "@/lib/landing-nav-sections";

import { LandingLoginLink } from "./LandingLoginLink";

/**
 * 导航项的样式。
 *
 * 原因注释：抽成常量是因为同一套外观现在要同时用在 <button>（锚点项）
 * 和 <Link>（跳转项）上。写两遍的话，将来调间距或颜色改了一处漏一处，
 * 页面上就会出现两个看起来"差一点点"的导航项——这种差异没人会当成 bug 报，
 * 但它会一直在那里。
 */
const NAV_LINK_CLASS =
  "text-[0.7rem] uppercase tracking-[0.18em] text-[var(--lp-muted)] transition-colors duration-300 hover:text-[var(--lp-ink)]";

export function LandingNav() {  const { t } = useTranslation();
  const [hasScrolled, setHasScrolled] = useState(false);

  /**
   * 原因注释：
   * 导航一开始是完全透明的，让 Hero 的网格能连续铺到屏幕最上沿；
   * 一旦开始滚动就加上底色和毛玻璃，否则正文会从导航文字底下穿过去，两层字叠在一起没法读。
   * 阈值取 8px 而不是 0，是为了避开触控板的橡皮筋回弹反复触发状态切换。
   */
  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    const handleScroll = () => {
      setHasScrolled(window.scrollY > 8);
    };
    handleScroll();
    window.addEventListener("scroll", handleScroll, { passive: true });
    return () => {
      window.removeEventListener("scroll", handleScroll);
    };
  }, []);

  const handleNavClick = (sectionId: LandingSectionId) => {
    scrollToSection(sectionId);
  };

  return (
    <header
      className={`fixed inset-x-0 top-0 z-50 transition-[background-color,backdrop-filter,border-color] duration-500 ${
        hasScrolled
          ? "border-b border-[var(--lp-border)] bg-[var(--lp-bg-blur)] backdrop-blur-md"
          : "border-b border-transparent bg-transparent"
      }`}
      style={{ height: `${NAV_SCROLL_OFFSET}px` }}
    >
      {/* 无障碍：键盘用户第一个 Tab 就能跳过导航直达正文，
          否则每次进页面都要按四五次 Tab 才能读到内容。 */}
      <a
        href="#lp-main"
        className="sr-only focus:not-sr-only focus:absolute focus:left-6 focus:top-4 focus:z-50 focus:rounded-full focus:bg-[var(--lp-accent)] focus:px-4 focus:py-2 focus:text-xs focus:text-white"
      >
        {t("lp.nav.skipToContent")}
      </a>

      <div className="mx-auto flex h-full max-w-[1440px] items-center justify-between px-6 md:px-10">
        {/* 字标。设计注释：产品名用 display 字体、weight 400——
            参考稿的标题全部是 400 而不是 700，"细字大字号"是这套排版的识别点，
            换成粗体就立刻变成普通 SaaS 站。 */}
        <a
          href="#lp-main"
          onClick={(event) => {
            event.preventDefault();
            window.scrollTo({ top: 0, behavior: "smooth" });
          }}
          className="flex items-baseline gap-3"
        >
          <span className="lp-display text-lg font-normal tracking-[-0.02em] text-[var(--lp-ink)]">
            gmonkey<span className="text-[var(--lp-muted)]">.ai</span>
          </span>
          {/* 公司名在导航里只作为背书出现，字号压到最小、颜色压到 muted。
              企业客户会找"这是谁做的"，但产品名必须是视觉主体。 */}
          <span className="hidden text-[0.65rem] uppercase tracking-[0.18em] text-[var(--lp-muted)] lg:inline">
            GorillaBits
          </span>
        </a>

        <nav className="hidden items-center gap-9 md:flex">
          {/* 教学注释：这里按 item.kind 分派，而不是"如果 key 是 contact 就特殊处理"。
              差异编码在类型里，将来再加第二个跳转类入口时，
              漏写分支会被 TypeScript 在编译期拦下，而不是上线后才发现点了没反应。

              锚点项只在首页有效（法务页和 Contact 页不渲染这条导航），
              所以这里不需要处理"锚点不在当前页"的情况。 */}
          {NAV_ITEMS.map((item) =>
            item.kind === "route" ? (
              <Link
                key={item.key}
                href={item.href}
                className={NAV_LINK_CLASS}
              >
                {t(`lp.nav.${item.key}`)}
              </Link>
            ) : (
              <button
                key={item.key}
                type="button"
                onClick={() => handleNavClick(item.key)}
                className={NAV_LINK_CLASS}
              >
                {t(`lp.nav.${item.key}`)}
              </button>
            ),
          )}
        </nav>

        {/* 登录入口。指向站内的产品认证页 /auth。
            圆角 100px 的胶囊按钮是参考稿的按钮语言，全站主 CTA 都用这个形状。 */}
        <LandingLoginLink className="rounded-full bg-[var(--lp-accent)] px-5 py-2.5 text-[0.8rem] tracking-[0.02em] text-white transition-opacity duration-300 hover:opacity-85">
          {t("lp.nav.login")}
        </LandingLoginLink>
      </div>
    </header>
  );
}
