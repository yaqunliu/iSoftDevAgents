/**
 * 接口注释：
 * 隐私政策页，公开路由 /privacy。
 *
 * ⚠️ 正文以正式文档面貌呈现，但尚未经执业律师复核。
 * 尤其是第 3 节（保留完整的模型输入输出）和第 6 节（跨境传输）——
 * 这两条描述的是产品的真实行为，措辞需要和实际的数据处理方式逐字核对。
 */

import { LandingLegalPage } from "@/components/landing/LandingLegalPage";
import { useLandingChrome } from "@/components/landing/use-landing-chrome";

import "@/components/landing/landing.css";

/** 小节数量必须与 i18n-landing-locales.ts 里 lp.privacy.s1..s11 的实际条数一致。 */
const PRIVACY_SECTION_COUNT = 11;

export default function PrivacyPage() {
  useLandingChrome("Privacy Policy — gmonkey.ai");

  return <LandingLegalPage namespace="lp.privacy" sectionCount={PRIVACY_SECTION_COUNT} />;
}
