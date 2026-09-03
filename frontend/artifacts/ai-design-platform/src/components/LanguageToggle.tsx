import { useTranslation } from "react-i18next";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { normalizeSupportedLocale, SUPPORTED_LANGUAGE_OPTIONS, type SupportedLocale } from "@/lib/locale";

export function LanguageToggle() {
  const { t, i18n } = useTranslation();
  const currentLanguage = normalizeSupportedLocale(i18n.language);

  return (
    <Select
      value={currentLanguage}
      onValueChange={(value) => void i18n.changeLanguage(value as SupportedLocale)}
    >
      <SelectTrigger
        aria-label={t("language.label")}
        className="h-10 min-w-[132px] rounded-full border-white/10 bg-black/20 px-4 text-sm text-foreground shadow-none"
      >
        <SelectValue />
      </SelectTrigger>
      <SelectContent className="border-white/10 bg-black/95 text-foreground">
        {SUPPORTED_LANGUAGE_OPTIONS.map((option) => (
          <SelectItem key={option.value} value={option.value} className="text-sm">
            {option.label}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}
