/**
 * 接口注释：
 * 结尾行动召唤区块（锚点 #cta）。
 *
 * 设计注释：
 * 全站唯一一处居中排版。前面九个区块全部左对齐，到这里突然居中，
 * 是在告诉读者"内容结束了"——版式的变化本身就是一个句号。
 *
 * 原因注释：这个区块的 id 以前叫 "contact"。Contact 独立成页面（/contact）之后
 * 改成了 "cta"，避免"导航的 Contact 跳页面、锚点的 contact 指这里"这种同名不同义。
 */

import { useTranslation } from "react-i18next";
import { Link } from "wouter";
import { motion } from "framer-motion";

import { LANDING_ROUTES } from "@/lib/landing-cta";

import { LandingLoginLink } from "./LandingLoginLink";
import { LP_VIEWPORT, lpFadeUp, lpFadeUpLarge, lpFast, lpSlow } from "./landing-motion";

export function LandingCta() {
  const { t } = useTranslation();

  return (
    <section id="cta" className="border-b border-[var(--lp-border)] bg-[var(--lp-bg)]">
      <div className="mx-auto max-w-[1440px] px-6 py-28 text-center md:px-10 md:py-40">
        <motion.h2
          variants={lpFadeUpLarge}
          initial="hidden"
          whileInView="visible"
          viewport={LP_VIEWPORT}
          transition={lpSlow()}
          className="lp-display mx-auto max-w-[760px] text-[clamp(1.85rem,3.6vw,3.25rem)] font-normal leading-[1.12] tracking-[-0.035em] text-[var(--lp-ink)]"
        >
          {t("lp.cta.title")}
        </motion.h2>

        <motion.p
          variants={lpFadeUp}
          initial="hidden"
          whileInView="visible"
          viewport={LP_VIEWPORT}
          transition={lpFast(0.2)}
          className="mx-auto mt-7 max-w-[520px] text-[0.95rem] leading-[1.8] text-[var(--lp-muted)] md:text-base"
        >
          {t("lp.cta.body")}
        </motion.p>

        <motion.div
          variants={lpFadeUp}
          initial="hidden"
          whileInView="visible"
          viewport={LP_VIEWPORT}
          transition={lpFast(0.32)}
          className="mt-12 flex flex-col items-center justify-center gap-4 sm:flex-row"
        >
          {/* Open the platform → 站内 /auth。元素类型（Link 还是 <a>）
              由 LandingLoginLink 按地址形态决定，这里不用关心。 */}
          <LandingLoginLink className="rounded-full bg-[var(--lp-accent)] px-8 py-3.5 text-[0.85rem] tracking-[0.02em] text-white transition-opacity duration-300 hover:opacity-85">
            {t("lp.cta.primary")}
          </LandingLoginLink>
          {/* 次级落点从 mailto 改成了 /contact。
              原因注释：mailto 会直接唤起访客的邮件客户端，而在没配默认客户端的机器上
              （企业里用网页版邮箱的人不少）点了完全没反应——是个静默失败。
              联系页里仍然把邮箱明文列了出来，想直接发信的人一样拿得到。 */}
          <Link
            href={LANDING_ROUTES.contact}
            className="rounded-full border border-[var(--lp-border)] px-8 py-3.5 text-[0.85rem] tracking-[0.02em] text-[var(--lp-ink)] transition-colors duration-300 hover:border-[var(--lp-accent)]"
          >
            {t("lp.cta.secondary")}
          </Link>
        </motion.div>
      </div>
    </section>
  );
}
