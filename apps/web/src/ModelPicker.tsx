import { useI18n } from "./i18n";
import type { ModelOption } from "./api";

export const firstAvailableModel = (options: ModelOption[]) =>
  options.find((option) => option.available)?.id || "default";
export const initialModelIds = (options: ModelOption[]) => {
  const available = options.find((option) => option.available);
  return available ? [available.id] : [];
};

export function ModelSelect({
  label,
  options,
  value,
  disabled,
  onChange,
}: {
  label: string;
  options: ModelOption[];
  value: string;
  disabled: boolean;
  onChange: (id: string) => void;
}) {
  const { t, locale, tag, ms, pct } = useI18n();
  const selected = options.find((option) => option.id === value);
  return (
    <label className="model-select">
      <span>{t(label)}</span>
      <select
        value={value}
        disabled={disabled}
        onChange={(event) => onChange(event.target.value)}
      >
        {options.map((option) => (
          <option
            key={option.id}
            value={option.id}
            disabled={!option.available}
          >
            {t(option.name)}
            {!option.available ? t(" · bağlantı gerekli") : ""}
          </option>
        ))}
      </select>
      <small>
        {selected?.model}
        {selected?.settings.provider_only?.length
          ? " · " + selected.settings.provider_only.join(", ")
          : ""}
      </small>
    </label>
  );
}

export function ModelChecklist({
  label,
  options,
  selected,
  disabled,
  onChange,
}: {
  label: string;
  options: ModelOption[];
  selected: string[];
  disabled: boolean;
  onChange: (ids: string[]) => void;
}) {
  const { t, locale, tag, ms, pct } = useI18n();
  return (
    <fieldset className="model-checklist" disabled={disabled}>
      <legend>
        {t(label)}{" "}
        <span>
          {selected.length}
          {t(" seçili")}
        </span>
      </legend>
      <div className="model-options">
        {options.map((option) => (
          <div
            key={option.id}
            className={
              "model-option" +
              (selected.includes(option.id) ? " is-selected" : "") +
              (!option.available ? " is-unavailable" : "")
            }
          >
            <label>
              <input
                type="checkbox"
                checked={selected.includes(option.id)}
                disabled={!option.available}
                onChange={(event) =>
                  onChange(
                    event.target.checked
                      ? [...selected, option.id]
                      : selected.filter((id) => id !== option.id),
                  )
                }
              />
              <span>
                <strong>{t(option.name)}</strong>
                <small>{option.model}</small>
                <small>
                  {t(
                    option.available
                      ? option.description
                      : option.unavailable_reason,
                  )}
                </small>
              </span>
            </label>
            {option.weights_url && (
              <a href={option.weights_url} target="_blank" rel="noreferrer">
                {option.license}
                {t(" · model kartı ↗")}
              </a>
            )}
          </div>
        ))}
      </div>
    </fieldset>
  );
}
