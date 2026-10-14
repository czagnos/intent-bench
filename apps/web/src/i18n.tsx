import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import {
  translate,
  formatPercent,
  formatDuration,
  languageTag,
  type Locale,
  type Translate,
} from "./i18n-core";
export type { Translate } from "./i18n-core";
const STORAGE_KEY = "intent-studio-language";
function savedLocale(): Locale {
  try {
    return localStorage.getItem(STORAGE_KEY) === "en" ? "en" : "tr";
  } catch {
    return "tr";
  }
}
const LanguageContext = createContext({
  locale: "tr" as Locale,
  setLocale: (_: Locale) => {},
  t: ((key) => key || "") as Translate,
  tag: "tr-TR",
  pct: (value: number | null | undefined) => formatPercent("tr", value),
  ms: (value: number | null | undefined) => formatDuration("tr", value),
});
export function LanguageProvider({
  children,
  initialLocale,
}: {
  children: ReactNode;
  initialLocale?: Locale;
}) {
  const [locale, setLocale] = useState<Locale>(initialLocale || savedLocale);
  useEffect(() => {
    document.documentElement.lang = locale;
    document
      .querySelector("meta[name=description]")
      ?.setAttribute(
        "content",
        locale === "en"
          ? "Banking intent routing and evaluation workspace"
          : "Bankacılık intent yönlendirme ve değerlendirme çalışma alanı",
      );
    document.title =
      locale === "en"
        ? "IntentBench · Banking PoC"
        : "IntentBench · Bankacılık PoC";
    try {
      localStorage.setItem(STORAGE_KEY, locale);
    } catch {
      /* Selection still works without storage. */
    }
  }, [locale]);
  const value = useMemo(
    () => ({
      locale,
      setLocale,
      tag: languageTag(locale),
      t: ((key, values) => translate(locale, key, values)) as Translate,
      pct: (v: number | null | undefined) => formatPercent(locale, v),
      ms: (v: number | null | undefined) => formatDuration(locale, v),
    }),
    [locale],
  );
  return (
    <LanguageContext.Provider value={value}>
      {children}
    </LanguageContext.Provider>
  );
}
export const useI18n = () => useContext(LanguageContext);
export function LanguageSelect() {
  const { locale, setLocale, t } = useI18n();
  return (
    <label className="language-select">
      <span className="sr-only">{t("Arayüz dili")}</span>
      <select
        aria-label={t("Arayüz dili")}
        value={locale}
        onChange={(event) => setLocale(event.target.value as Locale)}
      >
        <option value="tr">Türkçe</option>
        <option value="en">English</option>
      </select>
    </label>
  );
}
