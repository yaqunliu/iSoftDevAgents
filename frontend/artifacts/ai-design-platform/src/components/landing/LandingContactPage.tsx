/**
 * 接口注释：
 * Contact 页（/contact）。左栏是真实联系方式与公司信息，右栏是咨询表单。
 *
 * ⚠️⚠️ 这个表单目前不发送任何东西。⚠️⚠️
 * 提交只是走一遍 "提交中 → 成功" 的界面状态，填写的内容随组件卸载丢弃。
 * 接后端的入口是 lib/landing-contact-form.ts 的 submitContactEnquiry，
 * 把那个函数体换成 fetch 即可，本文件一行都不用改。
 * 在接上之前，成功态里那行 support@gmonkey.ai 不要删——
 * 它是访客唯一真正能送达的通路。
 *
 * 设计注释：
 * 这一页刻意不渲染顶部导航（和 Terms / Privacy 保持一致，只给一个返回链接）。
 * 原因是顶部导航前四项全是首页的同页锚点，在这一页上它们指向不存在的元素，
 * 点击后页面纹丝不动、控制台也不报错——正是最难被发现的那类故障。
 * 与其加一层"不在首页就跳回首页再滚动"的特例逻辑，不如让这页保持安静。
 *
 * 版式沿用全站语言：1px 细线切分、左对齐、大字号细体标题、
 * 表单输入框只有下边框而没有完整边框——参考稿的表单就是这种"横线信笺"的处理，
 * 完整描边的输入框会立刻把气质拉回普通 SaaS 表单。
 */

import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "wouter";
import { motion } from "framer-motion";
import { ArrowRight, Check } from "lucide-react";

import { ctaEmailHref, LANDING_ROUTES, SUPPORT_EMAIL } from "@/lib/landing-cta";
import {
  CONTACT_MESSAGE_MAX_LENGTH,
  EMPTY_CONTACT_FORM,
  hasContactFormErrors,
  submitContactEnquiry,
  validateContactForm,
  type ContactFieldName,
  type ContactFormErrors,
  type ContactFormValues,
} from "@/lib/landing-contact-form";

import { LandingFooter } from "./LandingFooter";
import { lpFadeUp, lpFast } from "./landing-motion";

/** 输入框样式。下划线式，聚焦时下边框转为强调色。 */
const FIELD_CLASS =
  "w-full border-0 border-b border-[var(--lp-border)] bg-transparent px-0 py-3 text-[0.95rem] text-[var(--lp-ink)] outline-none transition-colors duration-300 placeholder:text-[var(--lp-muted)] focus:border-[var(--lp-accent)]";

const FIELD_ERROR_CLASS = "border-[var(--lp-warn)]";

const LABEL_CLASS =
  "block text-[0.66rem] uppercase tracking-[0.18em] text-[var(--lp-muted)]";

type SubmitState = "idle" | "sending" | "sent";

