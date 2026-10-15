import { useEffect, type ReactNode } from "react";
import { translate, formatPercent, formatDuration, type Translate } from "./i18n-core";
export type { Translate } from "./i18n-core";

const english = {
  locale: "en" as const,
  tag: "en-US",
  t: ((key, values) => translate("en", key, values)) as Translate,
  pct: (value: number | null | undefined) => formatPercent("en", value),
  ms: (value: number | null | undefined) => formatDuration("en", value),
};

export function LanguageProvider({ children }: { children: ReactNode }) {
  useEffect(() => {
    document.documentElement.lang = "en";
    document.title = "IntentBench · Decision Model Benchmarks";
    document.querySelector("meta[name=description]")?.setAttribute(
      "content", "Benchmark decision models for intent routing across industries",
    );
  }, []);
  return children;
}
export const useI18n = () => english;
