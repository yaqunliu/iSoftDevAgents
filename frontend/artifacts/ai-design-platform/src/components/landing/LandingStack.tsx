/**
 * 接口注释：
 * 技术栈与部署区块（锚点 #stack）。
 *
 * 设计注释：
 * 企业客户看官网时，这块往往是技术负责人唯一会认真读的部分——
 * 他要判断的是"这东西能不能进我们现有的机房和流水线"。
 * 所以这里用"标签 / 值"的定义列表而不是散文：读者是在核对清单，不是在读故事。
 * 值一律用等宽字体，强化"这是技术事实，不是形容词"的读感。
 */

import { useTranslation } from "react-i18next";
import { motion } from "framer-motion";

import { LP_VIEWPORT, lpFadeUp, lpFast } from "./landing-motion";
import { LandingSectionHeader } from "./LandingSectionHeader";

const STACK_KEYS = ["backend", "frontend", "models", "deploy"] as const;

export function LandingStack() {
  const { t } = useTranslation();

  return (
    <section id="stack" className="border-b border-[var(--lp-border)] bg-[var(--lp-bg)]">
      <div className="mx-auto max-w-[1440px] px-6 py-24 md:px-10 md:py-32">
        <div className="grid grid-cols-1 gap-16 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)] lg:gap-24">
          <LandingSectionHeader
            eyebrow={t("lp.stack.eyebrow")}
            title={t("lp.stack.title")}
            body={t("lp.stack.body")}
          />

          <dl className="lg:pt-4">
            {STACK_KEYS.map((key, index) => (
              <motion.div
                key={key}
                variants={lpFadeUp}
                initial="hidden"
                whileInView="visible"
                viewport={LP_VIEWPORT}
                transition={lpFast(index * 0.08)}
                className="flex flex-col gap-2 border-t border-[var(--lp-border)] py-6 sm:flex-row sm:items-baseline sm:gap-8"
              >
                <dt className="text-[0.68rem] uppercase tracking-[0.18em] text-[var(--lp-muted)] sm:w-40 sm:shrink-0">
                  {t(`lp.stack.${key}.label`)}
                </dt>
                <dd className="lp-mono text-[0.9rem] leading-[1.7] text-[var(--lp-ink)]">
                  {t(`lp.stack.${key}.value`)}
                </dd>
              </motion.div>
            ))}
          </dl>
        </div>
      </div>
    </section>
  );
}
