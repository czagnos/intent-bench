import type { Candidate, Decision, Intent, Stage } from "./api";

export const demoViews = [
  ["standard", "Standart"],
  ["workflow", "Workflow haritası"],
  ["radial", "Dairesel harita"],
  ["galaxy", "Intent galaksisi"],
  ["mosaic", "Intent mozaiği"],
] as const;
export type DemoView = (typeof demoViews)[number][0];
export type MapView = Exclude<DemoView, "standard">;
export const VIEW_STORAGE_KEY = "intent-studio-demo-view";
export function savedDemoView(): DemoView {
  try {
    const value = localStorage.getItem(VIEW_STORAGE_KEY);
    return demoViews.find(([id]) => id === value)?.[0] || "standard";
  } catch {
    return "standard";
  }
}

export function routeCandidates(
  stages: Stage[],
  result?: Decision,
): Candidate[] {
  // An empty final list is meaningful: a contextual reply may skip retrieval.
  if (result) return result.candidates;
  return (
    [...stages].reverse().find((event) => event.candidates !== undefined)
      ?.candidates || []
  );
}
export function selectedIntentId(result?: Decision): string | null {
  return result &&
    ["route", "continue"].includes(result.decision) &&
    result.workflow_id
    ? result.intent_id
    : null;
}
export function mergeStages(current: Stage[], incoming: Stage[]): Stage[] {
  const byId = new Map(current.map((event) => [event.id, event]));
  incoming.forEach((event) => byId.set(event.id, event));
  return [...byId.values()].sort((a, b) => a.id - b.id);
}
export function replayEvents(stages: Stage[]): Stage[] {
  // Replay only stages actually reported by the server, in event order.
  return mergeStages([], stages).filter((event) =>
    ["context", "retrieval", "reranking", "selection", "policy"].includes(event.stage),
  );
}

export type CatalogGroup = { name: string; intents: Intent[] };
export function groupCatalog(intents: Intent[]): CatalogGroup[] {
  const domains = new Map<string, Intent[]>();
  for (const intent of intents) {
    const group = domains.get(intent.domain) || [];
    group.push(intent);
    domains.set(intent.domain, group);
  }
  return [...domains].map(([name, entries]) => ({
    name,
    intents: [...entries].sort((a, b) =>
      a.intent_id.localeCompare(b.intent_id, "en"),
    ),
  }));
}
export function visibleIntentIds(
  candidates: Candidate[],
  result?: Decision,
): string[] {
  const selected = selectedIntentId(result);
  return [
    ...new Set([
      ...(selected ? [selected] : []),
      ...(result?.clarification_options || []).map(
        (option) => option.intent_id,
      ),
      ...candidates.map((candidate) => candidate.intent_id),
    ]),
  ].slice(0, 6);
}

export type Point = { x: number; y: number };
export type Box = Point & { w: number; h: number };
export type IntentMark = Point & {
  intent: Intent;
  shape: "circle" | "rect" | "arc" | "card";
  w?: number;
  h?: number;
  r?: number;
  d?: string;
};
export type DomainMark = Box & {
  name: string;
  count: number;
  shape: "box" | "cloud" | "arc";
  d?: string;
  labelX?: number;
  labelY?: number;
  showLabel?: boolean;
};
export type MapLayout = {
  width: number;
  height: number;
  source: Point;
  vertical: boolean;
  groups: DomainMark[];
  marks: IntentMark[];
};
const clamp = (n: number, min: number, max: number) =>
  Math.min(max, Math.max(min, n));
const polar = (center: Point, radius: number, angle: number): Point => ({
  x: center.x + radius * Math.cos(angle),
  y: center.y + radius * Math.sin(angle),
});
export function connection(
  source: Point,
  target: Point,
  vertical = false,
): string {
  const dx = target.x - source.x,
    dy = target.y - source.y;
  const length = Math.hypot(dx, dy) || 1;
  const start = {
    x: source.x + (dx / length) * 25,
    y: source.y + (dy / length) * 25,
  };
  if (vertical) {
    const y = (start.y + target.y) / 2;
    return `M ${start.x} ${start.y} C ${start.x} ${y}, ${target.x} ${y}, ${target.x} ${target.y}`;
  }
  const x = (start.x + target.x) / 2;
  return `M ${start.x} ${start.y} C ${x} ${start.y}, ${x} ${target.y}, ${target.x} ${target.y}`;
}
export function ringPath(
  center: Point,
  r0: number,
  r1: number,
  a0: number,
  end: number,
): string {
  const a1 = Math.min(end, a0 + Math.PI * 2 - 0.00001);
  const p0 = polar(center, r1, a0),
    p1 = polar(center, r1, a1);
  const p2 = polar(center, r0, a1),
    p3 = polar(center, r0, a0);
  const large = a1 - a0 > Math.PI ? 1 : 0;
  return `M ${p0.x} ${p0.y} A ${r1} ${r1} 0 ${large} 1 ${p1.x} ${p1.y} L ${p2.x} ${p2.y} A ${r0} ${r0} 0 ${large} 0 ${p3.x} ${p3.y} Z`;
}

