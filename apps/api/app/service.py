import copy
import json
import threading
import time
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from typing import Literal, TypedDict

from .config import ROOT, Settings
from .calibration import Calibrator, data_fingerprint, public_calibration
from .catalog_scope import core_ids, select_catalogs
from .catalog_presets import workspace_preset
from .contracts import Intent
from .case_context import PreTurnContext, validate_case_context
from .importer import parse_benchmark
from .transcript_data import StoredImportReportData
from .evaluation import summarize, diagnose
from .evaluation_types import EvaluationCheckpoint, EvaluationMetrics, EvaluationResult
from .execution import EvaluationController, EvaluationStopped, ExecutionAccounting, ExecutionLimits, activate_execution, execution_checkpoint, execution_stage
from .model_catalog import MAX_VARIANTS, ModelCatalog, embedding_key, embedding_runtime_key, llm_metadata
from .policy import apply_decision, baseline_decision, context_decision, explicit_workflow_slots
from .providers import is_openrouter
from .retrieval import Embeddings, ModelUnavailable, Retriever, tokens
from .reranker import Reranker
from .repeat_statistics import RepeatGroupSummary, RepeatResult, summarize_repeats
from .selector import Selector, prompt_version
from .store import Store, fingerprint
from .vector_index import CorpusRow, VectorIndex, build_corpus, make_identity


class _RerankerRuntimeSettings(TypedDict):
    model: str
    mode: Literal["disabled", "local", "http"]
    protocol: Literal["cohere", "tei"] | None
    endpoint: str | None
    credential: str | None
    timeout_seconds: float | None
    batch_size: int | None
    local_files_only: bool | None


def _reranker_runtime_key(settings: Settings) -> str:
    """Private identity of compatible inference; independent of the retrieval/LLM variant."""
    identity: _RerankerRuntimeSettings = {
        "model": settings.reranker_model, "mode": settings.reranker_mode,
        "protocol": settings.reranker_protocol if settings.reranker_mode == "http" else None,
        "endpoint": settings.reranker_base_url.strip().rstrip("/") if settings.reranker_mode == "http" else None,
        "credential": settings.reranker_api_key.strip() if settings.reranker_mode == "http" else None,
        "timeout_seconds": settings.reranker_timeout_seconds if settings.reranker_mode == "http" else None,
        "batch_size": settings.reranker_batch_size if settings.reranker_mode == "local" else None,
        "local_files_only": settings.reranker_local_files_only if settings.reranker_mode == "local" else None,
    }
    return fingerprint(identity)


def repeated_summaries(
    results: Sequence[EvaluationResult], group_ids: Sequence[str], repetitions: int,
) -> list[RepeatGroupSummary]:
    """Pass only the run statistics and outcome identities to the repeat reducer."""
    projected: list[RepeatResult] = [{
        "group_id": result["group_id"], "repeat_index": result["repeat_index"],
        "complete": result["complete"], "completed_count": result["completed_count"],
        "selected_count": result["selected_count"],
        "metrics": {
            "routing_accuracy": result["metrics"]["routing_accuracy"],
            "decision_accuracy": result["metrics"]["decision_accuracy"],
            "macro_f1": result["metrics"]["macro_f1"],
            "recall_at_k": result["metrics"]["recall_at_k"],
            "latency_ms": {"p95": result["metrics"]["latency_ms"]["p95"]},
            "errors": result["metrics"]["errors"], "total": result["metrics"]["total"],
        },
        "records": [{"case_id": record["case_id"], "decision": record["decision"],
                     "intent_id": record["intent_id"]} for record in result["records"]],
    } for result in results]
    return summarize_repeats(projected, group_ids=group_ids, planned_repetitions=repetitions)


