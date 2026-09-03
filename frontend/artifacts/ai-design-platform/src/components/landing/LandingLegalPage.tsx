/**
 * 接口注释：
 * Terms 与 Privacy 两页共用的排版外壳。传入标题、引言、以及若干 sN 小节的 key 前缀。
 *
 * 原因注释：
 * 两页的结构完全一致（标题 → 更新日期 → 引言 → 编号小节 → 联系方式 → 返回）。
 * 各写一遍的话，将来要改版式（比如加一列小节目录），就得记得两个文件都改；
 * 漏改一个不会报错，只会有一页悄悄和另一页长得不一样。
 *
 * ⚠️ 法务提示（2026-09-03，用户确认后移除了页头的 DRAFT 横幅）：
 * 这两份文本是通用商业条款，现在以正式文档的面貌呈现，但仍未经执业律师复核。
 * 其中 Privacy 第 3 节（完整保留 LLM 输入输出）和第 6 节（跨境传输）
 * 描述的是产品的真实行为，措辞需要工程逐字核对。
 * lp.legal.lastUpdatedValue 是文档的生效日期标记，改动条款内容时必须同步更新它，
 * 否则页面会声称一份已经变过的文本"最后更新于"某个更早的日期。
 */

import { useTranslation } from "react-i18next";
import { Link } from "wouter";
import { motion } from "framer-motion";

import { ctaEmailHref, LANDING_ROUTES, SUPPORT_EMAIL } from "@/lib/landing-cta";

import { LandingFooter } from "./LandingFooter";
import { LP_VIEWPORT, lpFadeUp, lpFast } from "./landing-motion";

type LandingLegalPageProps = {
  /** i18n key 前缀，"lp.terms" 或 "lp.privacy" */
  namespace: string;
  /** 小节数量。组件按 s1..sN 依次渲染。 */
  sectionCount: number;
};

export function LandingLegalPage({ namespace, sectionCount }: LandingLegalPageProps) {
  const { t } = useTranslation();

  // 教学注释：从数量生成 key 而不是让调用方传一个 key 数组。
  // 小节编号本来就必须连续，让调用方手写数组等于把"别漏掉 s7"这件事
  // 交给人来保证，而漏掉的那一节不会报错、只会静静地不出现在页面上。
  const sections = Array.from({ length: sectionCount }, (_, index) => `s${index + 1}`);

  return (
    <div className="min-h-screen bg-[var(--lp-bg)] text-[var(--lp-ink)]">
      <main className="mx-auto max-w-[760px] px-6 pb-24 pt-16 md:px-10 md:pb-32 md:pt-24">
        <Link
          href={LANDING_ROUTES.home}
          className="lp-mono text-[0.72rem] tracking-[0.1em] text-[var(--lp-muted)] transition-colors duration-300 hover:text-[var(--lp-ink)]"
        >
          ← {t("lp.legal.backToHome")}
        </Link>

        <motion.h1
          variants={lpFadeUp}
          initial="hidden"
          animate="visible"
          transition={lpFast(0.05)}
          className="lp-display mt-10 text-[clamp(1.9rem,4vw,2.75rem)] font-normal leading-[1.15] tracking-[-0.035em]"
        >
          {t(`${namespace}.title`)}
        </motion.h1>

        <p className="lp-mono mt-5 text-[0.72rem] tracking-[0.08em] text-[var(--lp-muted)]">
          {t("lp.legal.lastUpdated")}: {t("lp.legal.lastUpdatedValue")}
        </p>

        <p className="mt-10 text-[0.95rem] leading-[1.9] text-[var(--lp-muted)]">
          {t(`${namespace}.intro`)}
        </p>

        <div className="mt-4">
          {sections.map((section, index) => (
            <motion.section
              key={section}
              variants={lpFadeUp}
              initial="hidden"
              whileInView="visible"
              viewport={LP_VIEWPORT}
              transition={lpFast(Math.min(index, 4) * 0.04)}
              className="border-t border-[var(--lp-border)] py-9"
            >
              <h2 className="lp-display text-base font-normal tracking-[-0.02em] text-[var(--lp-ink)]">
                {t(`${namespace}.${section}.title`)}
              </h2>
              <p className="mt-4 text-[0.92rem] leading-[1.9] text-[var(--lp-muted)]">
                {t(`${namespace}.${section}.body`)}
              </p>
            </motion.section>
          ))}
        </div>

        <div className="border-t border-[var(--lp-border)] pt-9">
          <p className="text-[0.92rem] leading-[1.9] text-[var(--lp-muted)]">
            {t("lp.legal.contactPrompt")}{" "}
            <a
              href={ctaEmailHref()}
              className="lp-mono text-[var(--lp-ink)] underline underline-offset-4 transition-opacity duration-300 hover:opacity-70"
            >
              {SUPPORT_EMAIL}
            </a>
          </p>
        </div>
      </main>

      <LandingFooter />
    </div>
  );
}
