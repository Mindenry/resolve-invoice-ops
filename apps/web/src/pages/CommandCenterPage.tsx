import { useQuery } from "@tanstack/react-query";
import {
  AlertTriangle,
  ArrowUpRight,
  CheckCircle2,
  Clock3,
  Sparkles,
  TrendingUp,
} from "lucide-react";
import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { api, buildQuery } from "@/lib/api";
import { formatDate, formatMoney, formatNumber, formatPercent, humanize, timeAgo } from "@/lib/format";
import { cn } from "@/lib/utils";
import { useI18n } from "@/i18n";
import { useAuth } from "@/providers/auth";
import {
  Avatar,
  Badge,
  Button,
  Card,
  CardBody,
  CardHeader,
  EmptyState,
  ErrorState,
  KpiCard,
  PageHeader,
  Skeleton,
  StatusBadge,
} from "@/components/ui";
import type { AnalyticsOverview, CaseSummary, Page } from "@/types/api";

const RANGES = [7, 30, 90, 180];

function formatKpiValue(value: number, unit: string): { value: string; unit?: string } {
  if (unit === "percent") return { value: `${value.toFixed(1)}%` };
  if (unit === "hours") return { value: value.toFixed(1), unit: "h" };
  return { value: formatNumber(value) };
}

export function CommandCenterPage() {
  const { t } = useI18n();
  const navigate = useNavigate();
  const { can } = useAuth();
  const [days, setDays] = useState(30);

  const overview = useQuery({
    queryKey: ["analytics", "overview", days],
    queryFn: () => api.get<AnalyticsOverview>(`/analytics/overview${buildQuery({ days })}`),
    refetchInterval: 90_000,
  });

  const priorityQueue = useQuery({
    queryKey: ["cases", "priority-queue"],
    queryFn: () =>
      api.get<Page<CaseSummary>>(`/cases${buildQuery({ open_only: true, page_size: 7, sort: "last_activity_at" })}`),
  });

  if (overview.isError) {
    return (
      <Card>
        <ErrorState message={(overview.error as Error).message} onRetry={() => overview.refetch()} />
      </Card>
    );
  }

  const data = overview.data;
  const kpis = data?.kpis ?? [];
  const trend = (data?.exception_trend ?? []).map((point, index) => ({
    date: point.bucket,
    exceptions: point.value,
    cases: data?.case_trend[index]?.value ?? 0,
    resolved: data?.resolution_trend[index]?.value ?? 0,
  }));

  return (
    <>
      <PageHeader
        title={t("dashboard.title")}
        subtitle={t("dashboard.subtitle")}
        actions={
          <div className="flex items-center gap-2">
            <div className="flex rounded-md border border-[var(--line-strong)] bg-[var(--surface)] p-0.5">
              {RANGES.map((range) => (
                <button
                  key={range}
                  onClick={() => setDays(range)}
                  className={cn(
                    "rounded px-2.5 py-1 text-[11.5px] font-semibold transition-colors",
                    days === range
                      ? "bg-[var(--surface-3)] text-[var(--ink)]"
                      : "text-[var(--muted)] hover:text-[var(--ink)]",
                  )}
                >
                  {range}d
                </button>
              ))}
            </div>
            <Button variant="secondary" size="sm" onClick={() => overview.refetch()}>
              {t("common.refresh")}
            </Button>
          </div>
        }
      />

      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
        {overview.isLoading
          ? Array.from({ length: 6 }).map((_, index) => <Skeleton key={index} className="h-[104px]" />)
          : kpis.slice(0, 6).map((kpi) => {
              const formatted = formatKpiValue(kpi.value, kpi.unit);
              return (
                <KpiCard
                  key={kpi.key}
                  label={kpi.label}
                  value={formatted.value}
                  unit={formatted.unit}
                  delta={kpi.delta_percent}
                  detail={kpi.detail}
                />
              );
            })}
      </div>

      <div className="mt-3 grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-5">
        {overview.isLoading
          ? Array.from({ length: 5 }).map((_, index) => <Skeleton key={index} className="h-[104px]" />)
          : kpis.slice(6).map((kpi) => {
              const formatted = formatKpiValue(kpi.value, kpi.unit);
              return (
                <KpiCard
                  key={kpi.key}
                  label={kpi.label}
                  value={formatted.value}
                  unit={formatted.unit}
                  detail={kpi.detail}
                />
              );
            })}
      </div>

      <div className="mt-4 grid gap-4 xl:grid-cols-[1.55fr_1fr]">
        <Card>
          <CardHeader
            title={t("dashboard.exceptionTrend")}
            description="Detected exceptions, new cases and resolutions over time"
            actions={
              <div className="flex items-center gap-3 text-[11px] text-[var(--muted)]">
                <span className="flex items-center gap-1.5"><span className="dot bg-[var(--accent)]" />Exceptions</span>
                <span className="flex items-center gap-1.5"><span className="dot bg-[var(--info)]" />Cases</span>
                <span className="flex items-center gap-1.5"><span className="dot bg-[var(--warning)]" />Resolved</span>
              </div>
            }
          />
          <CardBody className="pt-3">
            {overview.isLoading ? (
              <Skeleton className="h-[260px]" />
            ) : (
              <div className="h-[260px] w-full">
                <ResponsiveContainer width="100%" height="100%">
                  <AreaChart data={trend} margin={{ top: 8, right: 8, left: -18, bottom: 0 }}>
                    <defs>
                      <linearGradient id="exceptionFill" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="0%" stopColor="var(--accent)" stopOpacity={0.24} />
                        <stop offset="100%" stopColor="var(--accent)" stopOpacity={0.01} />
                      </linearGradient>
                    </defs>
                    <CartesianGrid strokeDasharray="3 3" vertical={false} />
                    <XAxis
                      dataKey="date"
                      tickFormatter={(value: string) => formatDate(value, "dd MMM")}
                      tickLine={false}
                      axisLine={false}
                      minTickGap={28}
                    />
                    <YAxis allowDecimals={false} tickLine={false} axisLine={false} width={38} />
                    <Tooltip
                      labelFormatter={(value: string) => formatDate(value, "dd MMM yyyy")}
                      formatter={(value: number, name: string) => [value, humanize(name)]}
                    />
                    <Area
                      type="monotone"
                      dataKey="exceptions"
                      stroke="var(--accent)"
                      strokeWidth={1.8}
                      fill="url(#exceptionFill)"
                    />
                    <Area
                      type="monotone"
                      dataKey="cases"
                      stroke="var(--info)"
                      strokeWidth={1.4}
                      fill="transparent"
                      strokeDasharray="4 3"
                    />
                    <Area
                      type="monotone"
                      dataKey="resolved"
                      stroke="var(--warning)"
                      strokeWidth={1.4}
                      fill="transparent"
                    />
                  </AreaChart>
                </ResponsiveContainer>
              </div>
            )}
          </CardBody>
        </Card>

        <div className="space-y-4">
          <Card>
            <CardHeader title={t("dashboard.sla")} description="Active cases against their SLA" />
            <CardBody className="grid grid-cols-2 gap-3 pt-3">
              <div className="rounded-md border border-[var(--line)] bg-[var(--surface-2)] px-3 py-3">
                <div className="flex items-center gap-1.5 text-[11px] text-[var(--muted)]">
                  <AlertTriangle className="h-3.5 w-3.5 text-[var(--danger)]" />
                  {t("dashboard.slaBreached")}
                </div>
                <p className="num mt-1 text-[22px] font-semibold">{formatNumber(data?.sla.breached ?? 0)}</p>
              </div>
              <div className="rounded-md border border-[var(--line)] bg-[var(--surface-2)] px-3 py-3">
                <div className="flex items-center gap-1.5 text-[11px] text-[var(--muted)]">
                  <Clock3 className="h-3.5 w-3.5 text-[var(--warning)]" />
                  {t("dashboard.slaDueSoon")}
                </div>
                <p className="num mt-1 text-[22px] font-semibold">{formatNumber(data?.sla.due_within_24h ?? 0)}</p>
              </div>
              <div className="col-span-2 flex items-center justify-between rounded-md border border-[var(--line)] bg-[var(--surface-2)] px-3 py-2.5">
                <span className="flex items-center gap-1.5 text-[11.5px] text-[var(--muted)]">
                  <TrendingUp className="h-3.5 w-3.5 text-[var(--success)]" />
                  {t("dashboard.avgResolution")}
                </span>
                <span className="num text-[14px] font-semibold">
                  {(data?.sla.average_resolution_hours ?? 0).toFixed(1)} h
                </span>
              </div>
            </CardBody>
          </Card>

          <Card>
            <CardHeader
              title={t("dashboard.aiUsage")}
              description="Measured usage from the AI layer"
              actions={
                (data?.processing.ai_runs ?? 0) === 0 ? <Badge tone="neutral">No runs</Badge> : null
              }
            />
            <CardBody className="space-y-2 pt-3 text-[12px]">
              <div className="flex items-center justify-between">
                <span className="text-[var(--muted)]">Runs</span>
                <span className="num font-semibold">{formatNumber(data?.processing.ai_runs ?? 0)}</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-[var(--muted)]">Tokens</span>
                <span className="num font-semibold">{formatNumber(data?.processing.ai_tokens ?? 0)}</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-[var(--muted)]">Estimated cost</span>
                <span className="num font-semibold">{formatMoney(data?.processing.ai_cost_usd ?? 0, "USD")}</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-[var(--muted)]">Avg. latency</span>
                <span className="num font-semibold">
                  {formatNumber(data?.processing.ai_average_latency_ms ?? 0)} ms
                </span>
              </div>
              <Link
                to="/evaluation"
                className="mt-1 inline-flex items-center gap-1 text-[11.5px] font-semibold text-[var(--accent)]"
              >
                <Sparkles className="h-3.5 w-3.5" />
                Open evaluation lab
                <ArrowUpRight className="h-3 w-3" />
              </Link>
            </CardBody>
          </Card>
        </div>
      </div>

      <div className="mt-4 grid gap-4 xl:grid-cols-[1.2fr_1fr]">
        <Card>
          <CardHeader
            title={t("dashboard.priorityQueue")}
            actions={
              can("case:read") ? (
                <Button variant="ghost" size="sm" onClick={() => navigate("/cases?open_only=true")}>
                  {t("dashboard.viewQueue")}
                </Button>
              ) : null
            }
          />
          <div className="overflow-x-auto">
            {priorityQueue.isLoading ? (
              <div className="space-y-2 p-4">
                {Array.from({ length: 5 }).map((_, index) => (
                  <Skeleton key={index} className="h-9" />
                ))}
              </div>
            ) : (priorityQueue.data?.items ?? []).length === 0 ? (
              <EmptyState title={t("common.emptyTitle")} body={t("common.emptyBody")} />
            ) : (
              <table className="table">
                <thead>
                  <tr>
                    <th>Case</th>
                    <th>{t("common.priority")}</th>
                    <th>{t("common.assigned")}</th>
                    <th>{t("common.due")}</th>
                  </tr>
                </thead>
                <tbody>
                  {priorityQueue.data?.items.map((item) => (
                    <tr
                      key={item.id}
                      data-clickable="true"
                      onClick={() => navigate(`/cases/${item.id}`)}
                    >
                      <td>
                        <div className="font-semibold">{item.case_number}</div>
                        <div className="line-clamp-1 text-[11.5px] text-[var(--muted)]">{item.title}</div>
                      </td>
                      <td>
                        <StatusBadge status={item.priority} />
                      </td>
                      <td>
                        {item.assigned_user ? (
                          <span className="flex items-center gap-1.5 text-[12px]">
                            <Avatar
                              name={item.assigned_user.full_name}
                              color={item.assigned_user.avatar_color}
                              size={22}
                            />
                            <span className="hidden xl:inline">{item.assigned_user.full_name}</span>
                          </span>
                        ) : (
                          <span className="text-[12px] text-[var(--muted)]">{t("common.unassigned")}</span>
                        )}
                      </td>
                      <td>
                        <span className={cn("text-[12px]", item.sla_breached && "font-semibold text-[var(--danger)]")}>
                          {item.due_at ? timeAgo(item.due_at) : "—"}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </Card>

        <div className="space-y-4">
          <Card>
            <CardHeader title={t("dashboard.distribution")} description="Share of detected exception types" />
            <CardBody className="space-y-2.5 pt-3">
              {(data?.exception_distribution ?? []).slice(0, 6).map((row) => {
                const max = Math.max(...(data?.exception_distribution ?? []).map((item) => item.count), 1);
                return (
                  <div key={row.key}>
                    <div className="mb-1 flex items-center justify-between text-[11.5px]">
                      <span className="text-[var(--ink-soft)]">{row.label}</span>
                      <span className="num font-semibold">{row.count}</span>
                    </div>
                    <div className="h-1.5 overflow-hidden rounded-full bg-[var(--surface-3)]">
                      <div
                        className="h-full rounded-full bg-[var(--accent)]"
                        style={{ width: `${(row.count / max) * 100}%` }}
                      />
                    </div>
                  </div>
                );
              })}
              {(data?.exception_distribution ?? []).length === 0 ? (
                <p className="py-6 text-center text-[12px] text-[var(--muted)]">{t("dashboard.noExceptions")}</p>
              ) : null}
            </CardBody>
          </Card>

          <Card>
            <CardHeader title={t("dashboard.workload")} description="Active cases per team member" />
            <CardBody className="space-y-2 pt-3">
              {(data?.workload ?? []).slice(0, 5).map((row) => (
                <div key={row.name} className="flex items-center justify-between text-[12px]">
                  <span className="flex items-center gap-1.5">
                    <Avatar name={row.name} size={22} />
                    {row.name}
                  </span>
                  <span className="num font-semibold">{row.open_cases}</span>
                </div>
              ))}
              {(data?.workload ?? []).length === 0 ? (
                <p className="py-4 text-center text-[12px] text-[var(--muted)]">{t("common.noData")}</p>
              ) : null}
            </CardBody>
          </Card>
        </div>
      </div>

      <div className="mt-4 grid gap-4 xl:grid-cols-[1.4fr_1fr]">
        <Card>
          <CardHeader title={t("dashboard.recentActivity")} description="Latest case activity" />
          <CardBody className="pt-2">
            {(data?.recent_activity ?? []).length === 0 ? (
              <p className="py-6 text-center text-[12px] text-[var(--muted)]">{t("common.noData")}</p>
            ) : (
              <div className="divide-y divide-[var(--line)]">
                {data?.recent_activity.map((item) => (
                  <button
                    key={item.id}
                    className="flex w-full items-start gap-2 py-2.5 text-left hover:bg-[var(--surface-2)]"
                    onClick={() => navigate(`/cases/${item.case_id}`)}
                  >
                    <span className="mt-1 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-[var(--accent-soft)] text-[var(--accent)]">
                      <CheckCircle2 className="h-3 w-3" />
                    </span>
                    <div className="min-w-0 flex-1">
                      <p className="text-[12.5px]">
                        <span className="font-semibold">{item.case_number}</span>{" "}
                        <span className="text-[var(--muted)]">·</span> {item.summary}
                      </p>
                      <p className="text-[10.5px] text-[var(--muted)]">
                        {item.actor_name ?? "System"} · {timeAgo(item.created_at)}
                      </p>
                    </div>
                  </button>
                ))}
              </div>
            )}
          </CardBody>
        </Card>

        <Card>
          <CardHeader title={t("dashboard.processing")} description="Document and job pipeline" />
          <CardBody className="space-y-3 pt-3">
            <div>
              <p className="eyebrow mb-1.5">Documents</p>
              <div className="flex flex-wrap gap-1.5">
                {(data?.processing.documents_by_status ?? []).map((row) => (
                  <Badge key={row.key} tone="neutral">
                    {row.label}: <span className="num">{row.count}</span>
                  </Badge>
                ))}
                {(data?.processing.documents_by_status ?? []).length === 0 ? (
                  <span className="text-[11.5px] text-[var(--muted)]">—</span>
                ) : null}
              </div>
            </div>
            <div>
              <p className="eyebrow mb-1.5">Background jobs</p>
              <div className="flex flex-wrap gap-1.5">
                {(data?.processing.jobs_by_status ?? []).map((row) => (
                  <Badge key={row.key} tone={row.key === "FAILED" ? "danger" : "neutral"}>
                    {row.label}: <span className="num">{row.count}</span>
                  </Badge>
                ))}
                {(data?.processing.jobs_by_status ?? []).length === 0 ? (
                  <span className="text-[11.5px] text-[var(--muted)]">—</span>
                ) : null}
              </div>
            </div>
            <div className="rounded-md border border-[var(--line)] bg-[var(--surface-2)] px-3 py-2 text-[11.5px] text-[var(--muted)]">
              Detection rate <span className="num font-semibold text-[var(--ink)]">
                {formatPercent(kpis.find((item) => item.key === "detection_rate")?.value ?? 0)}
              </span>{" "}
              · Automation success{" "}
              <span className="num font-semibold text-[var(--ink)]">
                {formatPercent(kpis.find((item) => item.key === "automation_success_rate")?.value ?? 0)}
              </span>
            </div>
          </CardBody>
        </Card>
      </div>
    </>
  );
}