type Weighted = { key: string; weight: number };
export function partition(items: Weighted[], area: Box): (Box & Weighted)[] {
  if (!items.length) return [];
  if (items.length === 1) return [{ ...area, ...items[0] }];
  const total = items.reduce((sum, item) => sum + item.weight, 0);
  let weight = 0,
    split = 1;
  for (let i = 0; i < items.length - 1; i++) {
    weight += items[i].weight;
    split = i + 1;
    if (weight >= total / 2) break;
  }
  const ratio = weight / total;
  const [a, b] =
    area.w >= area.h
      ? [
          { ...area, w: area.w * ratio },
          { ...area, x: area.x + area.w * ratio, w: area.w * (1 - ratio) },
        ]
      : [
          { ...area, h: area.h * ratio },
          { ...area, y: area.y + area.h * ratio, h: area.h * (1 - ratio) },
        ];
  return [
    ...partition(items.slice(0, split), a),
    ...partition(items.slice(split), b),
  ];
}
export function wrapLabel(
  value: string,
  width: number,
  maxLines = 2,
): string[] {
  const limit = Math.max(6, Math.floor(width / 7.3));
  const words = value.split(/\s+/);
  const lines: string[] = [];
  let line = "";
  for (const word of words) {
    if (line && line.length + word.length + 1 > limit) {
      lines.push(line);
      line = "";
    }
    line += (line ? " " : "") + word;
  }
  if (line) lines.push(line);
  const visible = lines
    .slice(0, maxLines)
    .map((part) =>
      part.length > limit ? part.slice(0, limit - 1) + "…" : part,
    );
  if (lines.length > maxLines && visible.length)
    visible[visible.length - 1] = visible.at(-1)!.slice(0, limit - 1) + "…";
  return visible;
}

