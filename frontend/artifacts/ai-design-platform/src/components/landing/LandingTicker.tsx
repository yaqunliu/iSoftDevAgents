/**
 * 接口注释：
 * Hero 正下方那排数据位。六格，每格一个数值加一行说明。
 *
 * 教学注释：
 * 参考稿 SYMPHONY 这块原本写的是 "14.2k Hours Reclaimed"、"∞ Human Potential"
 * 这类营销数字。放在企业站上会立刻反噬：采购看到具体数字第一反应是要证明材料，
 * 拿不出来就连带怀疑整页的其他陈述。产品刚起步也确实没有这类运营数据。
 *
 * 所以这六格全部换成产品的结构性事实——几个 Agent、几个固定视图、什么技术栈。
 * 这些不需要任何数据支撑，读者自己在下面的区块里就能一一验证，
 * 而且信息量比虚构的百分比更高：它直接回答了"这东西到底是什么构成的"。
 */

import { useTranslation } from "react-i18next";
import { motion } from "framer-motion";

import { LP_VIEWPORT, lpFadeUp, lpFast } from "./landing-motion";

/**
 * 设计注释：
 * 六项的顺序是有意排的——从产品结构（Agent 数、视图数、产物数）
 * 走到工程属性（可追溯、模型无关、部署成本）。
 * 前三格回答"它产出什么"，后三格回答"它怎么落到你的环境里"，
 * 正好对应企业客户看官网时的两个连续问题。
 */
const TICKER_ITEMS = ["agents", "views", "artifacts", "trace", "models", "deploy"] as const;

export function LandingTicker() {
  const { t } = useTranslation();

  return (
    <section className="border-b border-[var(--lp-border)] bg-[var(--lp-bg)]">
      <div className="mx-auto max-w-[1440px] px-6 md:px-10">
        <div className="lp-ticker">
          {TICKER_ITEMS.map((item, index) => (
            <motion.div
              key={item}
              variants={lpFadeUp}
              initial="hidden"
              whileInView="visible"
              viewport={LP_VIEWPORT}
              // 逐格错开 0.07s 依次浮入，形成从左到右的"扫过"感。
              // 间隔再大就会显得拖沓——六格全部到位不该超过半秒。
              transition={lpFast(index * 0.07)}
            >
              <p className="lp-display text-[1.75rem] font-normal leading-none tracking-[-0.03em] text-[var(--lp-ink)]">
                {t(`lp.ticker.${item}.value`)}
              </p>
              <p className="mt-3 text-[0.65rem] uppercase leading-[1.5] tracking-[0.16em] text-[var(--lp-muted)]">
                {t(`lp.ticker.${item}.label`)}
              </p>
            </motion.div>
          ))}
        </div>
      </div>
    </section>
  );
}
