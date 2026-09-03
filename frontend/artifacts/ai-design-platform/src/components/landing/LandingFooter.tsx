/**
 * 接口注释：
 * 页脚。四栏链接 + 一行公司法定信息。
 *
 * 设计注释：
 * 页脚是官网上唯一需要承载"这家公司是真实存在的"这个信息的地方：
 * 法定名称、注册地、联系邮箱。企业客户在决定是否发第一封询价邮件之前
 * 通常会先滚到底看这一行。所以底部那条信息不用最小号字，也不刻意压灰。
 *
 * 变更记录：2026-09-03 去掉了 UEN 注册号。之前是留空 + 条件渲染的占位，
 * 现在明确不放。如果将来要补上，注意别只在这里加一行字符串——
 * 注册号是访客拿去 ACRA/BizFile 核实公司的入口，填错一位查不到，
 * 可信度的损失比不填更大，所以务必用真实号码。
 */

import { useTranslation } from "react-i18next";
import { Link } from "wouter";

import { ctaEmailHref, LANDING_ROUTES, SUPPORT_EMAIL } from "@/lib/landing-cta";
import { NAV_SECTIONS, scrollToSection } from "@/lib/landing-nav-sections";

import { LandingLoginLink } from "./LandingLoginLink";

export function LandingFooter() {
  const { t } = useTranslation();

  return (
    <footer className="bg-[var(--lp-bg)]">
      <div className="mx-auto max-w-[1440px] px-6 pb-16 pt-20 md:px-10">
        <div className="grid grid-cols-2 gap-10 border-t border-[var(--lp-border)] pt-12 md:grid-cols-4 md:gap-12">
          {/* 第一栏：品牌 + 一句主张 */}
          <div className="col-span-2 md:col-span-1">
            <p className="lp-display text-base tracking-[-0.02em] text-[var(--lp-ink)]">gmonkey.ai</p>
            <p className="mt-4 max-w-[240px] text-[0.82rem] leading-[1.8] text-[var(--lp-muted)]">
              {t("lp.footer.tagline")}
            </p>
          </div>

          {/* 第二栏：产品内部锚点。
              教学注释：这些是同页锚点，所以用 button + 平滑滚动而不是 <a href="#id">。
              原生锚点会瞬间跳过去，且目标标题会被 fixed 导航条盖住——
              scrollToSection 已经扣掉了导航高度。 */}
          <nav aria-label={t("lp.footer.product")}>
            <p className="text-[0.66rem] uppercase tracking-[0.18em] text-[var(--lp-muted)]">
              {t("lp.footer.product")}
            </p>
            <ul className="mt-5 space-y-3">
              {NAV_SECTIONS.map((section) => (
                <li key={section}>
                  <button
                    type="button"
                    onClick={() => scrollToSection(section)}
                    className="text-[0.85rem] text-[var(--lp-ink)] transition-colors duration-300 hover:text-[var(--lp-muted)]"
                  >
                    {t(`lp.nav.${section}`)}
                  </button>
                </li>
              ))}
              <li>
                <LandingLoginLink className="text-[0.85rem] text-[var(--lp-ink)] transition-colors duration-300 hover:text-[var(--lp-muted)]">
                  {t("lp.footer.login")}
                </LandingLoginLink>
              </li>
            </ul>
          </nav>

          {/* 第三栏：法务页。这两个是真实的站内路由，不是占位。 */}
          <nav aria-label={t("lp.footer.legal")}>
            <p className="text-[0.66rem] uppercase tracking-[0.18em] text-[var(--lp-muted)]">
              {t("lp.footer.legal")}
            </p>
            <ul className="mt-5 space-y-3">
              <li>
                <Link
                  href={LANDING_ROUTES.terms}
                  className="text-[0.85rem] text-[var(--lp-ink)] transition-colors duration-300 hover:text-[var(--lp-muted)]"
                >
                  {t("lp.footer.terms")}
                </Link>
              </li>
              <li>
                <Link
                  href={LANDING_ROUTES.privacy}
                  className="text-[0.85rem] text-[var(--lp-ink)] transition-colors duration-300 hover:text-[var(--lp-muted)]"
                >
                  {t("lp.footer.privacy")}
                </Link>
              </li>
            </ul>
          </nav>

          {/* 第四栏：联系方式。邮箱直接显示出来而不是只藏在"联系我们"按钮后面——
              企业客户常常要把地址复制进自己的邮件系统。
              上面再给一条通往 /contact 表单页的链接，两条通路并列，访客挑顺手的那条。 */}
          <div>
            <p className="text-[0.66rem] uppercase tracking-[0.18em] text-[var(--lp-muted)]">
              {t("lp.footer.contact")}
            </p>
            <Link
              href={LANDING_ROUTES.contact}
              className="mt-5 block text-[0.85rem] text-[var(--lp-ink)] transition-colors duration-300 hover:text-[var(--lp-muted)]"
            >
              {t("lp.nav.contact")}
            </Link>
            <a
              href={ctaEmailHref()}
              className="lp-mono mt-3 block text-[0.82rem] text-[var(--lp-ink)] transition-colors duration-300 hover:text-[var(--lp-muted)]"
            >
              {SUPPORT_EMAIL}
            </a>
          </div>
        </div>

        {/* 法定信息行 */}
        <div className="mt-16 flex flex-col gap-2 border-t border-[var(--lp-border)] pt-8 text-[0.78rem] leading-[1.8] text-[var(--lp-muted)] md:flex-row md:items-center md:justify-between md:gap-8">
          <p>
            <span className="text-[var(--lp-ink)]">{t("lp.footer.legalName")}</span>
            {" · "}
            {t("lp.footer.incorporation")}
          </p>
          <p>
            © {LANDING_COPYRIGHT_YEAR} {t("lp.footer.legalName")} {t("lp.footer.rights")}
          </p>
        </div>
      </div>
    </footer>
  );
}

/**
 * 版权年份。
 *
 * 原因注释：刻意写成常量而不是 new Date().getFullYear()。
 * 动态取年会让页面在每年 1 月 1 日零点自动变化，看起来贴心，
 * 实则产生了一处无人知晓的时间依赖：快照测试会在跨年当天全部失败，
 * 而且失败信息和年份无关，排查起来会绕很久。
 * 版权年份一年只需要改一次，手动改一行远比调试一次跨年故障便宜。
 */
const LANDING_COPYRIGHT_YEAR = 2026;
