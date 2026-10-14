import { memo, useEffect, useId, useMemo, useRef, useState } from "react";
import {
  Check,
  LoaderCircle,
  Pause,
  Play,
  RotateCcw,
  Workflow,
  ZoomIn,
  ZoomOut,
} from "lucide-react";
import {
  api,
  type Candidate,
  type Decision,
  type Intent,
  type Stage,
} from "./api";
import { useI18n } from "./i18n";
import {
  connection,
  groupCatalog,
  layoutMap,
  markCenter,
  replayEvents,
  routeCandidates,
  selectedIntentId,
  visibleIntentIds,
  wrapLabel,
  type CatalogGroup,
  type IntentMark,
  type MapView,
} from "./routing-map";

const decisionLabels: Record<string, string> = {
  route: "Yönlendirildi",
  continue: "Akış sürüyor",
  clarify: "Netleştirme gerekli",
  out_of_scope: "Kapsam dışı",
  handoff: "Temsilciye aktarım",
  cancel: "İptal edildi",
  error: "Bağlantı hatası",
};
const stageLabels: Record<string, string> = {
  context: "Konuşma bağlamı",
  retrieval: "Aday arama",
  reranking: "Adayları yeniden sıralama",
  selection: "Intent seçimi",
  policy: "Karar kontrolü",
};
const mapLabels: Record<MapView, string> = {
  workflow: "Workflow haritası",
  radial: "Dairesel harita",
  galaxy: "Intent galaksisi",
  mosaic: "Intent mozaiği",
};

type Props = {
  view: MapView;
  catalog: Intent[];
  catalogVersion: string;
  requestedCatalogVersion?: string;
  stages: Stage[];
  result?: Decision;
  busy: boolean;
  error: string;
  turnId: number;
};

function useMapWidth() {
  const ref = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(640);
  useEffect(() => {
    const element = ref.current;
    if (!element) return;
    const update = () => {
      const next = Math.round(element.getBoundingClientRect().width);
      if (next > 0) setWidth(Math.max(240, next));
    };
    update();
    if (typeof ResizeObserver !== "undefined") {
      const observer = new ResizeObserver(update);
      observer.observe(element);
      return () => observer.disconnect();
    }
    window.addEventListener("resize", update);
    return () => window.removeEventListener("resize", update);
  }, []);
  return { ref, width };
}

function MapText({
  x,
  y,
  value,
  width,
  className = "",
  anchor = "middle",
  lines = 2,
}: {
  x: number;
  y: number;
  value: string;
  width: number;
  className?: string;
  anchor?: "start" | "middle" | "end";
  lines?: number;
}) {
  return (
    <text x={x} y={y} textAnchor={anchor} className={className}>
      {wrapLabel(value, width, lines).map((line, i) => (
        <tspan key={i} x={x} dy={i ? 15 : 0}>
          {line}
        </tspan>
      ))}
    </text>
  );
}

const IntentGlyph = memo(function IntentGlyph({
  mark,
  status,
}: {
  mark: IntentMark;
  status: string;
}) {
  const attrs = {
    className: `routing-intent ${status}`,
    "data-intent-id": mark.intent.intent_id,
    "data-state": status,
  };
  const title = (
    <title>
      {mark.intent.name} · {mark.intent.domain}
    </title>
  );
  if (mark.shape === "circle")
    return (
      <circle
        {...attrs}
        cx={mark.x}
        cy={mark.y}
        r={status === "selected" ? 5 : status === "candidate" ? 3.5 : mark.r}
      >
        {title}
      </circle>
    );
  if (mark.shape === "arc")
    return (
      <path {...attrs} d={mark.d}>
        {title}
      </path>
    );
  if (mark.shape === "rect")
    return (
      <rect
        {...attrs}
        x={mark.x}
        y={mark.y}
        width={mark.w}
        height={mark.h}
        rx={2}
      >
        {title}
      </rect>
    );
  return (
    <g {...attrs}>
      {title}
      <rect x={mark.x} y={mark.y} width={mark.w} height={mark.h} rx={9} />
      <MapText
        x={mark.x + 13}
        y={mark.y + 20}
        value={mark.intent.name}
        width={mark.w! - 26}
        anchor="start"
        lines={1}
      />
      <MapText
        x={mark.x + 13}
        y={mark.y + 40}
        value={mark.intent.domain}
        width={mark.w! - 26}
        anchor="start"
        lines={1}
        className="routing-muted"
      />
    </g>
  );
});

