/**
 * 接口注释：
 * 第一块深色区域。全幅深底 + 抽象配图，不带交互。
 *
 * 设计注释：
 * 参考稿 SYMPHONY 里有一块 70vh 的纯黑展示区（.showcase），
 * 作用是在连续的浅色信息块中间强行插入一次呼吸——读者滚了三屏密集文字之后，
 * 一整块深色会重置视觉疲劳，接下来的内容才读得进去。
 * 它承担的是节奏功能，不是信息功能，所以文案刻意只有三行。
 *
 * 原稿在这块上加了 filter: grayscale(20%) contrast(1.1)。
 * 这里不需要——配图本身就是单色矢量，没有需要压下去的色彩。
 */

import { useTranslation } from "react-i18next";
import { motion } from "framer-motion";

import { RelayArtwork } from "./LandingArtwork";
import { LP_VIEWPORT, lpFadeIn, lpFadeUp, lpFadeUpLarge, lpFast, lpSlow } from "./landing-motion";

export function LandingShowcase() {
  const { t } = useTranslation();

  return (
    <section className="lp-noise relative overflow-hidden bg-[var(--lp-dark-bg)]">
      {/* 静态网格肌理。这里不跟随光标——深色块是"停下来看"的地方，
          再加一层跟手动效会把注意力从内容上抢走。 */}
      <div
        aria-hidden="true"
        className="lp-grid-static-dark pointer-events-none absolute inset-0 opacity-40"
      />

      {/* 抽象接力图。放在右侧、部分出血到视口外，
          这种"图没有被完整框住"的处理是编辑排版里制造纵深的常用手法。 */}
      <motion.div
        variants={lpFadeIn}
        initial="hidden"
        whileInView="visible"
        viewport={LP_VIEWPORT}
        transition={lpSlow(0.2)}
        aria-hidden="true"
        className="pointer-events-none absolute -right-16 top-1/2 hidden h-[420px] w-[720px] -translate-y-1/2 text-[var(--lp-dark-ink)] lg:block"
      >
        <RelayArtwork className="h-full w-full" />
      </motion.div>

      <div className="relative z-10 mx-auto max-w-[1440px] px-6 py-28 md:px-10 md:py-36">
        <div className="max-w-[540px]">
          <motion.p
            variants={lpFadeUp}
            initial="hidden"
            whileInView="visible"
            viewport={LP_VIEWPORT}
            transition={lpFast()}
            className="text-[0.7rem] uppercase tracking-[0.2em] text-[var(--lp-dark-muted)]"
          >
            {t("lp.showcase.eyebrow")}
          </motion.p>

          <motion.h2
            variants={lpFadeUpLarge}
            initial="hidden"
            whileInView="visible"
            viewport={LP_VIEWPORT}
            transition={lpSlow(0.1)}
            className="lp-display mt-6 text-[clamp(1.85rem,3.6vw,3.25rem)] font-normal leading-[1.12] tracking-[-0.035em] text-[var(--lp-dark-ink)]"
          >
            {t("lp.showcase.title")}
          </motion.h2>

          <motion.p
            variants={lpFadeUp}
            initial="hidden"
            whileInView="visible"
            viewport={LP_VIEWPORT}
            transition={lpFast(0.25)}
            className="mt-7 text-[0.95rem] leading-[1.8] text-[var(--lp-dark-muted)] md:text-base"
          >
            {t("lp.showcase.body")}
          </motion.p>
        </div>
      </div>
    </section>
  );
}
