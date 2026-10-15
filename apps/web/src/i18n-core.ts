import english from "./locales/en.json";
export type Locale = "tr" | "en";
export type Translate = (
  key: string | null | undefined,
  values?: Record<string, string | number>,
) => string;
// Compatibility for labels stored by older releases. New interface copy is English.
// Catalog definitions, user utterances and model conversation output bypass translation.
const dictionary: Record<string, string> = english;
export const languageTag = (locale: Locale) =>
  locale === "en" ? "en-US" : "tr-TR";
export function translate(
  locale: Locale,
  key: string | null | undefined,
  values: Record<string, string | number> = {},
): string {
  if (key == null) return "";
  const trimmed = key.trim();
  let result = key;
  if (locale === "en") {
    const translated = dictionary[trimmed];
    if (translated !== undefined) result = key.replace(trimmed, translated);
    else if (/ · varsayılan$/.test(key))
      result = key.replace(/ · varsayılan$/, " · default");
    else if (/^\d+ intent adayı bulundu$/.test(key))
      result = key.replace(
        "intent adayı bulundu",
        "intent candidates retrieved",
      );
    else if (key.endsWith(" için OpenRouter bağlantısı gerekli."))
      result = key.replace(
        " için OpenRouter bağlantısı gerekli.",
        " requires an OpenRouter connection.",
      );
    else if (key.startsWith("Bilinmeyen ") && key.includes(" model seçimi: "))
      result = key
        .replace("Bilinmeyen ", "Unknown ")
        .replace(" model seçimi: ", " model selection: ");
    else if (/^\d+\. kayıttaki soru 2000 karakter sınırını aşıyor\.$/.test(key))
      result = key.replace(
        /^(\d+)\..*$/,
        "Question in row $1 exceeds the 2000-character limit.",
      );
    else if (key.endsWith(" için karışabilecek intent eşlemesi eksik."))
      result = key.replace(
        " için karışabilecek intent eşlemesi eksik.",
        ": confusable intent mapping is missing.",
      );
    else if (key.endsWith(" için slot sorusu eksik."))
      result = key.replace(
        " için slot sorusu eksik.",
        ": a slot question is missing.",
      );
    else if (
      /^Tek deneyde en fazla \d+ model kombinasyonu seçilebilir\.$/.test(key)
    )
      result = key.replace(
        /.* (\d+) model.*/,
        "A maximum of $1 model combinations can be selected per experiment.",
      );
    else if (/^Katalog büyüklüğü \d+ ile \d+ arasında olmalı/.test(key))
      result = key.replace(
        /^Katalog büyüklüğü (\d+) ile (\d+).*$/,
        "Catalog size must be between $1 and $2. Required test, context and calibration intents are retained.",
      );
    else if (/^(Embedding|LLM|OpenRouter): /.test(key)) {
      const index = key.indexOf(": ") + 2;
      result = key.slice(0, index) + translate(locale, key.slice(index));
    }
  }
  return result.replace(/\{(\w+)\}/g, (match, name: string) =>
    values[name] === undefined ? match : String(values[name]),
  );
}
export const formatPercent = (
  locale: Locale,
  value: number | null | undefined,
) =>
  value == null
    ? "—"
    : new Intl.NumberFormat(languageTag(locale), {
        style: "percent",
        minimumFractionDigits: 1,
        maximumFractionDigits: 1,
      }).format(value);
export const formatDuration = (
  locale: Locale,
  value: number | null | undefined,
) =>
  value == null
    ? "—"
    : value >= 1000
      ? new Intl.NumberFormat(languageTag(locale), {
          minimumFractionDigits: 2,
          maximumFractionDigits: 2,
        }).format(value / 1000) + (locale === "en" ? " s" : " sn")
      : Math.round(value) + " ms";
