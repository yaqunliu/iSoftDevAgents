/**
 * 接口注释：
 * 每个区块顶部那组"小标签 + 大标题 + 一段正文"的排版。九个区块共用。
 *
 * 原因注释：
 * 这组排版在参考稿里是靠固定的字号、字距、间距关系立起来的，
 * 九个区块各写一遍必然会漂——某个区块的标题少了 0.5rem 上边距、
 * 某个 eyebrow 的字距写成 0.18em，单看都察觉不出，
 * 但连续滚动时读者会感到"这页有点不整齐"却说不出哪里不对。
 * 抽成组件后，整站的区块节奏由一个文件保证。
 */

import type { ReactNode } from "react";
import { motion } from "framer-motion";

import { LP_VIEWPORT, lpFadeDown, lpFadeUp, lpFadeUpLarge, lpFast, lpSlow } from "./landing-motion";

type LandingSectionHeaderProps = {
  eyebrow: string;
  title: string;
  body?: string;
  /** 深色区块传 true，切换到反相色板 */
  dark?: boolean;
  /** 标题右侧的附加内容，目前只有 Roadmap 的"未发布"徽章用到 */
  badge?: ReactNode;
};

export function LandingSectionHeader({
  eyebrow,
  title,
  body,
  dark = false,
  badge,
}: LandingSectionHeaderProps) {
  const inkClass = dark ? "text-[var(--lp-dark-ink)]" : "text-[var(--lp-ink)]";
  const mutedClass = dark ? "text-[var(--lp-dark-muted)]" : "text-[var(--lp-muted)]";

  return (
    <div className="max-w-[820px]">
      <motion.div
        variants={lpFadeDown}
        initial="hidden"
        whileInView="visible"
        viewport={LP_VIEWPORT}
        transition={lpFast()}
        className="flex flex-wrap items-center gap-4"
      >
        <p className={`text-[0.7rem] uppercase tracking-[0.2em] ${mutedClass}`}>{eyebrow}</p>
        {badge}
      </motion.div>

      {/* 区块标题走慢轨，和 Hero 大标题同一套节奏；
          字号比 Hero 小一档（上限 3.25rem 对 5rem），保证首屏始终是全站最大的那一屏。 */}
      <motion.h2
        variants={lpFadeUpLarge}
        initial="hidden"
        whileInView="visible"
        viewport={LP_VIEWPORT}
        transition={lpSlow(0.1)}
        className={`lp-display mt-6 text-[clamp(1.85rem,3.6vw,3.25rem)] font-normal leading-[1.12] tracking-[-0.035em] ${inkClass}`}
      >
        {title}
      </motion.h2>

      {body ? (
        <motion.p
          variants={lpFadeUp}
          initial="hidden"
          whileInView="visible"
          viewport={LP_VIEWPORT}
          transition={lpFast(0.25)}
          className={`mt-7 max-w-[620px] text-[0.95rem] leading-[1.8] md:text-base ${mutedClass}`}
        >
          {body}
        </motion.p>
      ) : null}
    </div>
  );
}
