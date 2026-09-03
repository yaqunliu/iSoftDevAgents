/**
 * 接口注释：
 * 服务条款页，公开路由 /terms。
 *
 * ⚠️ 正文是通用商业条款，以正式文档面貌呈现，但尚未经执业律师复核。
 * 修改条款内容时必须同步更新 i18n 里的 lp.legal.lastUpdatedValue。
 */

import { LandingLegalPage } from "@/components/landing/LandingLegalPage";
import { useLandingChrome } from "@/components/landing/use-landing-chrome";

import "@/components/landing/landing.css";

/** 小节数量必须与 i18n-landing-locales.ts 里 lp.terms.s1..s13 的实际条数一致。 */
const TERMS_SECTION_COUNT = 13;

export default function TermsPage() {
  useLandingChrome("Terms of Service — gmonkey.ai");

  return <LandingLegalPage namespace="lp.terms" sectionCount={TERMS_SECTION_COUNT} />;
}
