/**
 * 接口注释：
 * gmonkey.ai 官网首页，挂在公开路由 "/" 上（不经过 ProtectedRoute）。
 * 访客直接输入域名即落在这里，不需要部署层做任何路径映射。
 *
 * 原因注释：
 * 这一段以前写的是"官网挂在 /landing，根域名交给 nginx 映射"。
 * 那个方案已经废弃：官网现在直接占用 "/"，产品首页搬到了 lib/app-routes.ts
 * 的 APP_HOME_PATH（/app），/landing 只留了一个 replace 重定向兜住旧链接。
 * 保留这段修订记录是因为"根路径归谁"决定了五处回跳目标（登录成功、未登录
 * 的 next、项目页返回、404 返回、官网登录按钮），改动时必须连着一起看——
 * 详见 App.tsx 路由表上方的注释。
 *
 * 进入产品的入口有两个，都指向 /auth，都由
 * components/landing/LandingLoginLink.tsx 统一解析地址：
 * 顶部导航的 "Product" 项，以及右侧的 "Log in" 胶囊按钮。
 *
 * 设计注释：
 * 区块顺序就是一条论证链，不是随便排的：
 *   Hero（是什么）→ Ticker（结构事实）→ Pipeline（怎么做的）
 *   → Showcase（深色，换气）→ Control（人在环中，差异点）
 *   → Observability（深色，工程保证）→ Views（产出形态）
 *   → Stack（能不能进我们的机房）→ Roadmap（在研，明确标注）
 *   → Company（谁在做）→ CTA（那就试试）
 * 两块深色分别落在第 4 和第 6 位——正好把长滚动切成三段，
 * 每段不超过三屏密集文字，读者不会在中途疲劳退出。
 */

import { LandingCompany } from "@/components/landing/LandingCompany";
import { LandingControl } from "@/components/landing/LandingControl";
import { LandingCta } from "@/components/landing/LandingCta";
import { LandingCursorRing } from "@/components/landing/LandingCursorRing";
import { LandingFooter } from "@/components/landing/LandingFooter";
import { LandingHero } from "@/components/landing/LandingHero";
import { LandingNav } from "@/components/landing/LandingNav";
import { LandingObservability } from "@/components/landing/LandingObservability";
import { LandingPipeline } from "@/components/landing/LandingPipeline";
import { LandingRoadmap } from "@/components/landing/LandingRoadmap";
import { LandingShowcase } from "@/components/landing/LandingShowcase";
import { LandingStack } from "@/components/landing/LandingStack";
import { LandingTicker } from "@/components/landing/LandingTicker";
import { LandingViews } from "@/components/landing/LandingViews";
import { useLandingChrome } from "@/components/landing/use-landing-chrome";

// 设计注释：样式只在官网页面里 import，产品页面完全不加载这份 CSS。
import "@/components/landing/landing.css";

export default function LandingPage() {
  useLandingChrome("gmonkey.ai — Multi-agent software delivery");

  return (
    <div className="min-h-screen bg-[var(--lp-bg)] text-[var(--lp-ink)]">
      <LandingCursorRing />
      <LandingNav />
      <main>
        <LandingHero />
        <LandingTicker />
        <LandingPipeline />
        <LandingShowcase />
        <LandingControl />
        <LandingObservability />
        <LandingViews />
        <LandingStack />
        <LandingRoadmap />
        <LandingCompany />
        <LandingCta />
      </main>
      <LandingFooter />
    </div>
  );
}