export function layoutMap(
  view: MapView,
  allGroups: CatalogGroup[],
  width: number,
  height: number,
  focusDomain: string | null,
  focusedIds: string[] | null,
): MapLayout {
  const vertical = width < 450;
  const source = vertical
    ? { x: width / 2, y: 40 }
    : { x: 46, y: height / 2 - 20 };
  const area = {
    x: vertical ? 16 : 112,
    y: vertical ? 100 : 34,
    w: vertical ? width - 32 : width - 134,
    h: vertical ? height - 165 : height - 99,
  };
  const groups = focusDomain
    ? allGroups.filter((g) => g.name === focusDomain)
    : allGroups;
  const layout: MapLayout = {
    width,
    height,
    source,
    vertical,
    groups: [],
    marks: [],
  };
  if (view === "workflow") {
    const byId = new Map(
      allGroups
        .flatMap((group) => group.intents)
        .map((intent) => [intent.intent_id, intent]),
    );
    const chosen = (focusedIds || [])
      .map((id) => byId.get(id))
      .filter((i): i is Intent => !!i);
    if (chosen.length) {
      const step = Math.min(69, area.h / chosen.length);
      const h = Math.min(59, step - 8);
      chosen.forEach((intent, index) =>
        layout.marks.push({
          intent,
          shape: "card",
          x: area.x,
          y: area.y + index * step,
          w: area.w,
          h,
        }),
      );
    } else {
      const columns = width > 660 ? 3 : 2,
        gap = 10;
      const rows = Math.ceil(allGroups.length / columns);
      const w = (area.w - gap * (columns - 1)) / columns;
      const h = Math.min(54, (area.h - gap * (rows - 1)) / Math.max(1, rows));
      const startY =
        area.y + Math.max(0, (area.h - rows * (h + gap) + gap) / 2);
      allGroups.forEach((g, i) =>
        layout.groups.push({
          name: g.name,
          count: g.intents.length,
          shape: "box",
          x: area.x + (i % columns) * (w + gap),
          y: startY + Math.floor(i / columns) * (h + gap),
          w,
          h,
        }),
      );
    }
    return layout;
  }
  if (view === "radial") {
    const center = { x: width / 2, y: height / 2 - 18 };
    layout.source = center;
    const radius = Math.min(width * (vertical ? 0.32 : 0.37), height * 0.35);
    const total = groups.reduce((sum, g) => sum + g.intents.length, 0) || 1;
    let offset = 0;
    groups.forEach((g) => {
      const start = -Math.PI / 2 + (2 * Math.PI * offset) / total;
      const end = start + (2 * Math.PI * g.intents.length) / total;
      const pos = polar(center, radius + 22, (start + end) / 2);
      const labelWidth = Math.min(g.name.length * 7, 112);
      layout.groups.push({
        name: g.name,
        count: g.intents.length,
        shape: "arc",
        x: center.x,
        y: center.y,
        w: 0,
        h: 0,
        d: ringPath(
          center,
          radius * 0.46,
          radius * 0.71,
          start + 0.002,
          end - 0.002,
        ),
        labelX: clamp(pos.x, labelWidth / 2 + 10, width - labelWidth / 2 - 10),
        labelY: pos.y,
        showLabel: end - start > 0.22 || groups.length === 1,
      });
      g.intents.forEach((intent) => {
        const a0 = -Math.PI / 2 + (2 * Math.PI * offset) / total;
        const a1 = -Math.PI / 2 + (2 * Math.PI * (offset + 1)) / total;
        const point = polar(center, radius * 0.9, (a0 + a1) / 2);
        layout.marks.push({
          intent,
          shape: "arc",
          ...point,
          d: ringPath(center, radius * 0.77, radius, a0 + 0.0003, a1 - 0.0003),
        });
        offset++;
      });
    });
    return layout;
  }
  if (view === "galaxy") {
    const columns = Math.max(
      1,
      Math.ceil(Math.sqrt((groups.length * area.w) / area.h)),
    );
    const rows = Math.ceil(groups.length / columns);
    const cellW = area.w / columns,
      cellH = area.h / Math.max(1, rows);
    const maxCount = Math.max(1, ...groups.map((g) => g.intents.length));
    groups.forEach((g, index) => {
      const center = {
        x: area.x + ((index % columns) + 0.5) * cellW,
        y: area.y + (Math.floor(index / columns) + 0.43) * cellH,
      };
      const radius =
        Math.min(cellW * 0.34, cellH * 0.29) *
        Math.max(0.3, Math.sqrt(g.intents.length / maxCount));
      layout.groups.push({
        name: g.name,
        count: g.intents.length,
        shape: "cloud",
        ...center,
        w: radius * 2 + 12,
        h: radius * 2 + 10,
        labelX: center.x,
        labelY: center.y + radius + 20,
      });
      g.intents.forEach((intent, i) => {
        const angle = i * 2.399963229728653;
        const r = Math.sqrt((i + 0.5) / g.intents.length) * radius;
        layout.marks.push({
          intent,
          shape: "circle",
          ...polar(center, r, angle),
          r: focusDomain ? 3 : 1.9,
        });
      });
    });
    return layout;
  }
  const boxes = partition(
    groups.map((g) => ({ key: g.name, weight: g.intents.length })),
    area,
  );
  const grouped = new Map(groups.map((g) => [g.name, g]));
  boxes.forEach((box) => {
    const g = grouped.get(box.key)!;
    const w = Math.max(1, box.w - 6),
      h = Math.max(1, box.h - 6);
    const showLabel = w > 76 && h > 65;
    const header = showLabel ? 27 : 0;
    layout.groups.push({
      name: g.name,
      count: g.intents.length,
      shape: "box",
      x: box.x + 3,
      y: box.y + 3,
      w,
      h,
      showLabel,
    });
    const tiles = partition(
      g.intents.map((intent) => ({ key: intent.intent_id, weight: 1 })),
      {
        x: box.x + 7,
        y: box.y + header + 7,
        w: Math.max(1, w - 8),
        h: Math.max(1, h - header - 8),
      },
    );
    const intents = new Map(
      g.intents.map((intent) => [intent.intent_id, intent]),
    );
    tiles.forEach((tile) =>
      layout.marks.push({
        intent: intents.get(tile.key)!,
        shape: "rect",
        x: tile.x + 0.8,
        y: tile.y + 0.8,
        w: Math.max(0.3, tile.w - 1.6),
        h: Math.max(0.3, tile.h - 1.6),
      }),
    );
  });
  return layout;
}

export function markCenter(mark: IntentMark): Point {
  return mark.shape === "rect" || mark.shape === "card"
    ? { x: mark.x + mark.w! / 2, y: mark.y + mark.h! / 2 }
    : mark;
}