function RoutingMap({
  view,
  groups,
  candidates,
  result,
  busy,
  error,
  focus,
  reduced,
  eventKey,
}: {
  view: MapView;
  groups: CatalogGroup[];
  candidates: Candidate[];
  result?: Decision;
  busy: boolean;
  error: string;
  focus: boolean;
  reduced: boolean;
  eventKey: string;
}) {
  const { t } = useI18n();
  const { ref, width } = useMapWidth();
  const height = width < 450 ? 540 : 490;
  const gridId = useId().replaceAll(":", "");
  const selectedId = selectedIntentId(result);
  const intentById = useMemo(
    () =>
      new Map(groups.flatMap((g) => g.intents).map((i) => [i.intent_id, i])),
    [groups],
  );
  const selected = selectedId ? intentById.get(selectedId) : undefined;
  const ids = visibleIntentIds(candidates, result);
  const idsKey = ids.join("\u0000");
  const candidateDomains = [
    ...new Set(ids.map((id) => intentById.get(id)?.domain).filter(Boolean)),
  ];
  // No domain is chosen as a classification step; grouping only changes the viewport.
  const focusDomain = focus
    ? selected?.domain ||
      (result?.decision === "clarify" && candidateDomains.length === 1
        ? candidateDomains[0]!
        : null)
    : null;
  const layout = useMemo(
    () =>
      layoutMap(view, groups, width, height, focusDomain, focus ? ids : null),
    [view, groups, width, height, focusDomain, focus, idsKey],
  );
  const candidateIds = new Set([
    ...candidates.map((candidate) => candidate.intent_id),
    ...(result?.clarification_options || []).map((option) => option.intent_id),
  ]);
  const positions = new Map(
    layout.marks.map((mark) => [mark.intent.intent_id, mark]),
  );
  const activeDomains = new Set(
    [...candidateIds].map((id) => intentById.get(id)?.domain),
  );
  const edges = ids.flatMap((id) => {
    const mark = positions.get(id);
    if (mark) {
      const target =
        mark.shape === "card"
          ? { x: mark.x, y: mark.y + mark.h! / 2 }
          : markCenter(mark);
      return [
        {
          id,
          d: connection(layout.source, target, layout.vertical),
          selected: id === selectedId,
        },
      ];
    }
    const domain = intentById.get(id)?.domain;
    const parent = layout.groups.find((g) => g.name === domain);
    return parent && view === "workflow"
      ? [
          {
            id,
            d: connection(
              layout.source,
              { x: parent.x, y: parent.y + parent.h / 2 },
              layout.vertical,
            ),
            selected: id === selectedId,
          },
        ]
      : [];
  });
  const terminal =
    result && !["route", "continue"].includes(result.decision)
      ? result.decision
      : error
        ? "error"
        : null;
  const exit = { x: width / 2, y: height - 29 };
  const exitPath = terminal ? connection(layout.source, exit, true) : null;
  const selectedPath = edges.find((edge) => edge.selected)?.d;
  const animatedPath = exitPath || selectedPath;
  const count = groups.reduce((sum, g) => sum + g.intents.length, 0);
  return (
    <div
      ref={ref}
      className={`routing-map ${reduced ? "reduced-motion" : ""}`}
      data-view={view}
      data-focus={
        focusDomain || (focus && ids.length ? "candidates" : "overview")
      }
    >
      <svg
        width="100%"
        height={height}
        viewBox={`0 0 ${width} ${height}`}
        role="img"
        aria-label={t("{view}: {count} intent", {
          view: t(mapLabels[view]),
          count,
        })}
      >
        <desc>
          {t("Bağlantılar yönlendirmeyi, alanlar katalog gruplarını gösterir.")}
        </desc>
        <defs>
          <pattern
            id={gridId}
            width="22"
            height="22"
            patternUnits="userSpaceOnUse"
          >
            <circle cx="1" cy="1" r="0.7" fill="#dce4f1" />
          </pattern>
        </defs>
        <rect
          width={width}
          height={height}
          fill={`url(#${gridId})`}
          opacity="0.45"
        />
        {view === "workflow" &&
          !layout.marks.length &&
          layout.groups.map((g) => (
            <path
              key={g.name}
              className="routing-structural-edge"
              d={connection(
                layout.source,
                { x: g.x, y: g.y + g.h / 2 },
                layout.vertical,
              )}
            />
          ))}
        {layout.groups.map((g) => (
          <g
            key={g.name}
            className={`routing-domain ${activeDomains.has(g.name) ? "has-candidates" : ""}`}
            data-domain={g.name}
          >
            <title>
              {g.name} · {g.count} {t("intent")}
            </title>
            {g.shape === "arc" ? (
              <path d={g.d} />
            ) : g.shape === "cloud" ? (
              <ellipse cx={g.x} cy={g.y} rx={g.w / 2} ry={g.h / 2} />
            ) : (
              <rect x={g.x} y={g.y} width={g.w} height={g.h} rx={8} />
            )}
          </g>
        ))}
        {layout.marks.map((mark) => (
          <IntentGlyph
            key={mark.intent.intent_id}
            mark={mark}
            status={
              mark.intent.intent_id === selectedId
                ? "selected"
                : candidateIds.has(mark.intent.intent_id)
                  ? "candidate"
                  : "idle"
            }
          />
        ))}
        {layout.groups.map((g) => {
          if (g.showLabel === false) return null;
          if (g.shape !== "box")
            return (
              <MapText
                key={g.name}
                x={g.labelX!}
                y={g.labelY!}
                width={110}
                value={g.name}
                className="routing-domain-label"
              />
            );
          const top = view === "workflow" ? g.y + 20 : g.y + 18;
          return (
            <g key={g.name}>
              <MapText
                x={g.x + 10}
                y={top}
                width={g.w - 20}
                anchor="start"
                lines={1}
                value={g.name}
                className="routing-domain-label"
              />
              {view === "workflow" && (
                <text x={g.x + 10} y={g.y + 40} className="routing-muted">
                  {t("{count} intent", { count: g.count })}
                </text>
              )}
            </g>
          );
        })}
        {edges.map((edge) => (
          <path
            key={edge.id}
            className={`routing-edge ${edge.selected ? "selected" : terminal ? "dimmed" : "candidate"}`}
            d={edge.d}
          />
        ))}
        <g className={`routing-source ${busy || result ? "active" : ""}`}>
          <circle
            cx={layout.source.x}
            cy={layout.source.y}
            r="30"
            className="routing-source-halo"
          />
          <circle cx={layout.source.x} cy={layout.source.y} r="24" />
          <text x={layout.source.x} y={layout.source.y + 4} textAnchor="middle">
            {t("Giriş")}
          </text>
        </g>
        {terminal && (
          <g
            className={`routing-exit ${terminal === "error" ? "error" : ""}`}
            data-outcome={terminal}
          >
            <path d={exitPath!} />
            <rect
              x={exit.x - Math.min(width - 32, 232) / 2}
              y={exit.y - 20}
              width={Math.min(width - 32, 232)}
              height="40"
              rx="9"
            />
            <text x={exit.x} y={exit.y + 4} textAnchor="middle">
              {t(decisionLabels[terminal] || terminal)}
            </text>
          </g>
        )}
        {animatedPath && !reduced && (
          <circle
            key={`${eventKey}:${view}:${focus}:${terminal || selectedId}`}
            r="4.5"
            className={`routing-packet ${terminal ? "terminal" : ""}`}
            opacity="0"
          >
            <animate
              attributeName="opacity"
              values="0;1;1;0"
              keyTimes="0;0.02;0.9;1"
              dur="0.85s"
              fill="freeze"
            />
            <animateMotion path={animatedPath} dur="0.85s" fill="freeze" />
          </circle>
        )}
      </svg>
      <div className="routing-map-legend">
        <span>
          {focusDomain
            ? `${focusDomain} · ${t("{count} intent", { count: groups.find((g) => g.name === focusDomain)?.intents.length || 0 })}`
            : t("{count} alan", { count: groups.length })}
        </span>
        <span>
          <i className="candidate" />
          {t("Aday")}
          <i className="selected" />
          {t("Seçilen intent")}
        </span>
      </div>
    </div>
  );
}

