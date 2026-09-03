/**
 * 接口注释：
 * 四个固定视图区块（锚点 #views）。PRD / UI / Architecture / API。
 *
 * 设计注释：
 * 这块讲的是"几十个文件之上只有四个入口"，所以版式本身就该是四等分的规整网格——
 * 版式在读者读完文字之前就已经把"四"这个数说清楚了。
 * 分隔用 1px 竖线（.lp-divide-x）而不是卡片边框：卡片会让四项读成四个独立物件，
 * 竖线让它们读成同一张表的四栏，那才是实际关系。
 */

import { useTranslation } from "react-i18next";
import { motion } from "framer-motion";

import { LP_VIEWPORT, lpFadeUp, lpFast } from "./landing-motion";
import { LandingSectionHeader } from "./LandingSectionHeader";

const VIEW_KEYS = ["prd", "ui", "architecture", "api"] as const;

export function LandingViews() {
  const { t } = useTranslation();

  return (
    <section id="views" className="border-b border-[var(--lp-border)] bg-[var(--lp-bg)]">
      <div className="mx-auto max-w-[1440px] px-6 py-24 md:px-10 md:py-32">
        <LandingSectionHeader
          eyebrow={t("lp.views.eyebrow")}
          title={t("lp.views.title")}
          body={t("lp.views.body")}
        />

        {/* 教学注释：这里没有用 .lp-divide-x，改成在每个格子上直接写 md:border-l。
            原因是 .lp-divide-x 是一条普通 CSS 类，Tailwind 的 md: 前缀只能修饰
            Tailwind 自己生成的工具类，写成 md:lp-divide-x 不会报错、也不会生成任何规则，
            只会安静地什么都不做。窄屏是单列，竖线会全部叠到左侧变成一条长线，
            所以竖线必须能按断点开关——那就用能被断点修饰的写法。 */}
        <div className="mt-16 grid grid-cols-1 border-t border-[var(--lp-border)] md:grid-cols-4">
          {VIEW_KEYS.map((key, index) => (
            <motion.div
              key={key}
              variants={lpFadeUp}
              initial="hidden"
              whileInView="visible"
              viewport={LP_VIEWPORT}
              transition={lpFast(index * 0.08)}
              className="border-b border-[var(--lp-border)] px-0 py-8 md:border-b-0 md:border-l md:px-8 md:py-10 md:first:border-l-0 md:first:pl-0 md:last:pr-0"
            >
              <span className="lp-mono text-[0.68rem] tracking-[0.12em] text-[var(--lp-muted)]">
                {String(index + 1).padStart(2, "0")}
              </span>
              <h3 className="lp-display mt-5 text-lg font-normal tracking-[-0.02em] text-[var(--lp-ink)]">
                {t(`lp.views.${key}.name`)}
              </h3>
              <p className="mt-3 text-[0.9rem] leading-[1.8] text-[var(--lp-muted)]">
                {t(`lp.views.${key}.body`)}
              </p>
            </motion.div>
          ))}
        </div>
      </div>
    </section>
  );
}
