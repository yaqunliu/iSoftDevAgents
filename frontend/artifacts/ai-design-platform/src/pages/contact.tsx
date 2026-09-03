/**
 * 接口注释：
 * 联系页，公开路由 /contact。顶部导航的 Contact 和首页底部 CTA 的次级按钮都指向这里。
 *
 * ⚠️ 页内表单目前不真正发送。接后端的入口在
 * lib/landing-contact-form.ts 的 submitContactEnquiry，详见该函数注释。
 */

import { LandingContactPage } from "@/components/landing/LandingContactPage";
import { useLandingChrome } from "@/components/landing/use-landing-chrome";

import "@/components/landing/landing.css";

export default function ContactPage() {
  useLandingChrome("Contact — gmonkey.ai");

  return <LandingContactPage />;
}
