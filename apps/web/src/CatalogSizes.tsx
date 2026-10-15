import { useI18n } from "./i18n";

export function parseCatalogSizes(
  text: string,
  minimum: number,
  maximum: number,
): number[] {
  const parts = text.split(",").map((part) => part.trim());
  if (!parts.length || parts.some((part) => !/^\d+$/.test(part))) return [];
  const sizes = [...new Set(parts.map(Number))].sort((a, b) => a - b);
  return sizes.length <= 8 &&
    sizes.every((size) => size >= minimum && size <= maximum)
    ? sizes
    : [];
}

export function CatalogSizes({
  value,
  onChange,
  minimum,
  maximum,
  disabled,
}: {
  value: string;
  onChange: (value: string) => void;
  minimum: number;
  maximum: number;
  disabled: boolean;
}) {
  const { t } = useI18n();
  const sizes = parseCatalogSizes(value, minimum, maximum);
  const presets = [...new Set([48, 100, 200, 400, 800, maximum])]
    .filter((n) => n >= minimum && n <= maximum)
    .sort((a, b) => a - b);
  return (
    <div className="catalog-size-control">
      <label>
        {t("Catalog sizes to search")}
        <input
          aria-label={t("Catalog sizes to search")}
          value={value}
          disabled={disabled}
          onChange={(event) => onChange(event.target.value)}
          placeholder={presets.join(", ")}
          aria-invalid={!sizes.length}
        />
      </label>
      <div
        className="catalog-size-presets"
        role="group"
        aria-label={t("Catalog size presets")}
      >
        {presets.map((size) => (
          <button
            key={size}
            type="button"
            className="button subtle"
            disabled={disabled}
            aria-pressed={sizes.includes(size)}
            onClick={() =>
              onChange(
                (sizes.includes(size)
                  ? sizes.filter((n) => n !== size)
                  : [...sizes, size]
                )
                  .sort((a, b) => a - b)
                  .join(", "),
              )
            }
          >
            {size}
          </button>
        ))}
        <button
          type="button"
          className="button subtle"
          disabled={disabled}
          onClick={() => onChange(presets.join(", "))}
        >
          {t("Compare all sizes")}
        </button>
      </div>
      <p className="field-hint">
        {t(
          "Sets how many intents retrieval can search. The test cases stay fixed; larger catalogs contain the smaller catalogs.",
        )}
      </p>
      <p className="field-hint">
        {t(
          "Available catalog: {total} intents. Choose up to 8 sizes from {minimum} to {total}. Test or calibration labels may require a higher minimum.",
          { total: maximum, minimum },
        )}
      </p>
      {!sizes.length && (
        <p className="selection-warning" role="alert">
          {t("Enter valid catalog sizes separated by commas.")}
        </p>
      )}
    </div>
  );
}
