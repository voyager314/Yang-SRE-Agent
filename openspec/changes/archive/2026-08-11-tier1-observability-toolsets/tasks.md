## 1. Shared Infrastructure

- [x] 1.1 Create `src/sre_agent/utils/time.py` with `parse_relative_time(value, now)` function extracted from prometheus.py
- [x] 1.2 Update `src/sre_agent/toolsets/prometheus.py` to import and use `parse_relative_time` from utils.time, remove internal `_parse_relative_time`
- [x] 1.3 Add `param_validators` support to `YAMLTool` in `src/sre_agent/core/tool.py`: parse from YAML definition, validate before invoke, implement `hostname` validator (allowlist `[a-zA-Z0-9.\-:]`)
- [x] 1.4 Update `ToolsetManager._parse_tools()` to pass `param_validators` field from YAML data to YAMLTool

## 2. Tracing Toolset

- [x] 2.1 Create `src/sre_agent/toolsets/tracing.py` with data classes: `Span` (trace_id, span_id, parent_span_id, service, operation, start_us, duration_us, status_code, attributes, events) and `TraceSummary` (trace_id, root_service, root_operation, duration_ms, span_count, error_count, start_time)
- [x] 2.2 Implement `TracingBackend` Protocol with `search_traces`, `get_trace`, `list_services` method signatures
- [x] 2.3 Implement `TempoBackend`: search_traces (params→TraceQL translation + raw_query passthrough), get_trace (OTLP JSON→Span list), list_services (/api/v2/search/tag/service.name/values)
- [x] 2.4 Implement `JaegerBackend`: search_traces (direct param mapping to /api/traces), get_trace (Jaeger format→Span list), list_services (/api/services)
- [x] 2.5 Implement shared formatting: `_ATTR_BLACKLIST_PREFIXES`, `_ATTR_BLACKLIST_KEYS`, `_filter_attrs`, `_format_span_attrs` (max 4 shown + folding)
- [x] 2.6 Implement `_build_span_tree` (parent_span_id→children map, DFS) and `_render_span_tree` (├─/└─ indentation, ⚠️ SLOW / ❌ ERROR annotation)
- [x] 2.7 Implement `_format_search_results` (table format with trace_id, service, operation, duration, spans, errors)
- [x] 2.8 Implement `TraceSearchTool`, `TraceGetTool`, `TraceServicesTool` tool classes
- [x] 2.9 Implement `create_tracing_toolset` factory: provider detection (_detect_provider), URL resolution (TEMPO_URL→JAEGER_URL→TRACING_URL), TracingToolset with compress() hook
- [x] 2.10 Write unit tests for: params→TraceQL translation, OTLP JSON parsing, Jaeger format parsing, span tree building, attribute blacklist filtering, compress logic

## 3. Alertmanager Toolset

- [x] 3.1 Create `src/sre_agent/toolsets/alertmanager.py` with `AlertmanagerListTool` (params: filter, silenced, inhibited) calling GET /api/v2/alerts
- [x] 3.2 Implement `AlertmanagerSilencesTool` calling GET /api/v2/silences, filtering active silences
- [x] 3.3 Implement alert formatting: group by severity (critical→warning→info), show alertname/namespace/pod/message core labels
- [x] 3.4 Implement silence formatting: show matchers, createdBy, endsAt, comment
- [x] 3.5 Implement `create_alertmanager_toolset` factory: URL resolution (config→ALERTMANAGER_URL env), AlertmanagerToolset with compress() (alertname dedup + count)
- [x] 3.6 Write unit tests for: alert grouping/formatting, silence formatting, compress logic

## 4. Network Diagnostics Toolset

- [x] 4.1 Create `src/sre_agent/toolsets/network.yaml` with dns_lookup (dig), port_check (bash /dev/tcp or nc), http_check (curl -w), traceroute tools, each with `param_validators: {host: hostname}` or `{domain: hostname}`
- [x] 4.2 Add per-tool CommandPrerequisite checks (which dig, which curl, which traceroute, which nc) in the YAML prerequisites section
- [x] 4.3 Write integration test verifying param_validators reject shell metacharacters

## 5. Registration and Configuration

- [x] 5.1 Update `src/sre_agent/toolsets/__init__.py`: import and register tracing and alertmanager toolsets in `get_builtin_toolsets`, load network.yaml alongside kubernetes.yaml
- [x] 5.2 Update `src/sre_agent/config.py`: document new toolset config keys (tracing, alertmanager, network) — no schema change needed since ToolsetConfig already allows extra fields
- [x] 5.3 Verify end-to-end: toolset manager loads all new toolsets, prerequisite checks run, disabled toolsets don't register tools
