/**
 * 接口注释：
 * 官网首屏。承载产品的一句话定位、主 CTA（跳转产品认证页）和网格聚焦背景。
 *
 * 设计注释：
 * 排版完全沿用参考稿 SYMPHONY 的第一屏结构：
 * 极小的 eyebrow 小标签 → 一个 clamp 到 5rem 的细体大标题 → 一段限宽正文 → 两个 CTA。
 * 标题的 font-weight 是 400 而不是 700，这是这套排版最容易被改坏的一处：
 * 换成粗体后"编辑设计"的气质会立刻退化成普通 SaaS 落地页。
 *
 * 背景是两份参考真正融合的地方，细节见 landing.css 里 .lp-grid-field 的注释。
 */

import { useEffect, useRef } from "react";
import { useTranslation } from "react-i18next";
import { motion } from "framer-motion";
import { ArrowDown } from "lucide-react";

import { easeToward, scrollToSection, toMaskPercent } from "@/lib/landing-nav-sections";

import { LandingLoginLink } from "./LandingLoginLink";
import {
  LP_DURATION_SLOW,
  lpFadeDown,
  lpFadeUp,
  lpFadeUpLarge,
  lpFast,
  lpSlow,
} from "./landing-motion";

export function LandingHero() {
  const { t } = useTranslation();
  const sectionRef = useRef<HTMLElement | null>(null);
  const gridRef = useRef<HTMLDivElement | null>(null);

  /**
   * 网格聚焦光圈跟随鼠标。
   *
   * 教学注释：
   * 和光标环用的是同一套逐帧插值，但这里写入的是 CSS 变量而不是 transform，
   * 因为遮罩位置只能通过 radial-gradient 的坐标表达。
   * 同样刻意不走 React state：遮罩每帧都在变，用 state 会触发每秒 60 次重渲染，
   * 而这一屏底下还挂着大标题和按钮，重渲染的代价不划算。
   */
  useEffect(() => {
    const section = sectionRef.current;
    const grid = gridRef.current;
    if (!section || !grid || typeof window === "undefined") {
      return;
    }

    // 触摸设备和"减少动态效果"下不启动跟随。
    // CSS 侧在 prefers-reduced-motion 时会把遮罩整体关掉、网格以半透明静态呈现，
    // 所以这里直接不注册监听，视觉上仍然有网格肌理，只是不跟手。
    const skipMotion = window.matchMedia(
      "(hover: none), (prefers-reduced-motion: reduce)",
    ).matches;
    if (skipMotion) {
      return;
    }

    // 初始位置放在偏左上，而不是正中：正中会让光圈看起来像个居中的装饰圆，
    // 偏移后更像"光标刚好停在那里"，鼠标一动就自然接上。
    let targetX = 38;
    let targetY = 42;
    let currentX = targetX;
    let currentY = targetY;
    let frameId = 0;

    const handlePointerMove = (event: MouseEvent) => {
      const bounds = section.getBoundingClientRect();
      targetX = toMaskPercent(event.clientX - bounds.left, bounds.width);
      targetY = toMaskPercent(event.clientY - bounds.top, bounds.height);
    };

    const renderFrame = () => {
      currentX = easeToward(currentX, targetX);
      currentY = easeToward(currentY, targetY);
      grid.style.setProperty("--lp-x", `${currentX}%`);
      grid.style.setProperty("--lp-y", `${currentY}%`);
      frameId = window.requestAnimationFrame(renderFrame);
    };

    // 监听挂在 window 而不是 section 上：光标移出首屏后光圈应该继续朝出界方向
    // 缓慢滑走（toMaskPercent 允许到 -20%/120%），而不是在边界上突然定住。
    window.addEventListener("mousemove", handlePointerMove, { passive: true });
    frameId = window.requestAnimationFrame(renderFrame);

    return () => {
      window.cancelAnimationFrame(frameId);
      window.removeEventListener("mousemove", handlePointerMove);
    };
  }, []);

  return (
    <section
      ref={sectionRef}
      id="lp-main"
      /* 设计注释：内容贴底而不是垂直居中（items-end 而不是 items-center）。
         居中时状态行下方会悬着一大块空白，读者的视线在标题和空白之间无处落脚；
         贴底之后"需求锁定后无人值守"那行正好压在首屏下边界上方，
         成为第一屏的收口，同时暗示下面还有内容。

         min-h-[100svh] 保留：内容超过一屏高时容器会被撑开，
         items-end 在被撑开的容器里等同于正常流，不会裁掉顶部。
         用 svh 而不是 vh，是因为移动端 vh 把地址栏算进去了，
         用 vh 会让状态行藏在浏览器工具栏后面。 */
      className="relative flex min-h-[100svh] items-end overflow-hidden border-b border-[var(--lp-border)] bg-[var(--lp-bg)]"
    >
      {/* 网格聚焦层。aria-hidden 因为它纯装饰；
          放在内容之下、不接收指针事件，避免挡住文字选择和按钮点击。 */}
      <div
        ref={gridRef}
        aria-hidden="true"
        className="lp-grid-field pointer-events-none absolute inset-0 z-0"
      />

      {/* 上下留白不对称：顶部留足导航高度（88px）之外的余量，
          底部只留一点点，让状态行贴近下边界。
          pt 不能小于导航高度，否则窗口矮的时候 eyebrow 会被固定导航压住。 */}
      <div className="relative z-10 mx-auto w-full max-w-[1440px] px-6 pb-12 pt-32 md:px-10 md:pb-16 md:pt-36">
        {/* eyebrow：0.75rem 大写 + 0.2em 字距，参考稿的 .sub-header。
            走快轨，先于标题出现，给大标题的慢速浮入让出时间差。 */}
        <motion.p
          variants={lpFadeDown}
          initial="hidden"
          animate="visible"
          transition={lpFast(0.15)}
          className="text-[0.7rem] uppercase tracking-[0.2em] text-[var(--lp-muted)]"
        >
          {t("lp.hero.eyebrow")}
        </motion.p>

        {/* 主标题走慢轨。max-w 900px 是参考稿的原值——
            这个限宽保证标题稳定折成两到三行，一行装完会失掉"编辑排版"的块面感。 */}
        <motion.h1
          variants={lpFadeUpLarge}
          initial="hidden"
          animate="visible"
          transition={lpSlow(0.25)}
          className="lp-display mt-7 max-w-[900px] text-[clamp(2.5rem,6vw,5rem)] font-normal leading-[1.05] tracking-[-0.04em] text-[var(--lp-ink)]"
        >
          {t("lp.hero.title")}
        </motion.h1>

        <motion.p
          variants={lpFadeUp}
          initial="hidden"
          animate="visible"
          transition={lpFast(0.55)}
          className="mt-8 max-w-[560px] text-base leading-[1.75] text-[var(--lp-muted)] md:text-[1.05rem]"
        >
          {t("lp.hero.body")}
        </motion.p>

        <motion.div
          variants={lpFadeUp}
          initial="hidden"
          animate="visible"
          transition={lpFast(0.75)}
          className="mt-12 flex flex-wrap items-center gap-x-8 gap-y-5"
        >
          {/* 主 CTA。设计注释：这里绝对不用参考稿 Sanctuary 那个"长按 1.5 秒进入"的交互——
              冥想类产品的仪式感放到企业站的登录按钮上，客户会以为按钮坏了。
              那段环形填充动效被移植到了五 Agent 流水线的状态指示器上，见 .lp-stage-ring。 */}
          <LandingLoginLink className="rounded-full bg-[var(--lp-accent)] px-8 py-4 text-sm tracking-[0.02em] text-white transition-opacity duration-300 hover:opacity-85">
            {t("lp.hero.primaryCta")}
          </LandingLoginLink>

          {/* 次级 CTA：文字 + 44px 圆形按钮，参考稿的 .circle-btn。
              group-hover 让圆圈和文字一起反馈，而不是各自单独响应。 */}
          <button
            type="button"
            onClick={() => scrollToSection("pipeline")}
            className="group flex items-center gap-4 text-sm text-[var(--lp-ink)]"
          >
            <span className="border-b border-transparent pb-0.5 transition-colors duration-300 group-hover:border-[var(--lp-ink)]">
              {t("lp.hero.secondaryCta")}
            </span>
            <span className="flex h-11 w-11 items-center justify-center rounded-full border border-[var(--lp-border)] transition-colors duration-300 group-hover:border-[var(--lp-ink)]">
              <ArrowDown className="h-4 w-4" strokeWidth={1.25} />
            </span>
          </button>
        </motion.div>

        {/* 运行状态行。
            教学注释：脉冲点在参考稿里是纯装饰（"System Status: Harmonized"）。
            官网只把它用在真实语义上——这里陈述的是产品的实际行为：
            需求锁定后剩下四个阶段无人值守地跑完。不用它来装点气氛。 */}
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ duration: LP_DURATION_SLOW, delay: 1.1 }}
          className="mt-16 flex items-center gap-3 border-t border-[var(--lp-border)] pt-6"
        >
          <span
            aria-hidden="true"
            className="lp-pulse relative h-2 w-2 rounded-full bg-[var(--lp-live)] text-[var(--lp-live)]"
          />
          <span className="text-[0.7rem] uppercase tracking-[0.16em] text-[var(--lp-muted)]">
            {t("lp.hero.statusLabel")}
          </span>
        </motion.div>
      </div>
    </section>
  );
}
