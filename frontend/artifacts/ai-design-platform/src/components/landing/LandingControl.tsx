/**
 * 接口注释：
 * 人在环中区块（锚点 #control）。讲"一句话修正正在运行的 Agent"这个机制。
 *
 * 设计注释：
 * 版式用了参考稿 SYMPHONY 的错位双栏（.grid-section）：左右两栏等宽，
 * 但右栏整体向下偏移一大截。这个偏移是刻意的——两栏顶部对齐会读成一张表格，
 * 眼睛不知道先看哪边；错开之后阅读顺序变成明确的"先左后右"。
 *
 * 内容上这块是产品差异化最强的一处，所以它拿到了整站唯一的三步编号列表。
 */

import { useTranslation } from "react-i18next";
import { motion } from "framer-motion";

import { LP_VIEWPORT, lpFadeUp, lpFast } from "./landing-motion";
import { LandingSectionHeader } from "./LandingSectionHeader";

const CONTROL_STEPS = ["step1", "step2", "step3"] as const;

export function LandingControl() {
  const { t } = useTranslation();

  return (
    <section id="control" className="border-b border-[var(--lp-border)] bg-[var(--lp-bg)]">
      <div className="mx-auto max-w-[1440px] px-6 py-24 md:px-10 md:py-32">
        <div className="grid grid-cols-1 gap-16 lg:grid-cols-2 lg:gap-32">
          <LandingSectionHeader
            eyebrow={t("lp.control.eyebrow")}
            title={t("lp.control.title")}
            body={t("lp.control.body")}
          />

          {/* 右栏下移。lg 以下不偏移——窄屏是单列纵向流，偏移只会变成一段莫名的空白。 */}
          <div className="lg:pt-40">
            <ol>
              {CONTROL_STEPS.map((step, index) => (
                <motion.li
                  key={step}
                  variants={lpFadeUp}
                  initial="hidden"
                  whileInView="visible"
                  viewport={LP_VIEWPORT}
                  transition={lpFast(index * 0.12)}
                  className="border-t border-[var(--lp-border)] py-8"
                >
                  <div className="flex items-baseline gap-5">
                    <span className="lp-mono text-[0.7rem] tracking-[0.12em] text-[var(--lp-muted)]">
                      {String(index + 1).padStart(2, "0")}
                    </span>
                    <div>
                      <h3 className="lp-display text-lg font-normal tracking-[-0.02em] text-[var(--lp-ink)]">
                        {t(`lp.control.${step}.title`)}
                      </h3>
                      <p className="mt-3 text-[0.95rem] leading-[1.8] text-[var(--lp-muted)]">
                        {t(`lp.control.${step}.body`)}
                      </p>
                    </div>
                  </div>
                </motion.li>
              ))}
            </ol>

            {/* 收尾那句单独拎出来加了脉冲点：它陈述的是"需求锁定后无人值守"，
                是这一整块的结论，不该混在三步列表里被读成第四步。 */}
            <motion.div
              variants={lpFadeUp}
              initial="hidden"
              whileInView="visible"
              viewport={LP_VIEWPORT}
              transition={lpFast(0.4)}
              className="flex items-start gap-3 border-t border-[var(--lp-border)] pt-8"
            >
              <span
                aria-hidden="true"
                className="lp-pulse relative mt-2 h-2 w-2 shrink-0 rounded-full bg-[var(--lp-live)] text-[var(--lp-live)]"
              />
              <p className="text-[0.95rem] leading-[1.8] text-[var(--lp-ink)]">
                {t("lp.control.footnote")}
              </p>
            </motion.div>
          </div>
        </div>
      </div>
    </section>
  );
}