function WorkflowPreview({
  result,
  intent,
}: {
  result: Decision;
  intent?: Intent;
}) {
  const { t } = useI18n();
  if (!selectedIntentId(result)) return null;
  const required =
    intent?.required_slots ||
    Object.keys({
      ...result.slots,
      ...Object.fromEntries(result.missing_slots.map((id) => [id, ""])),
    });
  const slotLabels: Record<string, string> = {
    new_limit: "Yeni limit",
    card_last4: "Kartın son dört hanesi",
    transfer_reference: "Transfer referansı",
  };
  return (
    <div className="routing-workflow" data-workflow={result.workflow_id!}>
      <div className="routing-workflow-heading">
        <Workflow size={18} />
        <div>
          <strong>{result.intent_name || intent?.name}</strong>
          <small>{t("İşlem simülasyonu")}</small>
        </div>
      </div>
      <ol>
        {required.map((slot) => {
          const value = result.slots[slot],
            missing = result.missing_slots.includes(slot);
          return (
            <li
              key={slot}
              className={missing ? "pending" : value ? "done" : ""}
            >
              <span className="routing-step-point">
                {value && <Check size={11} />}
              </span>
              <div>
                <strong>{t(slotLabels[slot] || slot)}</strong>
                <small>
                  {value || (missing ? t("Bekleniyor") : t("Tamamlandı"))}
                </small>
              </div>
            </li>
          );
        })}
        {!!required.length && (
          <li
            className={
              result.simulation_complete
                ? "done"
                : result.pending_confirmation
                  ? "pending"
                  : ""
            }
            data-confirmation={String(!!result.pending_confirmation)}
          >
            <span className="routing-step-point">
              {result.simulation_complete && <Check size={11} />}
            </span>
            <div>
              <strong>{t("Müşteri onayı")}</strong>
              {result.pending_confirmation && <small>{t("Bekleniyor")}</small>}
            </div>
          </li>
        )}
        <li
          className={
            result.simulation_complete
              ? "done"
              : required.length
                ? ""
                : "pending"
          }
        >
          <span className="routing-step-point">
            {result.simulation_complete && <Check size={11} />}
          </span>
          <div>
            <strong>
              {t(
                result.simulation_complete
                  ? "Simülasyon tamamlandı"
                  : required.length
                    ? "Simülasyonu tamamla"
                    : "Akış önizlemesi hazır",
              )}
            </strong>
          </div>
        </li>
      </ol>
      <p className="routing-next-message">{result.message}</p>
    </div>
  );
}

