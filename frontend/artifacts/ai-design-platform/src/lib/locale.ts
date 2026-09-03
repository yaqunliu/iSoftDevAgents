export type SupportedLocale = "en" | "zh" | "ja" | "ko" | "ru" | "fr" | "de";

export type BackendLocale = "en" | "zh";
export type ModuleTranslationLocale = SupportedLocale;

export type SupportedLanguageOption = {
  value: SupportedLocale;
  label: string;
};

export const SUPPORTED_LANGUAGE_OPTIONS: SupportedLanguageOption[] = [
  { value: "en", label: "English" },
  { value: "zh", label: "中文" },
  { value: "ja", label: "日本語" },
  { value: "ko", label: "한국어" },
  { value: "ru", label: "Русский" },
  { value: "fr", label: "Français" },
  { value: "de", label: "Deutsch" },
];

const SUPPORTED_LOCALE_SET = new Set<SupportedLocale>(
  SUPPORTED_LANGUAGE_OPTIONS.map((item) => item.value),
);

/**
 * 接口注释：
 * 把浏览器语言、本地存储语言、或 i18n 当前语言统一收口成平台支持的语言代码。
 * 这里会自动吃掉 `zh-CN`、`en-US` 这种带地区后缀的值，避免界面各处重复判断。
 */
export function normalizeSupportedLocale(language: string | null | undefined): SupportedLocale {
  const normalized = String(language ?? "")
    .trim()
    .toLowerCase();
  const baseLanguage = normalized.split("-")[0] as SupportedLocale | "";
  if (baseLanguage && SUPPORTED_LOCALE_SET.has(baseLanguage)) {
    return baseLanguage;
  }
  return "en";
}

/**
 * 设计注释：
 * 当前后端接口仍然只稳定支持 `en/zh` 两种 locale。
 * 所以前端扩语言时，先保持中文走 `zh`，其它语言统一安全回退到 `en`，
 * 这样可以先把前端语言切换打通，而不会误伤现有后端工作流。
 */
export function backendLocaleForLanguage(language: string | null | undefined): BackendLocale {
  return normalizeSupportedLocale(language) === "zh" ? "zh" : "en";
}

/**
 * 教学注释：
 * 模块说明文案现在已经支持前端全部语言。
 * 这里直接返回归一化后的语言代码，避免模块卡片和页面其他区域语言不一致。
 */
export function moduleTranslationLocaleForLanguage(language: string | null | undefined): ModuleTranslationLocale {
  return normalizeSupportedLocale(language);
}

export function dateLocaleForLanguage(language: string | null | undefined): string {
  switch (normalizeSupportedLocale(language)) {
    case "zh":
      return "zh-CN";
    case "ja":
      return "ja-JP";
    case "ko":
      return "ko-KR";
    case "ru":
      return "ru-RU";
    case "fr":
      return "fr-FR";
    case "de":
      return "de-DE";
    case "en":
    default:
      return "en-US";
  }
}
