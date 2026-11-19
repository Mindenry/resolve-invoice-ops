import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Building2, GitMerge, Search, ShieldAlert } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";

import { api, buildQuery, errorMessage } from "@/lib/api";
import { humanize } from "@/lib/format";
import { useI18n } from "@/i18n";
import { useAuth } from "@/providers/auth";
import {
  Badge,
  Button,
  Card,
  Dialog,
  DialogContent,
  EmptyState,
  Field,
  Input,
  PageHeader,
  Pagination,
  Select,
  StatusBadge,
} from "@/components/ui";
import { DataTable, type Column } from "@/components/data-table";
import type { Page, Vendor } from "@/types/api";

export function VendorsPage() {
  const { t } = useI18n();
  const { can } = useAuth();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("");
  const [createOpen, setCreateOpen] = useState(false);
  const [duplicatesOpen, setDuplicatesOpen] = useState(false);
  const [form, setForm] = useState({ vendor_number: "", legal_name: "", tax_id: "", currency: "USD", email: "", country: "TH" });

  const params = { page, page_size: 25, search: search || undefined, status: status || undefined, sort: "legal_name", order: "asc" };

  const list = useQuery({
    queryKey: ["vendors", params],
    queryFn: () => api.get<Page<Vendor>>(`/vendors${buildQuery(params)}`),
  });

  const duplicates = useQuery({
    queryKey: ["vendors", "duplicates"],
    queryFn: () => api.get<{ anchor: Vendor; candidates: { vendor_id: string; legal_name: string; vendor_number: string; score: number; reasons: string[] }[] }[]>("/vendors/duplicates"),
    enabled: duplicatesOpen,
  });

  const create = useMutation({
    mutationFn: () => api.post("/vendors", { ...form, tax_id: form.tax_id || null, email: form.email || null }),
    onSuccess: () => {
      setCreateOpen(false);
      setForm({ vendor_number: "", legal_name: "", tax_id: "", currency: "USD", email: "", country: "TH" });
      void queryClient.invalidateQueries({ queryKey: ["vendors"] });
      toast.success("Vendor created");
    },
    onError: (error) => toast.error(errorMessage(error)),
  });

  const merge = useMutation({
    mutationFn: ({ target, source }: { target: string; source: string }) =>
      api.post(`/vendors/${target}/merge`, { source_vendor_id: source, note: "Merged from duplicate review" }),
    onSuccess: () => {
      setDuplicatesOpen(false);
      void queryClient.invalidateQueries({ queryKey: ["vendors"] });
      toast.success("Vendors merged");
    },
    onError: (error) => toast.error(errorMessage(error)),
  });

  const columns: Column<Vendor>[] = [
    {
      key: "name",
      header: t("vendors.legalName"),
      render: (row) => (
        <div>
          <div className="flex items-center gap-1.5 font-semibold">
            <Building2 className="h-3.5 w-3.5 text-[var(--muted)]" />
            {row.legal_name}
            {row.is_demo ? <Badge tone="neutral">demo</Badge> : null}
          </div>
          <div className="mono text-[10.5px] text-[var(--muted)]">{row.vendor_number} · {row.normalized_name}</div>
        </div>
      ),
    },
    { key: "tax", header: t("vendors.taxId"), render: (row) => <span className="mono text-[11px]">{row.tax_id ?? "—"}</span> },
    { key: "currency", header: t("common.currency"), render: (row) => <span className="mono text-[11px]">{row.currency}</span> },
    { key: "invoices", header: t("vendors.invoices"), align: "right", render: (row) => <span className="num">{row.invoice_count}</span> },
    {
      key: "exceptions",
      header: t("vendors.exceptions"),
      align: "right",
      render: (row) =>
        row.open_exception_count ? <Badge tone="warning">{row.open_exception_count}</Badge> : <span className="text-[var(--muted)]">0</span>,
    },
    {
      key: "risk",
      header: t("vendors.riskFlags"),
      render: (row) =>
        row.risk_flags.length ? (
          <div className="flex flex-wrap gap-1">{row.risk_flags.slice(0, 2).map((flag) => <Badge key={flag} tone="warning">{humanize(flag)}</Badge>)}</div>
        ) : (
          <span className="text-[var(--muted)]">—</span>
        ),
    },
    { key: "status", header: t("common.status"), render: (row) => <StatusBadge status={row.status} /> },
  ];

  return (
    <>
      <PageHeader
        title={t("vendors.title")}
        subtitle={t("vendors.subtitle")}
        actions={
          <>
            <Button variant="secondary" size="sm" onClick={() => setDuplicatesOpen(true)}>
              <ShieldAlert className="h-3.5 w-3.5" />
              {t("vendors.duplicates")}
            </Button>
            {can("vendor:create") ? (
              <Button variant="primary" size="sm" onClick={() => setCreateOpen(true)}>
                {t("common.create")}
              </Button>
            ) : null}
          </>
        }
      />

      <Card>
        <div className="toolbar">
          <div className="relative min-w-[240px] flex-1">
            <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-[var(--muted)]" />
            <Input className="pl-8" placeholder={t("common.search")} value={search} onChange={(event) => { setSearch(event.target.value); setPage(1); }} />
          </div>
          <Select value={status} onChange={(event) => { setStatus(event.target.value); setPage(1); }} className="w-auto">
            <option value="">All statuses</option>
            {["ACTIVE", "INACTIVE", "BLOCKED"].map((value) => <option key={value} value={value}>{humanize(value)}</option>)}
          </Select>
        </div>
        <DataTable
          columns={columns}
          rows={list.data?.items}
          loading={list.isLoading}
          rowKey={(row) => row.id}
          onRowClick={(row) => navigate(`/vendors/${row.id}`)}
          empty={<EmptyState title="No vendors" body="Create a vendor or import vendors from your accounting system." />}
        />
        {list.data ? <Pagination page={list.data.meta.page} pages={list.data.meta.pages} total={list.data.meta.total} pageSize={list.data.meta.page_size} onPage={setPage} /> : null}
      </Card>

      <Dialog open={createOpen} onOpenChange={setCreateOpen}>
        <DialogContent title="Create vendor" description="Vendor numbers are unique within the organization.">
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label={t("vendors.number")}><Input value={form.vendor_number} onChange={(event) => setForm({ ...form, vendor_number: event.target.value })} /></Field>
            <Field label={t("vendors.legalName")}><Input value={form.legal_name} onChange={(event) => setForm({ ...form, legal_name: event.target.value })} /></Field>
            <Field label={t("vendors.taxId")}><Input value={form.tax_id} onChange={(event) => setForm({ ...form, tax_id: event.target.value })} /></Field>
            <Field label={t("common.currency")}><Input maxLength={3} value={form.currency} onChange={(event) => setForm({ ...form, currency: event.target.value.toUpperCase() })} /></Field>
            <Field label={t("common.email")}><Input type="email" value={form.email} onChange={(event) => setForm({ ...form, email: event.target.value })} /></Field>
            <Field label="Country"><Input maxLength={2} value={form.country} onChange={(event) => setForm({ ...form, country: event.target.value.toUpperCase() })} /></Field>
          </div>
          <div className="mt-4 flex justify-end gap-2">
            <Button variant="secondary" onClick={() => setCreateOpen(false)}>{t("common.cancel")}</Button>
            <Button variant="primary" loading={create.isPending} disabled={!form.vendor_number || !form.legal_name} onClick={() => create.mutate()}>{t("common.create")}</Button>
          </div>
        </DialogContent>
      </Dialog>

      <Dialog open={duplicatesOpen} onOpenChange={setDuplicatesOpen}>
        <DialogContent title={t("vendors.duplicates")} description={t("vendors.duplicateBody")} wide>
          <div className="space-y-3">
            {duplicates.isLoading ? <p className="text-[12px] text-[var(--muted)]">{t("common.loading")}</p> : null}
            {(duplicates.data ?? []).map((group) => (
              <div key={group.anchor.id} className="rounded-md border border-[var(--line)] p-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div>
                    <p className="text-[12.5px] font-semibold">{group.anchor.legal_name}</p>
                    <p className="mono text-[10.5px] text-[var(--muted)]">{group.anchor.vendor_number} · {group.anchor.tax_id ?? "no tax id"}</p>
                  </div>
                  <Badge tone="warning">{group.candidates.length} candidate(s)</Badge>
                </div>
                <div className="mt-2 space-y-1.5">
                  {group.candidates.map((candidate) => (
                    <div key={candidate.vendor_id} className="flex flex-wrap items-center justify-between gap-2 rounded border border-[var(--line)] px-2.5 py-2">
                      <div>
                        <p className="text-[12px]">{candidate.legal_name} <span className="mono text-[10px] text-[var(--muted)]">{candidate.vendor_number}</span></p>
                        <p className="text-[10.5px] text-[var(--muted)]">{candidate.reasons.join(" · ")} · score {candidate.score}</p>
                      </div>
                      {can("vendor:merge") ? (
                        <Button size="sm" variant="secondary" loading={merge.isPending} onClick={() => merge.mutate({ target: group.anchor.id, source: candidate.vendor_id })}>
                          <GitMerge className="h-3.5 w-3.5" />
                          {t("vendors.mergeInto")}
                        </Button>
                      ) : null}
                    </div>
                  ))}
                </div>
              </div>
            ))}
            {(duplicates.data ?? []).length === 0 && !duplicates.isLoading ? (
              <EmptyState title="No duplicate candidates" body="Deterministic tax ID and normalized name matching found no duplicates." />
            ) : null}
            <p className="text-[10.5px] text-[var(--muted)]">{t("vendors.mergeWarning")}</p>
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}
