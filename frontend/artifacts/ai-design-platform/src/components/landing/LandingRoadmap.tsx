/**
 * 接口注释：
 * 路线图区块（锚点 #roadmap）。
 *
 * ⚠️ 这块描述的是尚未发布的能力。
 *
 * 原因注释：
 * 三条内容全部用将来时书写，区块的 eyebrow 是 "Roadmap"。
 * 这不是措辞偏好，是必须保留的约束——把在研能力写成已有能力，
 * 在企业采购里会被当作虚假陈述，而且往往是在合同阶段才被发现。
 * 将来时和 "Roadmap" 这个 eyebrow 不要在功能真正上线前改掉。
 *
 * 变更记录：2026-09-03 按要求去掉了标题旁边那个
 * "In development — not yet available" 徽章。摘掉它是安全的，
 * 因为"这是路线图不是现货"这层意思由 eyebrow 和将来时正文同时承载着，
 * 徽章只是第三重。但如果将来有人把正文改成现在时，
 * 这块就再没有任何免责标记了——那时候必须把徽章加回来。
 */

import { useTranslation } from "react-i18next";
import { motion } from "framer-motion";

import { LP_VIEWPORT, lpFadeUp, lpFast } from "./landing-motion";
import { LandingSectionHeader } from "./LandingSectionHeader";

const ROADMAP_ITEMS = ["item1", "item2", "item3"] as const;

export function LandingRoadmap() {
  const { t } = useTranslation();

  return (
    <section id="roadmap" className="border-b border-[var(--lp-border)] bg-[var(--lp-bg)]">
      <div className="mx-auto max-w-[1440px] px-6 py-24 md:px-10 md:py-32">
        <LandingSectionHeader
          eyebrow={t("lp.roadmap.eyebrow")}
          title={t("lp.roadmap.title")}
          body={t("lp.roadmap.body")}
        />

        {/* 三条路线本身是有先后依赖的（先能编译，才能沙箱跑起来，才谈得上闭环修复），
            所以用带序号的横向三栏，从左到右读就是依赖顺序。 */}
        <ol className="mt-16 grid grid-cols-1 border-t border-[var(--lp-border)] md:grid-cols-3">
          {ROADMAP_ITEMS.map((item, index) => (
            <motion.li
              key={item}
              variants={lpFadeUp}
              initial="hidden"
              whileInView="visible"
              viewport={LP_VIEWPORT}
              transition={lpFast(index * 0.1)}
              className="border-b border-[var(--lp-border)] py-8 md:border-b-0 md:border-l md:px-10 md:py-10 md:first:border-l-0 md:first:pl-0 md:last:pr-0"
            >
              <span className="lp-mono text-[0.68rem] tracking-[0.12em] text-[var(--lp-muted)]">
                {String(index + 1).padStart(2, "0")}
              </span>
              <h3 className="lp-display mt-5 text-lg font-normal tracking-[-0.02em] text-[var(--lp-ink)]">
                {t(`lp.roadmap.${item}.title`)}
              </h3>
              <p className="mt-3 text-[0.9rem] leading-[1.8] text-[var(--lp-muted)]">
                {t(`lp.roadmap.${item}.body`)}
              </p>
            </motion.li>
          ))}
        </ol>
      </div>
    </section>
  );
}
