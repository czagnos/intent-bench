# Live demo views

Select a **Sector workspace**, then use **View** below the live-demo counters:

| View | Display |
|---|---|
| Standard | Conversation, decision, candidates, and measured timings |
| Workflow map | Functional domains and candidate intent cards after retrieval |
| Radial map | Request in the center, domains inside, intents around the outside |
| Intent galaxy | Intent points grouped by domain |
| Intent mosaic | One cell per intent in a catalog grouped by domain |

The browser remembers the view. Changing views within the same live conversation preserves model choices, the in-flight request, and the result. View changes and replay make no extra model call. The interface is English; catalog and conversation content retain their source language.

Changing **Sector workspace** is a different operation: the application loads that workspace's catalog/models and starts a new conversation. Registered connections, catalog additions, cases, and experiment history stay with their workspace. The browser remembers the selected sector.

## Live behavior

- Layout uses actual domains, IDs, and counts from the active catalog. Demo suggestions come from its examples, rather than fixed banking questions.
- Retrieval candidates arrive through the existing SSE request before the final decision. If an older server omits intermediate candidates, the final result supplies them.
- The selected intent comes from the final decision, not automatically the first search candidate. A successful-route color requires `route`/`continue` and a valid workflow mapping.
- Clarification, out-of-scope, handoff, cancellation, and technical error have distinct outcomes. Clarification options come from the decision payload.
- Supported workflow replies such as amounts or confirmations show their own turn's events. When context bypasses retrieval, the prior turn's candidates do not carry forward.
- Workflow previews show required information, collected values, and supported simulation confirmation/completion state. They do not execute business operations. Unknown custom fields remain a bounded preview rather than an unsupported collection loop.
- **Full catalog / Focus** changes the visible extent. Expand the details below the graphic to inspect candidates and decisions.

Domains are visual groups; the maps add no domain-classification stage to inference. Only the selected map renders. Positions are stable by catalog ID rather than a new physical simulation for every message. The workflow map opens at most six relevant cards; other maps show the full catalog or focused domain. Layout recalculates for narrow screens.

## Replay and measurements

**Replay** presents the recorded stages of a completed request. Its presentation timing is not model latency. **Pause / Resume** and view switching remain available, and replay never delays the actual conversation response.

A new message or conversation clears the old replay. Late events from an older request do not update the new conversation. Playback pauses in a hidden tab. Reduced-motion preferences suppress transitions/path animation while retaining the real states and decisions.

Displayed milliseconds come from the server's `timings_ms.total`. Animation does not alter this value or experiment p95. This screen illustrates a routing computation; it is not a load test or an accuracy benchmark.

## API and catalog versions

`POST /v1/route?workspace=airline` returns the request's pinned `catalog_version`. Intermediate retrieval events carry `candidates` and that version alongside `id`, `at`, `stage`, and `label`. Final application respects conversation revision checks. `pending_confirmation` records actual simulation confirmation state.

`GET /v1/catalog?workspace=airline&version=<version>` reads a saved snapshot within that workspace; missing snapshots return 404. The map loads the version used by its request even if another editor changes the current catalog. Reading a snapshot does not mutate the live catalog or invoke a model.

All requests, SSE connections, and fallback polls remain bound to the workspace in which they started. The full workspace UI remounts on a sector change, closing its old live stream and dialogs. Late catalog loads cannot restore previous models or catalog data.

## Update and verify

```bash
npm --prefix apps/web run build
```

Restart the API with your process manager. No new model key or visual-library dependency is required. Run backend tests before the build, not concurrently with it.

Backend tests cover early candidates, event replay, catalog snapshots, workspace separation, and workflow state. React/jsdom tests cover view switching during requests, actual selected candidates, negative decisions, contextual continuation, replay, stale events, English defaults, saved workspace selection, and map geometry. These checks do not measure live provider quality, browser rendering speed, or replace a visual browser inspection.

## Pitfalls

- An SSE connection can stop delivering events without raising `error`. After five seconds without a stage, the live demo switches to request-status polling so a completed first request still appears without navigating away. Keep this inactivity timer covered by the same completion and abort cleanup as the stream and polling timer.
- Cold vector-index preparation can take longer than two minutes. The response timeout measures time without a stage or successful status response, not the total lifetime of an accepted request; a server-confirmed queued/running job must remain active until its result arrives.
- Closing SSE and clearing its polling timer do not cancel an already pending fetch callback. Pass the abort signal to polling, suppress overlapping polls, and gate all callbacks after completion/abort.
- Bind each request client to an immutable workspace. A global mutable workspace can send an old request's fallback poll to the newly selected sector.
- Remount workspace state and guard stale catalog refreshes. Keeping only the page view isolated can leave old model dialogs, sessions, or delayed refresh results active.