class Studio:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.store = Store(settings.data_dir)
        self.embeddings = Embeddings(settings)
        self.selector = Selector(settings)
        self.reranker = Reranker(settings)
        self.reranker_clients = {}
        self.model_catalog = ModelCatalog(settings, self.store)
        self.embedding_clients = {}
        self.retrievers = {}
        self.lock = threading.Lock()
        self.router_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="route")
        self.evaluation_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="evaluation")
        self.calibrator = Calibrator(self)
        self.seeded_workspaces = set()

    def close(self):
        self.router_pool.shutdown(wait=True, cancel_futures=True)
        self.evaluation_pool.shutdown(wait=True, cancel_futures=True)

    def import_benchmark(self, workspace: str, content: bytes,
                         filename: str = "benchmark.csv") -> StoredImportReportData:
        self.ensure_workspace(workspace)
        cases, report = parse_benchmark(content, filename)
        catalog = self.store.catalog(workspace)
        intents = {item["intent_id"]: Intent.model_validate(item) for item in catalog["intents"]}
        for case in cases:
            validate_case_context(PreTurnContext.model_validate(case["context"]), intents)
        return self.store.import_cases(workspace, cases, report, expected_catalog_version=catalog["version"])

    def ensure_workspace(self, workspace):
        with self.lock:
            if workspace in self.seeded_workspaces:
                return
            preset = workspace_preset(workspace)
            intents = preset.intents()
            expanded = [intent.model_dump() for intent in intents]
            seed_cases = preset.cases()
            benchmark_cases = preset.benchmark_cases()
            cases = [json.loads(case.payload) for case in seed_cases]
            current = self.store.catalog(workspace)
            if current is None:
                self.store.bootstrap_workspace(workspace, intents, seed_cases + benchmark_cases)
            if preset.id == "banking":
                # Historical targets are required to upgrade untouched v1 records before
                # the separate English migration. Never translate arbitrary user records.
                historical = json.loads((ROOT / "data/demo/migrations/taxonomy-v2-targets.json").read_text())
                manifest = json.loads((ROOT / "data/demo/migrations/taxonomy-v2.json").read_text())
                english = json.loads((ROOT / "data/demo/migrations/english-v3.json").read_text())
                previous_hashes = set(manifest["previous_catalog_hashes"].values()) | set(english["previous_catalog_hashes"].values())
                legacy = current is not None and any(
                    fingerprint(Intent.model_validate(intent).model_dump()) in previous_hashes
                    for intent in current["intents"])
                # An already-English core must never acquire a transient Turkish version.
                baseline = historical["intents"] if legacy else expanded
                baseline_cases = historical["cases"] if legacy else cases
                self.store.expand_demo_catalog(workspace, core_ids(), baseline)
                self.store.revise_demo(workspace, manifest, baseline, baseline_cases, core_ids())
                self.store.revise_demo(workspace, english, expanded, cases, core_ids())
            else:
                for revision in preset.revisions():
                    self.store.expand_preset(workspace, revision, intents, seed_cases)
            self.store.expand_preset(workspace, preset.benchmark_revision(), intents, benchmark_cases)
            self.seeded_workspaces.add(workspace)

    def retriever(self, workspace, version=None, settings=None):
        settings = settings or self.settings
        catalog = self.store.catalog(workspace, version)
        if not catalog:
            raise ValueError("Catalog not found.")
        model_key = embedding_runtime_key(settings)
        key = (workspace, catalog["version"], model_key)
        with self.lock:
            if key not in self.retrievers or not self.retrievers[key].index_is_current():
                self.retrievers[key] = self._new_retriever(
                    workspace, catalog["version"], [Intent.model_validate(i) for i in catalog["intents"]], settings)
                if len(self.retrievers) > 32:
                    del self.retrievers[next(iter(self.retrievers))]
            return self.retrievers[key]

    def _new_retriever(self, workspace: str, version: str, intents: list[Intent], settings: Settings) -> Retriever:
        # Called while holding the Studio lock; clients and RAM entries share its scope.
        model_key = embedding_runtime_key(settings)
        if model_key == embedding_runtime_key(self.embeddings.settings):
            embeddings = self.embeddings
        else:
            embeddings = self.embedding_clients.setdefault(model_key, Embeddings(settings, transport=self.embeddings.transport))
        return self._retriever_with_embeddings(workspace, version, intents, embeddings)

    def _retriever_with_embeddings(
        self, workspace: str, version: str, intents: list[Intent], embeddings: Embeddings,
    ) -> Retriever:
        settings = embeddings.settings
        rows = build_corpus(intents, settings.retrieval_representation)
        formatted = embeddings.prepare_texts([row.text for row in rows])
        identity = make_identity(workspace, version, embedding_key(settings), settings.retrieval_representation,
                                 [CorpusRow(row.intent_id, row.evidence, text) for row, text in zip(rows, formatted)])
        index = VectorIndex(self.settings.data_dir / "vector-indexes", identity)
        return Retriever(intents, version, embeddings, index)

    def prepare_catalog(self, workspace: str, intents: list[Intent]) -> Retriever:
        """Prepare vectors before the caller publishes an imported catalog."""
        version = fingerprint([intent.model_dump() for intent in intents])
        with self.lock:
            retriever = self._new_retriever(workspace, version, intents, self.settings)
        if retriever.embeddings.enabled:
            retriever.prepare_index()
        return retriever

    def methods(self, workspace="demo"):
        embedding, llm = self.embeddings.enabled, self.settings.llm_configured
        if not (embedding and llm):
            for record in self.model_catalog.registry.records(workspace):
                if self.model_catalog.registry.public(record)["available"]:
                    embedding = embedding or record["kind"] == "embedding"
                    llm = llm or record["kind"] == "llm"
                if embedding and llm:
                    break
        return [
            {"id": "lexical", "name": "Lexical baseline", "available": True, "description": "Character similarity + BM25. Uses no semantic model or LLM.", "model": "char-tfidf+bm25-v1", "calibrated": False},
            {"id": "e5", "name": "Semantic retrieval", "available": embedding, "description": "Nearest intent using the selected multilingual embedding model.", "model": self.settings.embedding_model, "calibrated": False},
            {"id": "hybrid_llm", "name": "Hybrid retrieval + LLM", "available": embedding and llm, "description": "Embedding and lexical retrieval, with contextual selection by the chosen LLM.", "model": self.settings.llm_model, "calibrated": False},
        ]

    def get_reranker(self, settings):
        # A private runtime identity; neither endpoints nor credentials enter exported results.
        key = _reranker_runtime_key(settings)
        with self.lock:
            if key not in self.reranker_clients:
                self.reranker_clients[key] = Reranker(settings, transport=self.reranker.transport)
            return self.reranker_clients[key]

    def compute(self, text, state, method, retriever, channel="chat", emit=None, variant=None, preparation_error=None, calibration=None, reranker: Reranker | None = None):
        started = time.perf_counter()
        settings = variant.settings if variant else self.settings
        timings, candidates, usage = {}, [], {}
        trace = {"executed": False, "context_bypass": False}
        pool = []
        error_stage = None
        phase = "context"
        profile = variant.retrieval if variant else None
        emit = emit or (lambda *_, **__: None)
        try:
            if preparation_error:
                phase = "preparation"
                raise preparation_error
            t = time.perf_counter()
            proposal = context_decision(text, state)
            trace["context_bypass"] = proposal is not None
            timings["context"] = (time.perf_counter()-t)*1000
            emit("context", "Conversation context ready")
            if proposal is None:
                phase = "retrieval"
                t = time.perf_counter()
                query = text
                if len(tokens(text)) < 5 and state.get("messages"):
                    query += " " + state["messages"][-1]["content"][:200]
                mode = {"lexical": "lexical", "e5": "e5", "hybrid_llm": "hybrid"}[method]
                if profile and profile.source == "semantic":
                    mode = "e5"
                trace = {"executed": True, "completed": False, "source": mode}
                pool, trace = retriever.search_with_trace(query, mode, profile.pool_k if profile else settings.candidate_k,
                                                        state.get("active_intent"), profile.source_k if profile else 40,
                                                        profile.semantic_weight if profile else .5)
                candidates = pool[:settings.candidate_k]
                timings["retrieval"] = (time.perf_counter()-t)*1000
                emit("retrieval", f"{len(pool)} intent candidates retrieved", candidates=[c.model_dump() for c in pool])
                trace["reranker_used"] = bool(profile and profile.reranker_id)
                if profile and profile.reranker_id:
                    phase = "reranking"
                    candidates = []
                    trace["final"] = []
                    t = time.perf_counter()
                    candidates = (reranker or self.get_reranker(settings)).rank(query, pool, retriever.intents, settings.candidate_k)
                    timings["reranking"] = (time.perf_counter()-t)*1000
                    emit("reranking", f"{len(candidates)} candidates reranked", candidates=[c.model_dump() for c in candidates])
                trace["final"] = [c.intent_id for c in candidates]
                phase = "selection"
                t = time.perf_counter()
                if method == "hybrid_llm":
                    selector = Selector(settings, transport=self.selector.transport) if variant else self.selector
                    proposal, usage = selector.select(text, state, candidates, retriever.intents)
                else:
                    threshold = calibration.get("threshold") if method == "e5" and calibration else None
                    proposal = baseline_decision(text, candidates, state, semantic=method == "e5", rejection_threshold=threshold)
                timings["selection"] = (time.perf_counter()-t)*1000
                trace["selection_completed"] = True
                trace["proposal_decision"] = proposal.decision
                trace["proposal_intent_id"] = proposal.intent_id
                emit("selection", "Intent decision generated")
            phase = "policy"
            t = time.perf_counter()
            if proposal.decision == "route" and proposal.intent_id in retriever.intents:
                proposal.slots = explicit_workflow_slots(text, retriever.intents[proposal.intent_id])
            result, new_state = apply_decision(proposal, state, retriever.intents, channel)
            timings["policy"] = (time.perf_counter()-t)*1000
            emit("policy", "Decision and workflow mapping validated")
        except (ModelUnavailable, ValueError) as exc:
            error_stage = phase
            if phase not in timings and phase not in ("preparation",):
                timings[phase] = (time.perf_counter()-t)*1000
            result = {"decision": "error", "intent_id": None, "intent_name": None, "workflow_id": None, "slots": {}, "missing_slots": [], "clarification_options": [], "message": str(exc), "reason_code": "technical_error", "simulation": True, "simulation_complete": False}
            result["diagnostics"] = getattr(exc, "diagnostics", None)
            new_state = copy.deepcopy(state)
        timings["compute_total"] = (time.perf_counter()-started)*1000
        result.update(method=method, candidates=[c.model_dump() for c in candidates], timings_ms={k: round(v, 2) for k, v in timings.items()}, usage=usage, catalog_version=retriever.version, prompt_version=prompt_version(settings) if method == "hybrid_llm" else None, model=settings.llm_model if method == "hybrid_llm" else (settings.embedding_model if method == "e5" else "char-tfidf+bm25-v1"), calibration=None)
        result["embedding"] = retriever.embeddings.metadata if method in ("e5", "hybrid_llm") else None
        result["llm"] = llm_metadata(settings) if method == "hybrid_llm" else None
        result.update(index_preparation=trace.get("index_preparation"), retrieval_trace=trace, retrieval_candidates=[c.model_dump() for c in pool], error_stage=error_stage)
        result["calibration"] = calibration
        result["rejection_score"] = candidates[0].score if method == "e5" and candidates else None
        if variant:
            result["variant"] = variant.metadata
        new_state["messages"] = (state.get("messages", []) + [{"role": "user", "content": text}, {"role": "assistant", "content": result["message"]}])[-12:]
        return result, new_state

    def run_route(self, workspace, request, state, catalog_version, variant=None, calibration=None):
        job = self.store.job(workspace, request.request_id)
        self.store.patch_job(workspace, request.request_id, {"status": "running"})
        def emit(stage, label, **data):
            self.store.patch_job(workspace, request.request_id, {"event": {"stage": stage, "label": label, "catalog_version": catalog_version, **data}})
        try:
            variant = variant or self.model_catalog.variant(request.method, request.embedding_id, request.llm_id, workspace, request.retrieval_profile)
            retriever = self.retriever(workspace, catalog_version, variant.settings)
            result, updated = self.compute(request.user_text, state, request.method, retriever, request.channel, emit, variant, calibration=calibration)
            result["timings_ms"]["total"] = round((time.time()-job["created"])*1000, 2)
            result.update(request_id=request.request_id, session_id=request.session_id, turn_revision=request.turn_revision)
            saved = self.store.finish_turn(workspace, updated, request.turn_revision)
            if not saved:
                self.store.patch_job(workspace, request.request_id, {"status": "superseded", "error": "A newer conversation turn exists; the earlier decision was not applied.", "result": result})
            else:
                self.store.patch_job(workspace, request.request_id, {"status": "failed" if result["decision"] == "error" else "completed", "result": result, "event": {"stage": "complete", "label": "Decision ready"}})
        except Exception:
            self.store.patch_job(workspace, request.request_id, {"status": "failed", "error": "The request could not be processed. Check the service configuration."})

    def start_evaluation(self, workspace, options):
        variants = self.model_catalog.expand(options, workspace)
        if options.execution_limits.max_reported_cost_usd is not None:
            for variant in variants:
                settings = variant.settings
                unsupported_embedding = (variant.method != "lexical" and settings.embedding_mode == "http"
                                         and not is_openrouter(settings.embedding_base_url))
                unsupported_llm = (variant.method == "hybrid_llm"
                                   and (settings.llm_protocol != "openai" or not is_openrouter(settings.llm_base_url)))
                unsupported_reranker = (variant.retrieval and variant.retrieval.reranker_id
                                        and settings.reranker_mode == "http")
                if unsupported_embedding or unsupported_llm or unsupported_reranker:
                    raise ValueError("Reported USD limits require supported OpenRouter remote inference. Local models are allowed.")
        all_cases = self.store.cases(workspace, options.source, split=options.split)
        cases = [c for c in all_cases if c["reviewed"]][:options.limit]
        if not cases:
            raise ValueError("No reviewed labeled cases match this selection. Save expected decisions on the Cases page first.")
        self.store.validate_conversation_separation(workspace, (case.get("conversation_id") for case in cases))
        catalog = self.store.catalog(workspace)
        scale_fit = options.catalog_sizes is not None and options.semantic_rejection == "calibrated" and any(v.method == "e5" for v in variants)
        fit_cases = self.calibrator.cases(workspace, options.scale_calibration_source) if scale_fit else []
        if scale_fit:
            self.calibrator.validate_cases(workspace, fit_cases, catalog)
            from .calibration import question_hash
            if {question_hash(c["question"]) for c in fit_cases} & {question_hash(c["question"]) for c in cases}:
                raise ValueError("Cases used for calibration cannot be tested with the same threshold. Select a separate test split.")
        scopes = select_catalogs(catalog, options.catalog_sizes, cases, fit_cases, options.catalog_seed)
        if len(scopes)*len(variants) > MAX_VARIANTS:
            raise ValueError(f"At most {MAX_VARIANTS} combinations can run, including catalog sizes.")
        if len(cases)*len(scopes)*len(variants)*options.repetitions > 100000:
            raise ValueError("At most 100000 case executions can run, including repetitions.")
        runs, calibrations = [], {}
        for variant in variants:
            for scope in scopes:
                run_id = variant.id if options.catalog_sizes is None else f"{variant.id}__catalog_{scope['metadata']['intent_count']}_{scope['version'][:8]}"
                metadata = {**variant.metadata, "id": run_id, "base_variant_id": variant.id, "catalog": scope["metadata"]}
                runs.append((variant, scope, metadata))
                calibrations[run_id] = None if scale_fit and variant.method == "e5" else self.calibrator.resolve(workspace, variant, scope["version"], options.semantic_rejection, cases)
        runs = [(variant, scope, {**metadata, "group_id": metadata["id"], "repeat_index": repeat_index,
                                 "id": metadata["id"] if options.repetitions == 1 else f"{metadata['id']}__repeat_{repeat_index}"})
                for repeat_index in range(1, options.repetitions + 1) for variant, scope, metadata in runs]
        for scope in scopes:
            self.store.save_catalog_snapshot(workspace, scope)
        job = self.store.create_job(workspace, "evaluation", {
            "options": options.model_dump(), "variants": [metadata for _, _, metadata in runs],
            "catalog_version": catalog["version"], "catalog_scopes": [s["metadata"] for s in scopes],
            "dataset_fingerprint": fingerprint(cases), "dataset_versions": sorted({c["dataset_version"] for c in cases}),
            "selected_count": len(cases), "unreviewed_excluded": sum(not c["reviewed"] for c in all_cases),
            "progress": 0, "total": len(cases)*len(runs), "results": {}, "calibrations": calibrations,
            "group_summaries": repeated_summaries([], list(calibrations), options.repetitions),
            "cancel_requested": False, "stop_reason": None, "accounting": ExecutionAccounting().model_dump(),
            "scale_calibration": {"source": options.scale_calibration_source, "sample_count": len(fit_cases),
                                  "dataset_fingerprint": data_fingerprint(fit_cases), "max_oos_false_accept_rate": options.scale_max_oos_false_accept_rate} if scale_fit else None,
            "latency_protocol": "sequential-warm-index-v2", "source_counts": dict(__import__('collections').Counter(c['source'] for c in cases))})
        self.evaluation_pool.submit(self.run_evaluation, workspace, job["id"], cases, runs, calibrations, fit_cases)
        return job

    def run_evaluation(self, workspace, job_id, cases, runs, calibrations, fit_cases):
        job = self.store.claim_evaluation(workspace, job_id)
        if job is None:
            return
        controller = EvaluationController(
            ExecutionLimits.model_validate(job["options"].get("execution_limits", {})),
            cancel_requested=lambda: self.store.job(workspace, job_id).get("cancel_requested", False),
            on_checkpoint=lambda accounting: self.store.checkpoint_evaluation(workspace, job_id, {"accounting": accounting}),
        )
        with activate_execution(controller):
            self._execute_evaluation(workspace, job_id, cases, runs, calibrations, fit_cases)

    def _execute_evaluation(self, workspace, job_id, cases, runs, calibrations, fit_cases):
        job = self.store.job(workspace, job_id)
        results: dict[str, EvaluationResult] = {}
        progress, index_errors, fitted, fit_errors = 0, {}, {}, {}
        baselines: dict[tuple[str, int], tuple[int, EvaluationMetrics]] = {}
        pinned_retrievers: dict[tuple[str, str, str], Retriever] = {}
        pinned_embeddings: dict[str, Embeddings] = {}
        pinned_rerankers: dict[str, Reranker] = {}

        def checkpoint(updates: EvaluationCheckpoint) -> None:
            updates["group_summaries"] = repeated_summaries(
                list(results.values()), list(calibrations), job["options"]["repetitions"])
            self.store.checkpoint_evaluation(workspace, job_id, updates)

        try:
            for variant, scope, metadata in runs:
                execution_checkpoint()
                method, run_id = variant.method, metadata["id"]
                group_id = metadata["group_id"]
                records = []
                result: EvaluationResult = {**metadata, "complete": False, "completed_count": 0, "selected_count": len(cases),
                          "records": records, "metrics": summarize(records, variant.settings.candidate_k),
                          "model": None, "calibration": calibrations.get(group_id), "calibration_build_ms": 0,
                          "reranker_prepare_ms": 0, "index_preparation": None, "index_build_ms": 0,
                          "index_cache_hit": False, "index_error": None, "preparation_error": None,
                          "scaling": {"baseline_intent_count": None, "accuracy_delta_pp": None, "p95_ratio": None}}
                results[run_id] = result
                checkpoint({"active_variant": run_id, "phase": "index", "results": results})
                started = time.perf_counter()
                model_key = embedding_key(variant.settings)
                runtime_key = embedding_runtime_key(variant.settings)
                cache_key = (workspace, scope["version"], runtime_key)
                retriever_cached = cache_key in pinned_retrievers
                if cache_key not in pinned_retrievers:
                    if runtime_key not in pinned_embeddings:
                        pinned_embeddings[runtime_key] = Embeddings(
                            variant.settings.model_copy(deep=True), transport=self.embeddings.transport)
                    pinned_retrievers[cache_key] = self._retriever_with_embeddings(
                        workspace, scope["version"], [Intent.model_validate(intent) for intent in scope["intents"]],
                        pinned_embeddings[runtime_key])
                retriever = pinned_retrievers[cache_key]
                execution_checkpoint()
                cache_hit = retriever_cached if method == "lexical" else False
                index_preparation = None
                preparation_key = (model_key, scope["version"])
                preparation_error = index_errors.get(preparation_key) if method != "lexical" else None
                if method != "lexical" and preparation_error is None:
                    try:
                        with execution_stage("index"):
                            index_preparation = retriever.prepare_index()
                        cache_hit = index_preparation.source in ("memory", "disk")
                    except ModelUnavailable as exc:
                        preparation_error = index_errors[preparation_key] = exc
                index_ms = round((time.perf_counter()-started)*1000, 2)
                reranker_ms = 0
                reranker = None
                if variant.retrieval and variant.retrieval.reranker_id and preparation_error is None:
                    reranker_key = _reranker_runtime_key(variant.settings)
                    if reranker_key not in pinned_rerankers:
                        pinned_rerankers[reranker_key] = Reranker(
                            variant.settings.model_copy(deep=True), transport=self.reranker.transport)
                    reranker = pinned_rerankers[reranker_key]
                    started = time.perf_counter()
                    try:
                        with execution_stage("index"):
                            reranker.prepare()
                    except ModelUnavailable as exc:
                        preparation_error = exc
                    reranker_ms = round((time.perf_counter()-started)*1000, 2)
                calibration_ms = 0
                if method == "e5" and fit_cases and preparation_error is None:
                    checkpoint({"phase": "calibration"})
                    started = time.perf_counter()
                    if preparation_key not in fitted and preparation_key not in fit_errors:
                        try:
                            with execution_stage("calibration"):
                                fitted[preparation_key] = self.calibrator.fit_snapshot(retriever, fit_cases, job["scale_calibration"]["source"], job["scale_calibration"]["max_oos_false_accept_rate"], variant.settings.candidate_k)
                        except (ModelUnavailable, ValueError) as exc:
                            fit_errors[preparation_key] = exc
                    preparation_error = fit_errors.get(preparation_key)
                    if preparation_key in fitted:
                        calibrations[group_id] = public_calibration(fitted[preparation_key])
                    calibration_ms = round((time.perf_counter()-started)*1000, 2)
                    checkpoint({"calibrations": calibrations, "calibration_fits": list(fitted.values())})
                result.update(calibration=calibrations.get(group_id), calibration_build_ms=calibration_ms,
                              reranker_prepare_ms=reranker_ms,
                              index_preparation=index_preparation.model_dump() if index_preparation else None,
                              index_build_ms=index_ms, index_cache_hit=cache_hit,
                              index_error=str(index_errors[preparation_key]) if method != "lexical" and preparation_key in index_errors else None,
                              preparation_error=str(preparation_error) if preparation_error else None)
                checkpoint({"phase": "cases", "results": results})
                for case in cases:
                    execution_checkpoint()
                    # The labels select the fixed evaluation cohort, never the per-query candidate ranking or LLM input.
                    state = {"active_intent": None, "slots": {}, "pending_slot": None, "pending_confirmation": False, "clarification_options": [], "messages": [], **copy.deepcopy(case.get("context", {}))}
                    with execution_stage("cases"):
                        output, _ = self.compute(case["question"], state, method, retriever, variant=variant, preparation_error=preparation_error, calibration=calibrations.get(group_id), reranker=reranker)
                    expected = case["expected_decision"]
                    correct = output["decision"] == expected and (expected not in ("route", "continue", "cancel") or output["intent_id"] == case["expected_intent_id"])
                    record = {"case_id": case["case_id"], "question": case["question"], "expected_decision": expected, "expected_intent_id": case["expected_intent_id"], "decision": output["decision"], "intent_id": output["intent_id"], "correct": correct, "candidate_hit": case["expected_intent_id"] in [c["intent_id"] for c in output["candidates"]], "total_ms": output["timings_ms"]["compute_total"], "timings_ms": output["timings_ms"], "usage": output["usage"], "reason_code": output["reason_code"], "message": output["message"], "diagnostics": output.get("diagnostics"), "rejection_score": output.get("rejection_score"), "error": output["message"] if output["decision"] == "error" else None,
                              "error_stage": output.get("error_stage"), "index_preparation": output["index_preparation"], "retrieval_trace": output["retrieval_trace"],
                              "candidates": output["candidates"], "retrieval_candidates": output["retrieval_candidates"]}
                    record["analysis"] = diagnose(record)
                    records.append(record)
                    progress += 1
                    result.update(completed_count=len(records), complete=len(records) == len(cases),
                                  metrics=summarize(records, variant.settings.candidate_k), model=output["model"])
                    checkpoint({"progress": progress, "results": results})
                    execution_checkpoint()
                metrics = summarize(records, variant.settings.candidate_k)
                baseline = baselines.setdefault((variant.id, metadata["repeat_index"]), (scope["metadata"]["intent_count"], metrics))
                accuracy, base_accuracy = metrics["routing_accuracy"], baseline[1]["routing_accuracy"]
                base_p95 = baseline[1]["latency_ms"]["p95"]
                result["scaling"] = {"baseline_intent_count": baseline[0],
                                     "accuracy_delta_pp": 100*(accuracy-base_accuracy) if accuracy is not None and base_accuracy is not None else None,
                                     "p95_ratio": metrics["latency_ms"]["p95"]/base_p95 if base_p95 and not metrics["errors"] and not baseline[1]["errors"] else None}
                checkpoint({"progress": progress, "results": results})
            self.store.finalize_evaluation(workspace, job_id, "completed")
        except EvaluationStopped as exc:
            checkpoint({"results": results, "progress": progress})
            self.store.finalize_evaluation(workspace, job_id, "stopped", stop_reason=exc.stop_reason)
        except Exception:
            checkpoint({"results": results, "progress": progress})
            self.store.finalize_evaluation(workspace, job_id, "failed", error="The evaluation could not complete. Check the model and data configuration.")
