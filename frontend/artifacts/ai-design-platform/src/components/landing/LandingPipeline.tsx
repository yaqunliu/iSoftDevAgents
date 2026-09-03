/**
 * 接口注释：
 * 五 Agent 接力区块（锚点 #pipeline）。官网信息量最大的一块。
 *
 * 设计注释：
 * 这里是两份参考结合得最划算的地方。参考稿 Sanctuary 有个"长按 1.5 秒进入"的交互，
 * 用一个 scale(0) → scale(1) 的圆形填充表现进度，仪式感很强。
 * 但那套交互放到企业站的按钮上会坏事：客户点了 Log in 没有立刻进去会以为按钮坏了。
 *
 * 所以那段动效被整个搬到了这里的阶段状态指示器上（.lp-stage-ring）：
 * 已完成的阶段实心填满，运行中的阶段填到一半并持续呼吸，未开始的是空环。
 * 动效从装饰变成了功能性的进度可视化，而且正好呼应产品卖点——可观测性。
 */

import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { motion } from "framer-motion";

import {
  nextActiveIndex,
  PIPELINE_STAGES,
  pipelineProgressPercent,
  resolveStageState,
  type StageState,
} from "@/lib/landing-agent-pipeline";

import { LP_VIEWPORT, lpFadeUp, lpFast } from "./landing-motion";
import { LandingSectionHeader } from "./LandingSectionHeader";

/**
 * 演示循环的步进间隔。
 *
 * 原因注释：2.4 秒是配合 .lp-stage-ring 那条 1.4s 填充过渡定的——
 * 间隔必须明显长于过渡时长，否则上一格还没填满就被推到下一格，
 * 看起来会像卡顿而不是流动。留出 1 秒的静置时间让读者看清当前状态。
 */
const STAGE_INTERVAL_MS = 2400;

export function LandingPipeline() {
  const { t } = useTranslation();
  const [activeIndex, setActiveIndex] = useState(1);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    // 用户开了"减少动态效果"时停在第三阶段：这样三种状态（已完成 / 运行中 / 排队中）
    // 依然同时可见，信息一点没少，只是不再自己走动。
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      setActiveIndex(3);
      return;
    }
    const timer = window.setInterval(() => {
      setActiveIndex((current) => nextActiveIndex(current));
    }, STAGE_INTERVAL_MS);
    return () => {
      window.clearInterval(timer);
    };
  }, []);

  return (
    <section id="pipeline" className="border-b border-[var(--lp-border)] bg-[var(--lp-bg)]">
      <div className="mx-auto max-w-[1440px] px-6 py-24 md:px-10 md:py-32">
        <LandingSectionHeader
          eyebrow={t("lp.pipeline.eyebrow")}
          title={t("lp.pipeline.title")}
          body={t("lp.pipeline.body")}
        />

        {/* 进度条。宽度由 pipelineProgressPercent 算出，那个函数做了越界钳制，
            所以这里不需要再防御一次。 */}
        <div className="mt-16 flex items-center gap-5">
          <div className="h-px flex-1 bg-[var(--lp-border)]">
            <motion.div
              className="h-px bg-[var(--lp-accent)]"
              animate={{ width: `${pipelineProgressPercent(activeIndex)}%` }}
              transition={{ duration: 1.2, ease: [0.25, 1, 0.5, 1] }}
            />
          </div>
          <span className="lp-mono text-[0.7rem] tracking-[0.12em] text-[var(--lp-muted)]">
            {activeIndex} / {PIPELINE_STAGES.length}
          </span>
        </div>

        <ol className="mt-4">
          {PIPELINE_STAGES.map((stage, position) => {
            const state: StageState = resolveStageState(stage.index, activeIndex);
            const isActive = state === "running";

            return (
              <motion.li
                key={stage.id}
                variants={lpFadeUp}
                initial="hidden"
                whileInView="visible"
                viewport={LP_VIEWPORT}
                transition={lpFast(position * 0.08)}
                className="grid grid-cols-1 gap-x-10 gap-y-4 border-t border-[var(--lp-border)] py-9 md:grid-cols-[auto_minmax(0,18rem)_minmax(0,1fr)] md:items-start"
              >
                {/* 状态环 + 序号。currentColor 决定环的颜色，所以颜色只在这一层设一次。 */}
                <div
                  className={`flex items-center gap-4 transition-colors duration-700 ${
                    state === "pending" ? "text-[var(--lp-border)]" : "text-[var(--lp-accent)]"
                  }`}
                >
                  <span className="lp-stage-ring" data-state={state} />
                  <span className="lp-mono text-[0.7rem] tracking-[0.12em] text-[var(--lp-muted)]">
                    {String(stage.index).padStart(2, "0")}
                  </span>
                </div>

                <div>
                  <h3 className="lp-display text-lg font-normal tracking-[-0.02em] text-[var(--lp-ink)]">
                    {t(`lp.pipeline.${stage.id}.name`)}
                  </h3>
                  {/* 阶段产物。设计注释：用等宽字体列出来，是为了强调它们是文件名而不是营销词——
                      读者应当理解成"这个阶段真的会在磁盘上写出这些东西"。 */}
                  <div className="mt-4 flex flex-wrap gap-2">
                    {stage.artifactKeys.map((artifactKey) => (
                      <span
                        key={artifactKey}
                        className="lp-mono rounded-full border border-[var(--lp-border)] px-3 py-1 text-[0.68rem] tracking-[0.06em] text-[var(--lp-muted)]"
                      >
                        {t(`lp.pipeline.${stage.id}.artifact.${artifactKey}`)}
                      </span>
                    ))}
                  </div>
                </div>

                <div className="md:pt-1">
                  <p className="max-w-[520px] text-[0.95rem] leading-[1.8] text-[var(--lp-muted)]">
                    {t(`lp.pipeline.${stage.id}.summary`)}
                  </p>
                  <p
                    className={`mt-4 text-[0.65rem] uppercase tracking-[0.18em] transition-opacity duration-700 ${
                      isActive
                        ? "text-[var(--lp-live)] opacity-100"
                        : "text-[var(--lp-muted)] opacity-60"
                    }`}
                  >
                    {t(`lp.pipeline.state.${state}`)}
                  </p>
                </div>
              </motion.li>
            );
          })}
        </ol>
      </div>
    </section>
  );
}
