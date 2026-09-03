/**
 * 接口注释：
 * 跟随鼠标的缓动描边环。挂在落地页最外层，全站一个实例。
 *
 * 设计注释：
 * 这是参考稿 Sanctuary 里最具辨识度的一处交互。原稿是双层结构：
 * 一个 4px 实心点瞬时跟手，一个 32px 描边环用 lerp 缓动追赶，
 * 同时全局 cursor: none 把系统光标藏掉。
 *
 * 官网只移植了描边环，保留系统光标。原因是原稿是 body overflow:hidden 的单屏体验，
 * 而官网是长滚动、有大量可读文案和链接的页面：隐藏系统光标会让人选不了文字、
 * 看不到链接的手型和输入区的 I-beam，在企业站上是实打实的可用性损失。
 * 而"滑动惯性"这份质感恰好全部来自那个缓动环，跟实心点无关，所以省掉点没有损失。
 */

import { useEffect, useRef } from "react";

import { easeToward } from "@/lib/landing-nav-sections";

/**
 * 教学注释：
 * 环的位置用 requestAnimationFrame + 线性插值逐帧逼近鼠标，而不是直接赋值。
 * 每一帧只走剩余距离的 12%，于是环"追"着鼠标跑——这就是惯性感的来源。
 * 这里刻意不用 React state 存坐标：那会导致每帧一次重渲染（60fps 下每秒 60 次），
 * 直接改 DOM 的 style.transform 才能保证长页面上不掉帧。
 */
export function LandingCursorRing() {
  const ringRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const ring = ringRef.current;
    if (!ring || typeof window === "undefined") {
      return;
    }

    // 原因注释：触摸设备没有 hover 能力，环会变成一个卡在角落不动的圆圈；
    // 用户开了"减少动态效果"时也不该有跟随动画。这两种情况直接不启动动画循环，
    // 连 rAF 都不注册，避免在移动端白烧电量。CSS 侧也有 display:none 兜底。
    const skipMotion = window.matchMedia(
      "(hover: none), (prefers-reduced-motion: reduce)",
    ).matches;
    if (skipMotion) {
      return;
    }

    let pointerX = window.innerWidth / 2;
    let pointerY = window.innerHeight / 2;
    let ringX = pointerX;
    let ringY = pointerY;
    let frameId = 0;
    let hasMoved = false;

    const handlePointerMove = (event: MouseEvent) => {
      pointerX = event.clientX;
      pointerY = event.clientY;

      // 首次移动前环是隐藏的，否则页面一加载就会有个圆圈停在屏幕正中，
      // 看起来像渲染错误而不是光标。
      if (!hasMoved) {
        hasMoved = true;
        ringX = pointerX;
        ringY = pointerY;
        ring.style.opacity = "1";
      }

      // 悬停在可交互元素上时环收紧（尺寸变化由 CSS 过渡负责）。
      // 用 closest 而不是判断 event.target 本身，是因为按钮里通常还套着
      // 文字节点或图标，直接判断会在图标上失效。
      const target = event.target as Element | null;
      const isInteractive = Boolean(
        target?.closest?.('a, button, [role="button"], input, textarea, select'),
      );
      ring.dataset.active = isInteractive ? "true" : "false";
    };

    const handlePointerLeave = () => {
      ring.style.opacity = "0";
      hasMoved = false;
    };

    const renderFrame = () => {
      ringX = easeToward(ringX, pointerX);
      ringY = easeToward(ringY, pointerY);
      // translate(-50%, -50%) 必须留着：CSS 里的居中位移会被这次赋值整体覆盖。
      ring.style.transform = `translate3d(${ringX}px, ${ringY}px, 0) translate(-50%, -50%)`;
      frameId = window.requestAnimationFrame(renderFrame);
    };

    window.addEventListener("mousemove", handlePointerMove, { passive: true });
    document.addEventListener("mouseleave", handlePointerLeave);
    frameId = window.requestAnimationFrame(renderFrame);

    return () => {
      window.cancelAnimationFrame(frameId);
      window.removeEventListener("mousemove", handlePointerMove);
      document.removeEventListener("mouseleave", handlePointerLeave);
    };
  }, []);

  return (
    <div
      ref={ringRef}
      // aria-hidden：这是纯装饰层，读屏软件不该念它。
      aria-hidden="true"
      className="lp-cursor-ring hidden opacity-0 lg:block"
    />
  );
}
