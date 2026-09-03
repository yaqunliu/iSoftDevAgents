/**
 * 接口注释：
 * 可观测性区块（锚点 #observability）。第二块深色区域。
 *
 * 设计注释：
 * 这块是整站唯一一处"给企业客户看的技术保证"，所以版式最重：
 * 深底 + 四条能力 + 一个步骤卡面板示意。
 *
 * 面板里的耗时和 token 数是示例值，不是真实运行数据。面板底部有一行明确声明，
 * 那行字不是免责套话——虚构的性能数字一旦被当成承诺，在采购环节会被要求
 * 提供基准测试报告，拿不出来就连带整页的其他陈述一起失信。
 */

import { useTranslation } from "react-i18next";
import { motion } from "framer-motion";

import { PIPELINE_STAGES, resolveStageState } from "@/lib/landing-agent-pipeline";

import { SignalArtwork } from "./LandingArtwork";
import { LP_VIEWPORT, lpFadeIn, lpFadeUp, lpFast, lpSlow } from "./landing-motion";
import { LandingSectionHeader } from "./LandingSectionHeader";

const OBSERVABILITY_FEATURES = ["steps", "tokens", "trace", "debug"] as const;

/**
 * 面板里展示的示例步骤卡。
 *
 * 教学注释：
 * 数值写死成常量而不是随机生成，有两个原因。
 * 一是可复现——随机数会让每次刷新的页面都不一样，截图和视觉回归测试全都失效。
 * 二是可控——手写的数值可以刻意做得"不圆整"（4m 12s 而不是 4m 00s），
 * 因为真实的运行耗时本来就不圆整，圆整的数字反而一眼看出是假的。
 * 这些值只用于说明步骤卡的形态，配合面板底部的示例声明一起出现。
 */
const SAMPLE_STEPS = [
  { stageIndex: 1, elapsed: "1m 48s", tokens: "18,240", files: "2" },
  { stageIndex: 2, elapsed: "4m 12s", tokens: "41,905", files: "2" },
  { stageIndex: 3, elapsed: "6m 03s", tokens: "57,116", files: "1" },
] as const;

/** 面板演示停在第三阶段：三种状态刚好同时可见。 */
const SAMPLE_ACTIVE_INDEX = 3;

export function LandingObservability() {
  const { t } = useTranslation();

  return (
    <section id="observability" className="lp-noise relative overflow-hidden bg-[var(--lp-dark-bg)]">
      <div
        aria-hidden="true"
        className="lp-grid-static-dark pointer-events-none absolute inset-0 opacity-30"
      />

      <div className="relative z-10 mx-auto max-w-[1440px] px-6 py-24 md:px-10 md:py-32">
        <LandingSectionHeader
          dark
          eyebrow={t("lp.observability.eyebrow")}
          title={t("lp.observability.title")}
          body={t("lp.observability.body")}
        />

        <div className="mt-20 grid grid-cols-1 gap-16 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.15fr)] lg:gap-24">
          {/* 左栏：四条能力，1px 细线分隔，与全站的分隔语言一致 */}
          <div>
            {OBSERVABILITY_FEATURES.map((feature, index) => (
              <motion.div
                key={feature}
                variants={lpFadeUp}
                initial="hidden"
                whileInView="visible"
                viewport={LP_VIEWPORT}
                transition={lpFast(index * 0.09)}
                className="border-t border-[var(--lp-dark-border)] py-7"
              >
                <h3 className="lp-display text-base font-normal tracking-[-0.015em] text-[var(--lp-dark-ink)]">
                  {t(`lp.observability.feature.${feature}.title`)}
                </h3>
                <p className="mt-3 max-w-[440px] text-[0.9rem] leading-[1.8] text-[var(--lp-dark-muted)]">
                  {t(`lp.observability.feature.${feature}.body`)}
                </p>
              </motion.div>
            ))}
          </div>

          {/* 右栏：步骤卡面板示意 */}
          <motion.div
            variants={lpFadeIn}
            initial="hidden"
            whileInView="visible"
            viewport={LP_VIEWPORT}
            transition={lpSlow(0.15)}
            className="border border-[var(--lp-dark-border)] bg-[var(--lp-dark-surface)]"
          >
            <div className="flex items-center justify-between border-b border-[var(--lp-dark-border)] px-6 py-5">
              <div>
                <p className="text-[0.7rem] uppercase tracking-[0.18em] text-[var(--lp-dark-ink)]">
                  {t("lp.observability.panelTitle")}
                </p>
                <p className="mt-1.5 text-[0.72rem] text-[var(--lp-dark-muted)]">
                  {t("lp.observability.panelSubtitle")}
                </p>
              </div>
              <span
                aria-hidden="true"
                className="lp-pulse relative h-2 w-2 rounded-full bg-[var(--lp-live)] text-[var(--lp-live)]"
              />
            </div>

            <div>
              {SAMPLE_STEPS.map((step) => {
                const stage = PIPELINE_STAGES[step.stageIndex - 1];
                const state = resolveStageState(step.stageIndex, SAMPLE_ACTIVE_INDEX);

                return (
                  <div
                    key={step.stageIndex}
                    className="border-b border-[var(--lp-dark-border)] px-6 py-5 last:border-b-0"
                  >
                    <div
                      className={`flex items-center gap-3 ${
                        state === "running"
                          ? "text-[var(--lp-live)]"
                          : "text-[var(--lp-dark-muted)]"
                      }`}
                    >
                      <span className="lp-stage-ring" data-state={state} />
                      <span className="lp-display text-[0.92rem] text-[var(--lp-dark-ink)]">
                        {stage ? t(`lp.pipeline.${stage.id}.name`) : ""}
                      </span>
                      <span className="ml-auto text-[0.62rem] uppercase tracking-[0.16em]">
                        {t(`lp.pipeline.state.${state}`)}
                      </span>
                    </div>

                    {/* 三个指标用等宽 + tabular-nums：数字等宽后，
                        三张卡片的数值会在纵向自动对齐成一列，读起来像一张表。 */}
                    <dl className="lp-mono mt-4 grid grid-cols-3 gap-4 text-[0.72rem]">
                      {[
                        { label: t("lp.observability.metric.elapsed"), value: step.elapsed },
                        { label: t("lp.observability.metric.tokens"), value: step.tokens },
                        { label: t("lp.observability.metric.files"), value: step.files },
                      ].map((metric) => (
                        <div key={metric.label}>
                          <dt className="text-[0.6rem] uppercase tracking-[0.14em] text-[var(--lp-dark-muted)]">
                            {metric.label}
                          </dt>
                          <dd className="mt-1.5 text-[var(--lp-dark-ink)]">{metric.value}</dd>
                        </div>
                      ))}
                    </dl>
                  </div>
                );
              })}
            </div>

            {/* 信号图收尾，兼作面板底部的视觉重量 */}
            <div aria-hidden="true" className="h-20 overflow-hidden text-[var(--lp-dark-ink)]">
              <SignalArtwork className="h-full w-full" />
            </div>

            {/* 示例数据声明。不要删。 */}
            <p className="border-t border-[var(--lp-dark-border)] px-6 py-4 text-[0.66rem] leading-[1.6] text-[var(--lp-dark-muted)]">
              {t("lp.observability.panelNote")}
            </p>
          </motion.div>
        </div>
      </div>
    </section>
  );
}
