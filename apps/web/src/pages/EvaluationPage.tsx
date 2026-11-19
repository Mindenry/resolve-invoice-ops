import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BarChart3, FlaskConical, Play, TriangleAlert } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";

import { api, errorMessage } from "@/lib/api";
import { formatNumber, humanize, timeAgo } from "@/lib/format";
import { cn } from "@/lib/utils";
import { useI18n } from "@/i18n";
import { useAuth } from "@/providers/auth";
import {
  Badge,
  Button,
  Card,
  CardBody,
  CardHeader,
  Dialog,
  DialogContent,
  EmptyState,
  Field,
  Input,
  PageHeader,
  Select,
  Skeleton,
  StatusBadge,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "@/components/ui";
import type { EvaluationDataset, EvaluationRun, Page } from "@/types/api";

const METRIC_LABELS: Record<string, string> = {
  exception_classification_accuracy: "Classification accuracy",
  precision: "Precision",
  recall: "Recall",
  f1: "F1",
  root_cause_accuracy: "Root cause accuracy",
  evidence_accuracy: "Evidence accuracy",
  citation_accuracy: "Citation accuracy",
  recommendation_acceptance: "Recommendation acceptance",
  groundedness: "Groundedness",
  latency_ms_avg: "Average latency (ms)",
  tokens_total: "Tokens",
  cost_usd_total: "Cost (USD)",
  samples: "Samples",
  errors: "Errors",
};

function metricValue(key: string, value: unknown): string {
  if (typeof value !== "number") return String(value ?? "—");
  if (key === "tokens_total") return formatNumber(value);
  if (key === "cost_usd_total") return `$${value.toFixed(4)}`;
  if (key === "latency_ms_avg") return `${value.toFixed(0)} ms`;
  if (["samples", "errors"].includes(key)) return String(value);
  return `${(value * 100).toFixed(1)}%`;
}

export function EvaluationPage() {
  const { t } = useI18n();
  const { can } = useAuth();
  const queryClient = useQueryClient();
  const [runOpen, setRunOpen] = useState(false);
  const [datasetId, setDatasetId] = useState("");
  const [runName, setRunName] = useState("");
  const [selected, setSelected] = useState<string | null>(null);

  const datasets = useQuery({
    queryKey: ["evaluation", "datasets"],
    queryFn: () => api.get<EvaluationDataset[]>("/evaluation/datasets"),
  });

  const runs = useQuery({
    queryKey: ["evaluation", "runs"],
    queryFn: () => api.get<Page<EvaluationRun>>("/evaluation/runs?page_size=50"),
    refetchInterval: (query) => (query.state.data?.items.some((item) => ["QUEUED", "RUNNING"].includes(item.status)) ? 3_000 : false),
  });

  const runDetail = useQuery({
    queryKey: ["evaluation", "run", selected],
    queryFn: () => api.get<EvaluationRun>(`/evaluation/runs/${selected}`),
    enabled: Boolean(selected),
    refetchInterval: (query) =>
      ["QUEUED", "RUNNING"].includes(query.state.data?.status ?? "") ? 3000 : false,
  });

  const createRun = useMutation({
    mutationFn: () =>
      api.post<EvaluationRun>("/evaluation/runs", {
        dataset_id: datasetId,
        name: runName || `Run ${new Date().toISOString().slice(0, 16)}`,
      }),
    onSuccess: (run) => {
      setRunOpen(false);
      setRunName("");
      setSelected(run.id);
      void queryClient.invalidateQueries({ queryKey: ["evaluation"] });
      toast.success("Evaluation run queued");
    },
    onError: (error) => toast.error(errorMessage(error)),
  });

  useEffect(() => {
    if (!selected && runs.data?.items.length) {
      setSelected(runs.data.items[0].id);
    }
  }, [runs.data, selected]);

  const active = runDetail.data;
  const metrics = useMemo(() => {
    if (!active) return [];
    return Object.entries(active.metrics).filter(([key]) => key in METRIC_LABELS);
  }, [active]);

  return (
    <>
      <PageHeader
        title={t("evaluation.title")}
        subtitle={t("evaluation.subtitle")}
        actions={
          can("evaluation:run") ? (
            <Button
              size="sm"
              variant="primary"
              onClick={() => {
                setDatasetId(datasets.data?.[0]?.id ?? "");
                setRunOpen(true);
              }}
            >
              <Play className="h-3.5 w-3.5" />
              {t("evaluation.newRun")}
            </Button>
          ) : null
        }
      />

      <div className="grid gap-4 xl:grid-cols-[300px_1fr]">
        <div className="space-y-4">
          <Card>
            <CardHeader title={t("evaluation.datasets")} description="Labelled synthetic cases" />
            <CardBody className="space-y-2 pt-3">
              {(datasets.data ?? []).map((dataset) => (
                <div key={dataset.id} className="rounded border border-[var(--line)] px-2.5 py-2">
                  <div className="flex items-center gap-1.5">
                    <FlaskConical className="h-3.5 w-3.5 text-[var(--muted)]" />
                    <span className="text-[12px] font-semibold">{dataset.name}</span>
                  </div>
                  <p className="mt-0.5 text-[10.5px] text-[var(--muted)]">
                    {dataset.sample_count} samples · v{dataset.version} · {dataset.is_synthetic ? t("evaluation.synthetic") : "production data"}
                  </p>
                </div>
              ))}
              {(datasets.data ?? []).length === 0 ? <p className="text-[12px] text-[var(--muted)]">No datasets. Seed the demo workspace to load the synthetic dataset.</p> : null}
            </CardBody>
          </Card>

          <Card>
            <CardHeader title={t("evaluation.runs")} />
            <CardBody className="space-y-2 pt-3">
              {runs.isLoading ? <Skeleton className="h-20" /> : null}
              {(runs.data?.items ?? []).map((run) => (
                <button
                  key={run.id}
                  className={cn("w-full rounded border px-2.5 py-2 text-left text-[12px] hover:bg-[var(--surface-2)]", selected === run.id ? "border-[var(--accent)]" : "border-[var(--line)]")}
                  onClick={() => setSelected(run.id)}
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="truncate font-semibold">{run.name}</span>
                    <StatusBadge status={run.status} />
                  </div>
                  <p className="mt-0.5 text-[10.5px] text-[var(--muted)]">
                    {run.provider} · {run.model ?? "—"} · {timeAgo(run.created_at)}
                  </p>
                  {typeof run.metrics?.f1 === "number" ? (
                    <span className="num mt-1 inline-block rounded bg-[var(--accent-soft)] px-1 text-[10px] font-semibold text-[var(--accent-strong)]">
                      F1 {(run.metrics.f1 * 100).toFixed(1)}%
                    </span>
                  ) : null}
                </button>
              ))}
              {(runs.data?.items ?? []).length === 0 && !runs.isLoading ? (
                <EmptyState icon={<BarChart3 className="h-5 w-5" />} title={t("evaluation.noRuns")} />
              ) : null}
            </CardBody>
          </Card>
        </div>

        <Card>
          {!selected ? (
            <EmptyState icon={<BarChart3 className="h-5 w-5" />} title={t("evaluation.metrics")} body="Select a run to inspect measured precision, recall, grounding and per-sample results." />
          ) : !active ? (
            <div className="p-4"><Skeleton className="h-56" /></div>
          ) : (
            <>
              <CardHeader
                title={active.name}
                description={`${active.dataset_name ?? ""} · prompt ${active.prompt_version} · ${active.sample_completed}/${active.sample_total} samples`}
                actions={<StatusBadge status={active.status} />}
              />
              <CardBody className="space-y-4 pt-3">
                {active.metrics.deterministic_stub ? (
                  <div className="flex items-start gap-2 rounded border border-[var(--warning)]/30 bg-[var(--warning-soft)] px-3 py-2 text-[11.5px] text-[var(--warning)]">
                    <TriangleAlert className="mt-0.5 h-4 w-4 shrink-0" />
                    {t("evaluation.stubWarning")}
                  </div>
                ) : null}
                {active.error ? <p className="rounded bg-[var(--danger-soft)] px-3 py-2 text-[11.5px] text-[var(--danger)]">{active.error}</p> : null}

                <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 xl:grid-cols-4">
                  {metrics.map(([key, value]) => (
                    <div key={key} className="rounded-md border border-[var(--line)] bg-[var(--surface-2)] px-3 py-2">
                      <p className="text-[10px] uppercase tracking-wide text-[var(--muted)]">{METRIC_LABELS[key] ?? humanize(key)}</p>
                      <p className="num mt-0.5 text-[16px] font-semibold">{metricValue(key, value)}</p>
                    </div>
                  ))}
                </div>

                <Tabs defaultValue="results">
                  <TabsList>
                    <TabsTrigger value="results">Per-sample results</TabsTrigger>
                    <TabsTrigger value="raw">Metrics JSON</TabsTrigger>
                  </TabsList>
                  <TabsContent value="results">
                    <div className="overflow-x-auto">
                      <table className="table">
                        <thead><tr><th>Sample</th><th>F1</th><th>Root cause</th><th>Evidence</th><th>Citation</th><th>Latency</th><th>Status</th></tr></thead>
                        <tbody>
                          {(active.results ?? []).map((result) => (
                            <tr key={result.id}>
                              <td className="mono text-[11px]">{result.sample_key}</td>
                              <td className="num">{typeof result.scores.f1 === "number" ? `${(result.scores.f1 * 100).toFixed(1)}%` : "—"}</td>
                              <td>{result.scores.root_cause_correct ? <Badge tone="success">yes</Badge> : <Badge tone="neutral">no</Badge>}</td>
                              <td className="num">{typeof result.scores.evidence_accuracy === "number" ? `${(result.scores.evidence_accuracy * 100).toFixed(0)}%` : "—"}</td>
                              <td className="num">{typeof result.scores.citation_accuracy === "number" ? `${(result.scores.citation_accuracy * 100).toFixed(0)}%` : "—"}</td>
                              <td className="num">{result.latency_ms ?? "—"} ms</td>
                              <td>{result.error ? <Badge tone="danger">{result.error.slice(0, 40)}</Badge> : <Badge tone="success">ok</Badge>}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </TabsContent>
                  <TabsContent value="raw">
                    <pre className="mono max-h-[360px] overflow-auto rounded border border-[var(--line)] bg-[var(--surface-2)] p-3 text-[10.5px]">{JSON.stringify(active.metrics, null, 2)}</pre>
                  </TabsContent>
                </Tabs>
              </CardBody>
            </>
          )}
        </Card>
      </div>

      <Dialog open={runOpen} onOpenChange={setRunOpen}>
        <DialogContent title={t("evaluation.newRun")} description="Runs call the configured provider. Metrics are computed only from actual responses.">
          <div className="space-y-3">
            <Field label={t("evaluation.datasets")}>
              <Select value={datasetId} onChange={(event) => setDatasetId(event.target.value)}>
                {(datasets.data ?? []).map((dataset) => <option key={dataset.id} value={dataset.id}>{dataset.name} ({dataset.sample_count})</option>)}
              </Select>
            </Field>
            <Field label={t("common.name")}><Input value={runName} onChange={(event) => setRunName(event.target.value)} placeholder="Baseline investigation prompt" /></Field>
            <div className="flex justify-end gap-2">
              <Button variant="secondary" onClick={() => setRunOpen(false)}>{t("common.cancel")}</Button>
              <Button variant="primary" loading={createRun.isPending} disabled={!datasetId} onClick={() => createRun.mutate()}>{t("common.create")}</Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}
