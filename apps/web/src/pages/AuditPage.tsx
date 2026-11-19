import { useQuery } from "@tanstack/react-query";
import { Download, Search } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { api, buildQuery, errorMessage, fetchBlob } from "@/lib/api";
import { formatDateTime, humanize } from "@/lib/format";
import { useI18n } from "@/i18n";
import { Badge, Button, Card, Dialog, DialogContent, EmptyState, Input, PageHeader, Pagination, Select } from "@/components/ui";
import { DataTable, type Column } from "@/components/data-table";
import type { AuditRecord, Page } from "@/types/api";

export function AuditPage() {
  const { t } = useI18n();
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const [action, setAction] = useState("");
  const [entityType, setEntityType] = useState("");
  const [selected, setSelected] = useState<AuditRecord | null>(null);

  const params = { page, page_size: 30, search: search || undefined, action: action || undefined, entity_type: entityType || undefined };

  const list = useQuery({
    queryKey: ["audit", params],
    queryFn: () => api.get<Page<AuditRecord>>(`/audit${buildQuery(params)}`),
  });

  const actions = useQuery({
    queryKey: ["audit", "actions"],
    queryFn: () => api.get<{ action: string; count: number }[]>("/audit/actions"),
  });

  const exportCsv = async () => {
    try {
      const blob = await fetchBlob(`/audit/export${buildQuery({ action: action || undefined })}`);
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = "resolve-audit.csv";
      link.click();
      URL.revokeObjectURL(url);
    } catch (error) {
      toast.error(errorMessage(error));
    }
  };

  const columns: Column<AuditRecord>[] = [
    { key: "action", header: t("audit.action"), render: (row) => <span className="mono text-[11px] font-semibold">{row.action}</span> },
    {
      key: "summary",
      header: t("audit.summary"),
      render: (row) => <span className="line-clamp-2 max-w-[420px] text-[12px]">{row.summary}</span>,
    },
    { key: "actor", header: t("audit.actor"), render: (row) => <span className="text-[11.5px]">{row.actor_email ?? "system"}</span> },
    { key: "entity", header: t("audit.entity"), render: (row) => <Badge tone="neutral">{row.entity_type}{row.entity_id ? ` · ${row.entity_id.slice(0, 8)}` : ""}</Badge> },
    { key: "created", header: t("common.date"), render: (row) => <span className="text-[11px] text-[var(--muted)]">{formatDateTime(row.created_at)}</span> },
  ];

  return (
    <>
      <PageHeader
        title={t("audit.title")}
        subtitle={t("audit.subtitle")}
        actions={
          <Button size="sm" variant="secondary" onClick={exportCsv}>
            <Download className="h-3.5 w-3.5" />
            {t("audit.exportCsv")}
          </Button>
        }
      />
      <Card>
        <div className="toolbar">
          <div className="relative min-w-[220px] flex-1">
            <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-[var(--muted)]" />
            <Input className="pl-8" placeholder={t("common.search")} value={search} onChange={(event) => { setSearch(event.target.value); setPage(1); }} />
          </div>
          <Select value={action} onChange={(event) => { setAction(event.target.value); setPage(1); }} className="w-auto max-w-[240px]">
            <option value="">All actions</option>
            {(actions.data ?? []).map((item) => <option key={item.action} value={item.action}>{item.action} ({item.count})</option>)}
          </Select>
          <Select value={entityType} onChange={(event) => { setEntityType(event.target.value); setPage(1); }} className="w-auto">
            <option value="">All entities</option>
            {["case", "invoice", "vendor", "document", "resolution", "approval", "organization", "user", "exception"].map((value) => (
              <option key={value} value={value}>{humanize(value)}</option>
            ))}
          </Select>
        </div>
        <DataTable
          columns={columns}
          rows={list.data?.items}
          loading={list.isLoading}
          rowKey={(row) => row.id}
          onRowClick={(row) => setSelected(row)}
          empty={<EmptyState title="No audit records" body="Every consequential action is appended here and cannot be edited or deleted." />}
        />
        {list.data ? <Pagination page={list.data.meta.page} pages={list.data.meta.pages} total={list.data.meta.total} pageSize={list.data.meta.page_size} onPage={setPage} /> : null}
      </Card>

      <Dialog open={Boolean(selected)} onOpenChange={(open) => !open && setSelected(null)}>
        {selected ? (
          <DialogContent title={selected.action} description={`${selected.entity_type}${selected.entity_id ? ` · ${selected.entity_id}` : ""}`} wide>
            <div className="space-y-3">
              <p className="text-[12.5px]">{selected.summary}</p>
              <div className="grid grid-cols-2 gap-3 text-[11.5px]">
                <div><p className="eyebrow">{t("audit.actor")}</p><p>{selected.actor_email ?? "system"}</p></div>
                <div><p className="eyebrow">{t("common.date")}</p><p>{formatDateTime(selected.created_at)}</p></div>
                <div><p className="eyebrow">{t("audit.requestId")}</p><p className="mono text-[10px]">{selected.request_id ?? "—"}</p></div>
                <div><p className="eyebrow">{t("audit.ip")}</p><p className="mono text-[10px]">{selected.ip_address ?? "—"}</p></div>
              </div>
              {selected.before || selected.after ? (
                <div className="grid gap-3 md:grid-cols-2">
                  <div>
                    <p className="eyebrow mb-1">{t("audit.before")}</p>
                    <pre className="mono max-h-[240px] overflow-auto rounded border border-[var(--line)] bg-[var(--surface-2)] p-2.5 text-[10px]">{JSON.stringify(selected.before, null, 2)}</pre>
                  </div>
                  <div>
                    <p className="eyebrow mb-1">{t("audit.after")}</p>
                    <pre className="mono max-h-[240px] overflow-auto rounded border border-[var(--line)] bg-[var(--surface-2)] p-2.5 text-[10px]">{JSON.stringify(selected.after, null, 2)}</pre>
                  </div>
                </div>
              ) : null}
            </div>
          </DialogContent>
        ) : null}
      </Dialog>
    </>
  );
}
