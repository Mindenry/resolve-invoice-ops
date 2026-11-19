import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { api, buildQuery } from "@/lib/api";
import { formatDate, formatMoney, formatNumber, formatPercent } from "@/lib/format";
import { useI18n } from "@/i18n";
import { Card, CardBody, CardHeader, EmptyState, KpiCard, PageHeader, Skeleton } from "@/components/ui";
import type { AnalyticsOverview } from "@/types/api";

export function AnalyticsPage() {
  const { t } = useI18n();
  const [days, setDays] = useState(30);

  const overview = useQuery({
    queryKey: ["analytics", "overview", days],
    queryFn: () => api.get<AnalyticsOverview>(`/analytics/overview${buildQuery({ days })}`),
  });

  const resolution = useQuery({
    queryKey: ["analytics", "resolution", days],
    queryFn: () => api.get<{ bucket: string; average_hours: number; resolved: number }[]>(`/analytics/resolution-time${buildQuery({ days })}`),
  });

  const usage = useQuery({
    queryKey: ["analytics", "ai", days],
    queryFn: () => api.get<{ by_purpose: { purpose: string; runs: number; cost_usd: number; input_tokens: number; output_tokens: number }[]; by_model: { provider: string; model: string; runs: number; cost_usd: number }[] }>(`/analytics/ai-usage${buildQuery({ days })}`),
  });

  const data = overview.data;
  const kpis = data?.kpis ?? [];

  return (
    <>
      <PageHeader
        title={t("analytics.title")}
        subtitle={t("analytics.subtitle")}
        actions={
          <div className="flex rounded-md border border-[var(--line-strong)] bg-[var(--surface)] p-0.5">
            {[7, 30, 90, 180].map((value) => (
              <button
                key={value}
                onClick={() => setDays(value)}
                className={`rounded px-2.5 py-1 text-[11.5px] font-semibold ${days === value ? "bg-[var(--surface-3)] text-[var(--ink)]" : "text-[var(--muted)]"}`}
              >
                {value}d
              </button>
            ))}
          </div>
        }
      />

      <div className="mb-4 grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-5">
        {overview.isLoading
          ? Array.from({ length: 5 }).map((_, index) => <Skeleton key={index} className="h-[104px]" />)
          : kpis.filter((kpi) => ["average_resolution_hours", "detection_rate", "automation_success_rate", "ai_assisted_resolutions", "total_exceptions"].includes(kpi.key)).map((kpi) => (
              <KpiCard
                key={kpi.key}
                label={kpi.label}
                value={kpi.unit === "percent" ? formatPercent(kpi.value) : kpi.unit === "hours" ? kpi.value.toFixed(1) : formatNumber(kpi.value)}
                unit={kpi.unit === "hours" ? "h" : undefined}
                detail={kpi.detail}
              />
            ))}
      </div>

      <div className="grid gap-4 xl:grid-cols-2">
        <Card>
          <CardHeader title={t("analytics.resolutionTime")} description="Average hours from case creation to resolution" />
          <CardBody className="pt-3">
            {(resolution.data ?? []).length === 0 ? (
              <EmptyState title="No resolved cases" body="Resolution time appears after cases are resolved." />
            ) : (
              <div className="h-[260px]">
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={resolution.data} margin={{ top: 8, right: 12, left: -18, bottom: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" vertical={false} />
                    <XAxis dataKey="bucket" tickFormatter={(value: string) => formatDate(value, "dd MMM")} tickLine={false} axisLine={false} minTickGap={24} />
                    <YAxis tickLine={false} axisLine={false} width={38} />
                    <Tooltip labelFormatter={(value: string) => formatDate(value)} formatter={(value: number) => [`${value.toFixed(1)} h`, "Average"]} />
                    <Line type="monotone" dataKey="average_hours" stroke="var(--accent)" strokeWidth={2} dot={false} />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            )}
          </CardBody>
        </Card>

        <Card>
          <CardHeader title={t("analytics.exceptionMix")} description="Detected exception types in the selected range" />
          <CardBody className="space-y-2 pt-3">
            {(data?.exception_distribution ?? []).map((row) => {
              const max = Math.max(...(data?.exception_distribution ?? []).map((item) => item.count), 1);
              return (
                <div key={row.key}>
                  <div className="mb-1 flex items-center justify-between text-[11.5px]">
                    <span>{row.label}</span>
                    <span className="num font-semibold">{row.count}</span>
                  </div>
                  <div className="h-1.5 overflow-hidden rounded-full bg-[var(--surface-3)]">
                    <div className="h-full rounded-full bg-[var(--info)]" style={{ width: `${(row.count / max) * 100}%` }} />
                  </div>
                </div>
              );
            })}
            {(data?.exception_distribution ?? []).length === 0 ? <EmptyState title="No exceptions" /> : null}
          </CardBody>
        </Card>

        <Card>
          <CardHeader title={t("analytics.aiUsage")} description="Purpose-level token and cost consumption" />
          <CardBody className="pt-3">
            {(usage.data?.by_purpose ?? []).length === 0 ? (
              <EmptyState title="No AI usage" body="Usage is recorded for real provider calls only." />
            ) : (
              <>
                <div className="h-[200px]">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={usage.data?.by_purpose} margin={{ top: 8, right: 12, left: -18, bottom: 0 }}>
                      <CartesianGrid strokeDasharray="3 3" vertical={false} />
                      <XAxis dataKey="purpose" tickLine={false} axisLine={false} tick={{ fontSize: 10 }} />
                      <YAxis tickLine={false} axisLine={false} width={38} />
                      <Tooltip formatter={(value: number, name: string) => [name === "runs" ? value : `$${Number(value).toFixed(4)}`, name]} />
                      <Bar dataKey="runs" fill="var(--accent)" radius={[3, 3, 0, 0]} />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
                <div className="mt-3 space-y-1.5 border-t border-[var(--line)] pt-2 text-[11.5px]">
                  {(usage.data?.by_model ?? []).map((model) => (
                    <div key={`${model.provider}-${model.model}`} className="flex items-center justify-between">
                      <span className="mono">{model.provider} / {model.model}</span>
                      <span className="num">{model.runs} runs · {formatMoney(model.cost_usd, "USD")}</span>
                    </div>
                  ))}
                </div>
              </>
            )}
          </CardBody>
        </Card>

        <Card>
          <CardHeader title={t("analytics.automation")} description="Workflow execution outcomes and job failures" />
          <CardBody className="space-y-3 pt-3">
            <div className="flex flex-wrap gap-2">
              {(data?.processing.jobs_by_status ?? []).map((row) => (
                <span key={row.key} className="rounded border border-[var(--line)] px-2 py-1 text-[11px]">
                  {row.label}: <span className="num font-semibold">{row.count}</span>
                </span>
              ))}
            </div>
            <div className="rounded border border-[var(--line)] bg-[var(--surface-2)] p-3 text-[11.5px]">
              <div className="flex justify-between"><span className="text-[var(--muted)]">Automation success</span><span className="num font-semibold">{formatPercent(kpis.find((kpi) => kpi.key === "automation_success_rate")?.value ?? 0)}</span></div>
              <div className="mt-1 flex justify-between"><span className="text-[var(--muted)]">Failed jobs</span><span className="num font-semibold">{formatNumber(kpis.find((kpi) => kpi.key === "failed_jobs")?.value ?? 0)}</span></div>
              <div className="mt-1 flex justify-between"><span className="text-[var(--muted)]">Workflow executions</span><span className="num font-semibold">{formatNumber(data?.counts.workflow_executions ?? 0)}</span></div>
            </div>
          </CardBody>
        </Card>
      </div>
    </>
  );
}
