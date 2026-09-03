/**
 * 接口注释：
 * gmonkey.ai 官网首页，挂在公开路由 /landing 上（不经过 ProtectedRoute）。
 *
 * 原因注释：
 * 没有直接占用 "/"。App.tsx 里 "/" 是 ProtectedRoute 包着的产品首页，
 * 没有 token 的访客会被重定向到 /auth——那是产品应用应有的行为，改动它风险太大，
 * 会牵动现有用户的登录回跳。所以官网走独立公开路由，
 * 根域名指向 /landing 交给部署层（nginx）做映射，前端代码零冲突。
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
