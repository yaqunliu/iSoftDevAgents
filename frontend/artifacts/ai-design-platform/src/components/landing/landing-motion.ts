/**
 * 接口注释：
 * 官网所有入场动效的共享参数。组件只引用这里的变体和过渡，不自己写时长和曲线。
 *
 * 原因注释：
 * 参考稿把延迟硬编码在每个元素上（0.3s / 0.5s / 0.8s / 1.1s / 1.3s 逐个手写）。
 * 那在单文件 demo 里没问题，但铺到十几个组件上会出现两个必然的故障：
 * 一是节奏对不齐（有人写 0.8 有人写 0.85，肉眼看得出来），
 * 二是想整体调快调慢就得翻遍所有文件。所以这里集中成常量。
 */

import type { Transition, Variants } from "framer-motion";

/**
 * 设计注释：
 * 这条曲线等价于 landing.css 里的 --lp-ease，即参考稿 Sanctuary 的 --ease-fluid。
 * 它是"起步快、尾段长时间缓慢收住"的形状，也是那份参考手感的真正来源——
 * 比任何单个动效都重要。framer-motion 需要数组形式，所以在这里再声明一次；
 * 两处数值必须保持一致，改一个就要改另一个。
 */
export const LP_EASE: [number, number, number, number] = [0.25, 1, 0.5, 1];

/**
 * 双轨入场节奏。
 *
 * 设计注释：
 * 这是两份参考结合时必须做的取舍。SYMPHONY 的入场是 0.8s 左右，干脆利落，
 * 适合信息密度高的编辑排版；Sanctuary 的 fadeInSlow 是 3s，缓慢渗出，
 * 适合只有一句话的冥想页。全站统一用哪一个都会坏事：
 * 全用 3s，读者滚到第五屏还在等文字浮现，企业站会显得卡；
 * 全用 0.8s，Hero 大标题会"弹"出来，失掉参考稿最打动人的那份从容。
 *
 * 所以分两轨：标题和大块视觉走慢轨，正文、按钮、列表、数据位走快轨。
 * 慢轨压到 1.6s（不是原稿的 3s）——3s 只有在单屏不滚动时才成立。
 */
export const LP_DURATION_FAST = 0.7;
export const LP_DURATION_SLOW = 1.6;

export function lpFast(delay = 0): Transition {
  return { duration: LP_DURATION_FAST, delay, ease: LP_EASE };
}

export function lpSlow(delay = 0): Transition {
  return { duration: LP_DURATION_SLOW, delay, ease: LP_EASE };
}

/** 从下方浮入，用于正文、按钮、列表项 */
export const lpFadeUp: Variants = {
  hidden: { opacity: 0, y: 24 },
  visible: { opacity: 1, y: 0 },
};

/** 从上方落下，用于导航栏和 eyebrow 小标签 */
export const lpFadeDown: Variants = {
  hidden: { opacity: 0, y: -16 },
  visible: { opacity: 1, y: 0 },
};

/** 位移更大的浮入，专用于 Hero 大标题（配慢轨时长） */
export const lpFadeUpLarge: Variants = {
  hidden: { opacity: 0, y: 56 },
  visible: { opacity: 1, y: 0 },
};

/** 纯淡入，用于图片和深色面板这类不适合位移的大块 */
export const lpFadeIn: Variants = {
  hidden: { opacity: 0 },
  visible: { opacity: 1 },
};

/**
 * 滚动触发的统一阈值。
 *
 * 原因注释：
 * once: true 是必须的——企业站访客会反复上下滚动比对信息，
 * 如果每次滚过都重播一遍入场动画，页面会变成走马灯，读起来非常累。
 * amount: 0.2 表示区块露出两成就开始播，等到一半才播会让人觉得"内容加载慢"。
 */
export const LP_VIEWPORT = { once: true, amount: 0.2 } as const;
