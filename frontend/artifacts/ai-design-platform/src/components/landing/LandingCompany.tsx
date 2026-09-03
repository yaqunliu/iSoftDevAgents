/**
 * 接口注释：
 * 公司介绍区块（锚点 #company）。
 *
 * 设计注释：
 * 公司段落和事实清单分成左右两栏。左边是叙述（我们是谁、怎么想的），
 * 右边是可核实的事实（注册地、市场、方向）。
 * 分开的理由是这两类信息的读法不同——叙述是顺着读的，事实是跳着查的，
 * 混在一段里两种读法互相干扰。
 */

import { useTranslation } from "react-i18next";
import { motion } from "framer-motion";

import { LP_VIEWPORT, lpFadeUp, lpFast } from "./landing-motion";
import { LandingSectionHeader } from "./LandingSectionHeader";

const COMPANY_PARAGRAPHS = ["lp.company.body1", "lp.company.body2", "lp.company.body3"] as const;
const COMPANY_FACTS = ["hq", "markets", "focus"] as const;

export function LandingCompany() {
  const { t } = useTranslation();

  return (
    <section id="company" className="border-b border-[var(--lp-border)] bg-[var(--lp-bg)]">
      <div className="mx-auto max-w-[1440px] px-6 py-24 md:px-10 md:py-32">
        <LandingSectionHeader
          eyebrow={t("lp.company.eyebrow")}
          title={t("lp.company.title")}
          badge={
            <span className="lp-mono text-[0.68rem] tracking-[0.08em] text-[var(--lp-muted)]">
              {t("lp.company.incorporation")}
            </span>
          }
        />

        <div className="mt-16 grid grid-cols-1 gap-16 lg:grid-cols-[minmax(0,1.35fr)_minmax(0,1fr)] lg:gap-24">
          <div>
            {COMPANY_PARAGRAPHS.map((key, index) => (
              <motion.p
                key={key}
                variants={lpFadeUp}
                initial="hidden"
                whileInView="visible"
                viewport={LP_VIEWPORT}
                transition={lpFast(index * 0.08)}
                className="mt-6 max-w-[640px] text-[0.95rem] leading-[1.9] text-[var(--lp-muted)] first:mt-0 md:text-base"
              >
                {t(key)}
              </motion.p>
            ))}

            {/* 公司主张单独成块。它是整段里唯一一句带立场的话——
                "把工程可靠性和交付确定性当作核心竞争力，而不是追逐模型层概念"——
                混在三段叙述里会被读过去，抽出来加一道左边线才立得住。 */}
            <motion.div
              variants={lpFadeUp}
              initial="hidden"
              whileInView="visible"
              viewport={LP_VIEWPORT}
              transition={lpFast(0.3)}
              className="mt-12 border-l-2 border-[var(--lp-accent)] pl-6"
            >
              <h3 className="lp-display text-base font-normal tracking-[-0.02em] text-[var(--lp-ink)]">
                {t("lp.company.thesis.title")}
              </h3>
              <p className="mt-3 max-w-[560px] text-[0.95rem] leading-[1.9] text-[var(--lp-ink)]">
                {t("lp.company.thesis.body")}
              </p>
            </motion.div>
          </div>

          <dl>
            {COMPANY_FACTS.map((fact, index) => (
              <motion.div
                key={fact}
                variants={lpFadeUp}
                initial="hidden"
                whileInView="visible"
                viewport={LP_VIEWPORT}
                transition={lpFast(index * 0.08)}
                className="border-t border-[var(--lp-border)] py-6"
              >
                <dt className="text-[0.68rem] uppercase tracking-[0.18em] text-[var(--lp-muted)]">
                  {t(`lp.company.fact.${fact}.label`)}
                </dt>
                <dd className="lp-display mt-2 text-base font-normal tracking-[-0.015em] text-[var(--lp-ink)]">
                  {t(`lp.company.fact.${fact}.value`)}
                </dd>
              </motion.div>
            ))}
          </dl>
        </div>
      </div>
    </section>
  );
}