export function LandingContactPage() {
  const { t } = useTranslation();

  const [values, setValues] = useState<ContactFormValues>(EMPTY_CONTACT_FORM);
  const [errors, setErrors] = useState<ContactFormErrors>({});
  const [state, setState] = useState<SubmitState>("idle");

  /**
   * 教学注释：
   * 校验只在提交时整体跑一遍，不在每次按键时跑。
   * 边输边校验会在用户刚打下第一个字母时就红一片（"这不是合法邮箱"），
   * 那是在用户还没写完的时候批评他。
   * 但一旦某个字段已经报过错，就切换成"边改边清"——用户正在修的字段
   * 一变成合法就立刻把红色去掉，这样他能确认自己改对了。
   */
  const updateField = (field: ContactFieldName, value: string) => {
    const nextValues = { ...values, [field]: value };
    setValues(nextValues);
    if (errors[field]) {
      const nextErrors = validateContactForm(nextValues);
      setErrors((previous) => {
        const merged = { ...previous };
        if (nextErrors[field]) {
          merged[field] = nextErrors[field];
        } else {
          delete merged[field];
        }
        return merged;
      });
    }
  };

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (state === "sending") {
      return;
    }

    const nextErrors = validateContactForm(values);
    setErrors(nextErrors);
    if (hasContactFormErrors(nextErrors)) {
      return;
    }

    setState("sending");
    await submitContactEnquiry(values);
    setState("sent");
  };

  const resetForm = () => {
    setValues(EMPTY_CONTACT_FORM);
    setErrors({});
    setState("idle");
  };

  const fieldError = (field: ContactFieldName) =>
    errors[field] ? t(`lp.contact.error.${errors[field]}`) : null;

  return (
    <div className="min-h-screen bg-[var(--lp-bg)] text-[var(--lp-ink)]">
      <main className="mx-auto max-w-[1180px] px-6 pb-24 pt-16 md:px-10 md:pb-32 md:pt-24">
        <Link
          href={LANDING_ROUTES.home}
          className="lp-mono text-[0.72rem] tracking-[0.1em] text-[var(--lp-muted)] transition-colors duration-300 hover:text-[var(--lp-ink)]"
        >
          ← {t("lp.legal.backToHome")}
        </Link>

        <motion.h1
          variants={lpFadeUp}
          initial="hidden"
          animate="visible"
          transition={lpFast(0.05)}
          className="lp-display mt-10 max-w-[720px] text-[clamp(1.9rem,4vw,3rem)] font-normal leading-[1.12] tracking-[-0.035em]"
        >
          {t("lp.contact.title")}
        </motion.h1>

        <motion.p
          variants={lpFadeUp}
          initial="hidden"
          animate="visible"
          transition={lpFast(0.15)}
          className="mt-7 max-w-[520px] text-[0.95rem] leading-[1.85] text-[var(--lp-muted)]"
        >
          {t("lp.contact.intro")}
        </motion.p>

        {/* 两栏。设计注释：表单放右边而不是左边，因为左侧承载的是
            "这家公司是真的" 这组信息——企业访客通常先确认对方存在，再决定要不要写信。 */}
        <div className="mt-16 grid grid-cols-1 gap-x-16 gap-y-14 border-t border-[var(--lp-border)] pt-14 lg:grid-cols-[minmax(0,320px)_minmax(0,1fr)]">
          {/* ---------- 左栏：真实联系方式 ---------- */}
          <aside className="space-y-10">
            <div>
              <p className={LABEL_CLASS}>{t("lp.contact.asideTitle")}</p>
              <a
                href={ctaEmailHref()}
                className="lp-mono mt-4 block text-[0.95rem] text-[var(--lp-ink)] underline underline-offset-4 transition-opacity duration-300 hover:opacity-70"
              >
                {SUPPORT_EMAIL}
              </a>
              <p className="mt-4 text-[0.85rem] leading-[1.8] text-[var(--lp-muted)]">
                {t("lp.contact.asideBody")}
              </p>
            </div>

            <div className="border-t border-[var(--lp-border)] pt-8">
              <p className={LABEL_CLASS}>{t("lp.contact.responseTitle")}</p>
              <p className="mt-4 text-[0.85rem] leading-[1.8] text-[var(--lp-muted)]">
                {t("lp.contact.responseBody")}
              </p>
            </div>

            <div className="border-t border-[var(--lp-border)] pt-8">
              <p className={LABEL_CLASS}>{t("lp.contact.entityTitle")}</p>
              <p className="mt-4 text-[0.85rem] leading-[1.8] text-[var(--lp-muted)]">
                <span className="text-[var(--lp-ink)]">{t("lp.footer.legalName")}</span>
                <br />
                {t("lp.footer.incorporation")}
              </p>
            </div>
          </aside>

          {/* ---------- 右栏：表单 / 成功态 ---------- */}
          <div className="border-t border-[var(--lp-border)] pt-10 lg:border-l lg:border-t-0 lg:pl-16 lg:pt-0">
            {state === "sent" ? (
              <motion.div
                variants={lpFadeUp}
                initial="hidden"
                animate="visible"
                transition={lpFast()}
                /* aria-live：成功提示是异步出现的，屏幕阅读器不会自动播报
                   一个静默插入的区块。不加这个属性，用视障辅助的用户点完提交后
                   得不到任何反馈，只能反复按提交。 */
                aria-live="polite"
                className="max-w-[520px]"
              >
                <span className="flex h-11 w-11 items-center justify-center rounded-full border border-[var(--lp-live)] text-[var(--lp-live)]">
                  <Check className="h-5 w-5" strokeWidth={1.5} />
                </span>
                <h2 className="lp-display mt-7 text-[1.5rem] font-normal leading-[1.25] tracking-[-0.02em]">
                  {t("lp.contact.success.title")}
                </h2>
                <p className="mt-4 text-[0.92rem] leading-[1.85] text-[var(--lp-muted)]">
                  {t("lp.contact.success.body")}
                </p>

                {/* ⚠️ 这一段在表单接上真实后端之前不要删。
                    表单目前不真发，这行邮箱是访客唯一能真正送达的通路。 */}
                <p className="mt-6 border-t border-[var(--lp-border)] pt-6 text-[0.92rem] leading-[1.85] text-[var(--lp-muted)]">
                  {t("lp.contact.success.emailPrompt")}{" "}
                  <a
                    href={ctaEmailHref()}
                    className="lp-mono text-[var(--lp-ink)] underline underline-offset-4 transition-opacity duration-300 hover:opacity-70"
                  >
                    {SUPPORT_EMAIL}
                  </a>
                </p>

                <button
                  type="button"
                  onClick={resetForm}
                  className="mt-9 flex items-center gap-3 text-[0.85rem] text-[var(--lp-ink)] transition-opacity duration-300 hover:opacity-70"
                >
                  <span className="border-b border-[var(--lp-border)] pb-0.5">
                    {t("lp.contact.success.again")}
                  </span>
                  <ArrowRight className="h-4 w-4" strokeWidth={1.25} />
                </button>
              </motion.div>
            ) : (
              <form onSubmit={handleSubmit} noValidate className="max-w-[560px]">
                {/* noValidate：关掉浏览器原生校验气泡。
                    原生气泡的样式无法控制、语言跟随浏览器而不是页面，
                    在英文页面上会冒出一个中文的"请填写此字段"。 */}
                <fieldset disabled={state === "sending"} className="space-y-9">
                  <legend className="sr-only">{t("lp.contact.form.legend")}</legend>

                  <ContactField
                    id="contact-name"
                    label={t("lp.contact.form.name")}
                    error={fieldError("name")}
                  >
                    <input
                      id="contact-name"
                      name="name"
                      type="text"
                      autoComplete="name"
                      value={values.name}
                      onChange={(event) => updateField("name", event.target.value)}
                      placeholder={t("lp.contact.form.namePlaceholder")}
                      aria-invalid={Boolean(errors.name)}
                      aria-describedby={errors.name ? "contact-name-error" : undefined}
                      className={`${FIELD_CLASS} ${errors.name ? FIELD_ERROR_CLASS : ""}`}
                    />
                  </ContactField>

                  <ContactField
                    id="contact-email"
                    label={t("lp.contact.form.email")}
                    error={fieldError("email")}
                  >
                    <input
                      id="contact-email"
                      name="email"
                      type="email"
                      autoComplete="email"
                      value={values.email}
                      onChange={(event) => updateField("email", event.target.value)}
                      placeholder={t("lp.contact.form.emailPlaceholder")}
                      aria-invalid={Boolean(errors.email)}
                      aria-describedby={errors.email ? "contact-email-error" : undefined}
                      className={`${FIELD_CLASS} ${errors.email ? FIELD_ERROR_CLASS : ""}`}
                    />
                  </ContactField>

                  <ContactField
                    id="contact-company"
                    label={t("lp.contact.form.company")}
                    hint={t("lp.contact.form.companyOptional")}
                    error={fieldError("company")}
                  >
                    <input
                      id="contact-company"
                      name="company"
                      type="text"
                      autoComplete="organization"
                      value={values.company}
                      onChange={(event) => updateField("company", event.target.value)}
                      placeholder={t("lp.contact.form.companyPlaceholder")}
                      className={FIELD_CLASS}
                    />
                  </ContactField>

                  <ContactField
                    id="contact-message"
                    label={t("lp.contact.form.message")}
                    error={fieldError("message")}
                  >
                    <textarea
                      id="contact-message"
                      name="message"
                      rows={5}
                      value={values.message}
                      onChange={(event) => updateField("message", event.target.value)}
                      placeholder={t("lp.contact.form.messagePlaceholder")}
                      maxLength={CONTACT_MESSAGE_MAX_LENGTH}
                      aria-invalid={Boolean(errors.message)}
                      aria-describedby={errors.message ? "contact-message-error" : undefined}
                      className={`${FIELD_CLASS} resize-y ${errors.message ? FIELD_ERROR_CLASS : ""}`}
                    />
                  </ContactField>
                </fieldset>

                <div className="mt-11 flex flex-wrap items-center gap-x-8 gap-y-4">
                  <button
                    type="submit"
                    disabled={state === "sending"}
                    className="rounded-full bg-[var(--lp-accent)] px-8 py-3.5 text-[0.85rem] tracking-[0.02em] text-white transition-opacity duration-300 hover:opacity-85 disabled:cursor-not-allowed disabled:opacity-55"
                  >
                    {state === "sending"
                      ? t("lp.contact.form.submitting")
                      : t("lp.contact.form.submit")}
                  </button>

                  {/* 汇总提示。原因注释：字段级红字可能落在视口外
                      （长表单里第一个错在最上面、按钮在最下面），
                      不给按钮旁边一句汇总的话，用户会以为按钮坏了。 */}
                  {hasContactFormErrors(errors) ? (
                    <p
                      role="alert"
                      className="text-[0.8rem] leading-[1.7] text-[var(--lp-warn)]"
                    >
                      {t("lp.contact.error.summary")}
                    </p>
                  ) : null}
                </div>
              </form>
            )}
          </div>
        </div>
      </main>

      <LandingFooter />
    </div>
  );
}

/**
 * 单个表单字段的外壳：标签、可选提示、错误行。
 *
 * 原因注释：抽出来是因为四个字段的标签排版、错误行位置、
 * 以及错误 id 和 aria-describedby 的对应关系必须完全一致。
 * 手写四遍的话，漏掉一个 aria-describedby 不会有任何可见后果，
 * 只有用读屏的人会遇到"这个框红了但不知道为什么"。
 */
function ContactField({
  id,
  label,
  hint,
  error,
  children,
}: {
  id: string;
  label: string;
  hint?: string;
  error: string | null;
  children: React.ReactNode;
}) {
  return (
    <div>
      <label htmlFor={id} className={LABEL_CLASS}>
        {label}
        {hint ? (
          <span className="ml-2 normal-case tracking-normal text-[var(--lp-muted)] opacity-70">
            ({hint})
          </span>
        ) : null}
      </label>
      <div className="mt-1">{children}</div>
      {error ? (
        <p id={`${id}-error`} className="mt-2 text-[0.78rem] text-[var(--lp-warn)]">
          {error}
        </p>
      ) : null}
    </div>
  );
}