export default function RoutingVisualization({
  view,
  catalog,
  catalogVersion,
  requestedCatalogVersion,
  stages,
  result,
  busy,
  error,
  turnId,
}: Props) {
  const { t, ms } = useI18n();
  const targetVersion =
    result?.catalog_version ||
    requestedCatalogVersion ||
    stages.find((event) => event.catalog_version)?.catalog_version ||
    catalogVersion;
  const [snapshot, setSnapshot] = useState<{
    version: string;
    intents: Intent[];
  }>();
  const [catalogError, setCatalogError] = useState("");
  const [focus, setFocus] = useState(true);
  const [reduced, setReduced] = useState(
    () => !!window.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches,
  );
  const [replay, setReplay] = useState<{
    turnId: number;
    index: number;
    paused: boolean;
  } | null>(null);
  const events = useMemo(() => replayEvents(stages), [stages]);
  const replaying = !!replay && replay.turnId === turnId && !busy;
  const completeFrame = !replaying || replay!.index > events.length;
  const shownStages = replaying ? events.slice(0, replay!.index) : stages;
  const shownResult = completeFrame ? result : undefined;
  const shownError = completeFrame ? error : "";
  const candidates = routeCandidates(shownStages, shownResult);
  const actualCatalog =
    !targetVersion || targetVersion === catalogVersion
      ? catalog
      : snapshot?.version === targetVersion
        ? snapshot.intents
        : undefined;
  const groups = useMemo(
    () => groupCatalog(actualCatalog || []),
    [actualCatalog],
  );
  const intent = actualCatalog?.find(
    (i) => i.intent_id === selectedIntentId(shownResult),
  );

  useEffect(() => {
    if (
      !targetVersion ||
      targetVersion === catalogVersion ||
      snapshot?.version === targetVersion
    )
      return;
    const controller = new AbortController();
    setCatalogError("");
    api<{ version: string; intents: Intent[] }>(
      "/catalog?version=" + encodeURIComponent(targetVersion),
      { signal: controller.signal },
    )
      .then((value) => {
        if (controller.signal.aborted) return;
        if (value.version !== targetVersion)
          throw new Error("Katalog sürümü eşleşmiyor.");
        setSnapshot(value);
      })
      .catch((e) => {
        if (!controller.signal.aborted) setCatalogError((e as Error).message);
      });
    return () => controller.abort();
  }, [targetVersion, catalogVersion, snapshot?.version]);
  useEffect(() => {
    setReplay(null);
    setFocus(true);
  }, [turnId]);
  useEffect(() => {
    const media = window.matchMedia?.("(prefers-reduced-motion: reduce)");
    if (!media) return;
    const update = () => setReduced(media.matches);
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, []);
  useEffect(() => {
    if (!replaying || replay!.paused) return;
    const timer = window.setTimeout(() => {
      setReplay((current) =>
        !current || current.turnId !== turnId
          ? current
          : current.index > events.length
            ? null
            : { ...current, index: current.index + 1 },
      );
    }, 950);
    return () => window.clearTimeout(timer);
  }, [replaying, replay, turnId, events.length]);
  useEffect(() => {
    const pause = () => {
      if (document.hidden)
        setReplay((current) => (current ? { ...current, paused: true } : null));
    };
    document.addEventListener("visibilitychange", pause);
    return () => document.removeEventListener("visibilitychange", pause);
  }, []);

  const statusText = shownResult
    ? t(decisionLabels[shownResult.decision] || shownResult.decision)
    : shownError
      ? t("Bağlantı hatası")
      : shownStages.length
        ? t(shownStages.at(-1)!.label)
        : busy || replaying
          ? t("İstek işleniyor")
          : t("İlk mesajı bekliyor");
  const canFocus =
    !!selectedIntentId(shownResult) ||
    candidates.length > 0 ||
    !!shownResult?.clarification_options.length;
  const sampleKey = `${turnId}:${shownStages.map((event) => event.id).join(",")}:${shownResult?.decision || "pending"}`;
  return (
    <section
      className="panel routing-visualization"
      aria-label={t("Canlı yönlendirme görünümü")}
    >
      <div className="panel-heading routing-visual-heading">
        <div>
          <h2>{t(mapLabels[view])}</h2>
          <small>
            {actualCatalog
              ? t("{count} intent", { count: actualCatalog.length })
              : t("Katalog yükleniyor…")}
          </small>
        </div>
        <div className="routing-map-actions">
          <button
            type="button"
            className="button subtle"
            onClick={() => setFocus((value) => !value)}
            disabled={!canFocus}
            title={t(focus ? "Tüm katalog" : "Adaylara yaklaş")}
          >
            {focus ? <ZoomOut size={15} /> : <ZoomIn size={15} />}
            <span>{t(focus ? "Tüm katalog" : "Yakın görünüm")}</span>
          </button>
          <button
            type="button"
            className="button subtle"
            disabled={busy || (!result && !error)}
            onClick={() =>
              setReplay((value) =>
                replaying && value
                  ? { ...value, paused: !value.paused }
                  : { turnId, index: 0, paused: false },
              )
            }
          >
            {replaying ? (
              replay!.paused ? (
                <Play size={15} />
              ) : (
                <Pause size={15} />
              )
            ) : (
              <RotateCcw size={15} />
            )}
            {t(
              replaying
                ? replay!.paused
                  ? "Devam et"
                  : "Duraklat"
                : "Tekrar oynat",
            )}
          </button>
        </div>
      </div>
      <div className="routing-statusbar">
        <span aria-live="polite">{statusText}</span>
        <span>
          {replaying ? t("TEKRAR OYNATMA") : t("CANLI")}
          {result ? ` · ${ms(result.timings_ms.total)}` : ""}
        </span>
      </div>
      {!actualCatalog ? (
        <div className="empty">
          {catalogError ? (
            <p role="alert">{t(catalogError)}</p>
          ) : (
            <>
              <LoaderCircle className="spin" size={22} />
              <p>{t("İsteğin katalog sürümü yükleniyor…")}</p>
            </>
          )}
        </div>
      ) : (
        <RoutingMap
          view={view}
          groups={groups}
          candidates={candidates}
          result={shownResult}
          busy={busy || (replaying && !completeFrame)}
          error={shownError}
          focus={focus}
          reduced={reduced}
          eventKey={sampleKey}
        />
      )}
      <div className="routing-trace" aria-label={t("Gerçek işlem aşamaları")}>
        {shownStages
          .filter((event) => stageLabels[event.stage])
          .map((event) => (
            <span key={event.id}>
              <Check size={12} />
              {t(stageLabels[event.stage])}
            </span>
          ))}
        {!shownStages.length && (
          <span>{t("İşlem aşamaları burada görünecek.")}</span>
        )}
      </div>
      {shownResult && <WorkflowPreview result={shownResult} intent={intent} />}
      {shownResult?.decision === "clarify" && (
        <div className="routing-clarification">
          <p>{shownResult.message}</p>
          {shownResult.clarification_options.map((option) => (
            <span key={option.intent_id}>{option.name}</span>
          ))}
        </div>
      )}
      {shownError && !shownResult && (
        <p className="routing-error" role="alert">
          {t(shownError)}
        </p>
      )}
      <div className="routing-caption">
        <small>{t("Animasyon süresi ölçümlere dahil değildir.")}</small>
        <small>
          {t("Katalog ")}
          {targetVersion?.slice(0, 8)}
        </small>
      </div>
    </section>
  );
}
