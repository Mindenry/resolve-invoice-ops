import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, ArrowUpRight, CheckCircle2, Link2, ShieldCheck, TriangleAlert } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { toast } from "sonner";

import { api, errorMessage } from "@/lib/api";
import { formatDate, formatDateTime, formatMoney, humanize } from "@/lib/format";
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
  ErrorState,
  PageHeader,
  Skeleton,
  StatusBadge,
} from "@/components/ui";
import type { InvoiceDetail } from "@/types/api";

export function InvoiceDetailPage() {
  const { id = "" } = useParams();
  const { t } = useI18n();
  const { can } = useAuth();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [matchOpen, setMatchOpen] = useState(false);

  const detail = useQuery({
    queryKey: ["invoice", id],
    queryFn: () => api.get<InvoiceDetail>(`/invoices/${id}`),
  });

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: ["invoice", id] });
    void queryClient.invalidateQueries({ queryKey: ["invoices"] });
    void queryClient.invalidateQueries({ queryKey: ["cases"] });
  };

  const validate = useMutation({
    mutationFn: () => api.post(`/invoices/${id}/validate`, {}),
    onSuccess: () => { invalidate(); toast.success("Validation complete"); },
    onError: (error) => toast.error(errorMessage(error)),
  });

  const match = useMutation({
    mutationFn: (purchaseOrderId: string | null) => api.post(`/invoices/${id}/match`, { purchase_order_id: purchaseOrderId, auto_match: !purchaseOrderId }),
    onSuccess: () => { setMatchOpen(false); invalidate(); toast.success("Purchase order matched"); },
    onError: (error) => toast.error(errorMessage(error)),
  });

  const approve = useMutation({
    mutationFn: () => api.post(`/invoices/${id}/approve`, {}),
    onSuccess: () => { invalidate(); toast.success("Invoice approved"); },
    onError: (error) => toast.error(errorMessage(error)),
  });

  const transition = useMutation({
    mutationFn: (status: string) => api.post(`/invoices/${id}/transition`, { status }),
    onSuccess: () => { invalidate(); toast.success("Invoice updated"); },
    onError: (error) => toast.error(errorMessage(error)),
  });

  const invoice = detail.data;

  if (detail.isError) {
    return <Card><ErrorState message={(detail.error as Error).message} onRetry={() => detail.refetch()} /></Card>;
  }

  return (
    <>
      <button className="mb-3 inline-flex items-center gap-1.5 text-[12px] font-semibold text-[var(--muted)] hover:text-[var(--ink)]" onClick={() => navigate("/invoices")}>
        <ArrowLeft className="h-3.5 w-3.5" />
        {t("invoices.title")}
      </button>

      {detail.isLoading || !invoice ? (
        <Skeleton className="h-64" />
      ) : (
        <>
          <PageHeader
            title={invoice.invoice_number}
            subtitle={`${invoice.vendor?.legal_name ?? invoice.vendor_name_raw ?? "No vendor"} · ${formatDate(invoice.invoice_date)}`}
            actions={
              <>
                {can("invoice:update") ? (
                  <Button size="sm" variant="secondary" loading={validate.isPending} onClick={() => validate.mutate()}>
                    <ShieldCheck className="h-3.5 w-3.5" />
                    {t("invoices.validate")}
                  </Button>
                ) : null}
                {can("invoice:update") ? (
                  <Button size="sm" variant="secondary" onClick={() => setMatchOpen(true)}>
                    <Link2 className="h-3.5 w-3.5" />
                    {t("invoices.matchPo")}
                  </Button>
                ) : null}
                {can("invoice:approve") && ["VALIDATED", "MATCHED"].includes(invoice.status) ? (
                  <Button size="sm" variant="primary" loading={approve.isPending} onClick={() => approve.mutate()}>
                    <CheckCircle2 className="h-3.5 w-3.5" />
                    {t("invoices.approve")}
                  </Button>
                ) : null}
                {can("invoice:approve") && invoice.status === "APPROVED" ? (
                  <Button size="sm" variant="primary" loading={transition.isPending} onClick={() => transition.mutate("READY_FOR_EXPORT")}>
                    {t("invoices.readyForExport")}
                  </Button>
                ) : null}
              </>
            }
          >
            <div className="mt-2 flex flex-wrap items-center gap-2">
              <StatusBadge status={invoice.status} />
              <StatusBadge status={invoice.validation_status} />
              {invoice.open_exception_count ? <Badge tone="warning">{invoice.open_exception_count} open exceptions</Badge> : null}
              <Badge tone="neutral">{invoice.source}</Badge>
              {invoice.is_demo ? <Badge tone="neutral">demo</Badge> : null}
            </div>
          </PageHeader>

          <div className="grid gap-4 xl:grid-cols-[1.5fr_1fr]">
            <div className="space-y-4">
              <Card>
                <CardHeader title={t("common.total")} description={`${invoice.currency} · payment terms ${invoice.payment_terms_days} days`} />
                <CardBody>
                  <div className="grid grid-cols-3 gap-4">
                    <div>
                      <p className="eyebrow">{t("common.subtotal")}</p>
                      <p className="num mt-1 text-[17px] font-semibold">{formatMoney(invoice.subtotal, invoice.currency)}</p>
                    </div>
                    <div>
                      <p className="eyebrow">{t("common.tax")}</p>
                      <p className="num mt-1 text-[17px] font-semibold">{formatMoney(invoice.tax, invoice.currency)}</p>
                    </div>
                    <div>
                      <p className="eyebrow">{t("common.total")}</p>
                      <p className="num mt-1 text-[20px] font-semibold">{formatMoney(invoice.total, invoice.currency)}</p>
                    </div>
                  </div>
                  <div className="mt-4 grid grid-cols-2 gap-3 border-t border-[var(--line)] pt-3 text-[12px] sm:grid-cols-4">
                    <div><p className="eyebrow">{t("invoices.dueDate")}</p><p>{formatDate(invoice.due_date)}</p></div>
                    <div><p className="eyebrow">{t("common.vendor")}</p>
                      {invoice.vendor ? <Link to={`/vendors/${invoice.vendor.id}`} className="link">{invoice.vendor.legal_name}</Link> : <p>—</p>}
                    </div>
                    <div><p className="eyebrow">{t("invoices.purchaseOrder")}</p>
                      {invoice.purchase_order_id ? <Link to={`/purchase-orders/${invoice.purchase_order_id}`} className="link">{invoice.purchase_order_number}</Link> : <p className="text-[var(--muted)]">—</p>}
                    </div>
                    <div><p className="eyebrow">{t("common.case")}</p>
                      {invoice.case_id ? <Link to={`/cases/${invoice.case_id}`} className="link">Open case</Link> : <p className="text-[var(--muted)]">—</p>}
                    </div>
                  </div>
                </CardBody>
              </Card>

              <Card>
                <CardHeader title={t("invoices.lineItems")} />
                {invoice.items.length === 0 ? (
                  <EmptyState title="No line items" body="This invoice was created without item-level detail." />
                ) : (
                  <div className="overflow-x-auto">
                    <table className="table">
                      <thead>
                        <tr>
                          <th>#</th>
                          <th>{t("common.description")}</th>
                          <th className="text-right">{t("common.quantity")}</th>
                          <th className="text-right">{t("common.unitPrice")}</th>
                          <th className="text-right">{t("common.tax")} %</th>
                          <th className="text-right">{t("common.lineTotal")}</th>
                        </tr>
                      </thead>
                      <tbody>
                        {invoice.items.map((item) => (
                          <tr key={item.id}>
                            <td className="num">{item.line_number}</td>
                            <td>{item.description}</td>
                            <td className="num text-right">{item.quantity}</td>
                            <td className="num text-right">{formatMoney(item.unit_price, invoice.currency)}</td>
                            <td className="num text-right">{item.tax_rate}</td>
                            <td className="num text-right font-semibold">{formatMoney(item.line_total, invoice.currency)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </Card>

              <Card>
                <CardHeader title={t("invoices.validationChecks")} description={invoice.validation_notes.length ? `${invoice.validation_notes.length} check(s)` : t("invoices.noChecks")} />
                <CardBody className="space-y-2 pt-3">
                  {invoice.validation_notes.map((check, index) => (
                    <div key={`${check.code}-${index}`} className={cn("rounded border px-3 py-2", check.severity === "FAIL" ? "border-[var(--danger)]/30 bg-[var(--danger-soft)]" : check.severity === "WARN" ? "border-[var(--warning)]/30 bg-[var(--warning-soft)]" : "border-[var(--line)]")}>
                      <div className="flex items-center gap-2">
                        {check.severity === "FAIL" ? <TriangleAlert className="h-3.5 w-3.5 text-[var(--danger)]" /> : <CheckCircle2 className="h-3.5 w-3.5 text-[var(--muted)]" />}
                        <span className="mono text-[10.5px] uppercase text-[var(--muted)]">{check.code}</span>
                        <Badge tone={check.severity === "FAIL" ? "danger" : "warning"}>{check.severity}</Badge>
                      </div>
                      <p className="mt-1 text-[12px]">{check.message}</p>
                    </div>
                  ))}
                  {invoice.validation_notes.length === 0 ? <p className="text-[12px] text-[var(--muted)]">Run validation to generate deterministic checks.</p> : null}
                </CardBody>
              </Card>
            </div>

            <div className="space-y-4">
              <Card>
                <CardHeader title={t("invoices.exceptions")} description="Exceptions linked to this invoice" />
                <CardBody className="space-y-2 pt-3">
                  {invoice.exceptions.map((exception) => (
                    <div key={exception.id} className="rounded border border-[var(--line)] px-2.5 py-2">
                      <div className="flex items-center gap-2">
                        <Badge tone={exception.severity === "HIGH" ? "warning" : "neutral"}>{humanize(exception.severity)}</Badge>
                        <span className="text-[12px] font-semibold">{exception.title}</span>
                      </div>
                      <p className="mt-0.5 text-[10.5px] text-[var(--muted)]">{humanize(exception.exception_type)} · {humanize(exception.status)}</p>
                    </div>
                  ))}
                  {invoice.exceptions.length === 0 ? <p className="text-[12px] text-[var(--muted)]">No exceptions.</p> : null}
                </CardBody>
              </Card>

              <Card>
                <CardHeader title={t("invoices.candidates")} description="Deterministic vendor/amount/date match" />
                <CardBody className="space-y-2 pt-3">
                  {invoice.purchase_order_candidates.map((candidate) => (
                    <div key={candidate.id} className="flex items-center justify-between rounded border border-[var(--line)] px-2.5 py-2">
                      <div>
                        <p className="mono text-[11.5px] font-semibold">{candidate.po_number}</p>
                        <p className="num text-[10.5px] text-[var(--muted)]">
                          {formatMoney(candidate.total, candidate.currency)} · Δ {candidate.percent_difference}%
                        </p>
                      </div>
                      {candidate.within_tolerance ? <Badge tone="success">within tolerance</Badge> : <Badge tone="warning">outside</Badge>}
                    </div>
                  ))}
                  {invoice.purchase_order_candidates.length === 0 ? (
                    <p className="text-[12px] text-[var(--muted)]">No candidate purchase orders.</p>
                  ) : null}
                </CardBody>
              </Card>

              {invoice.document_id ? (
                <Card>
                  <CardBody className="flex items-center justify-between">
                    <div>
                      <p className="eyebrow">Source document</p>
                      <p className="text-[12px]">Extracted and reviewed</p>
                    </div>
                    <Button asChild size="sm" variant="secondary">
                      <Link to={`/documents/${invoice.document_id}`}>
                        Open <ArrowUpRight className="h-3 w-3" />
                      </Link>
                    </Button>
                  </CardBody>
                </Card>
              ) : null}
            </div>
          </div>

          <p className="mt-4 text-[10.5px] text-[var(--muted)]">
            Created {invoice.created_at ? formatDateTime(invoice.created_at) : "—"} · Validation is deterministic; approval is a human action recorded in the audit trail.
          </p>
        </>
      )}

      <Dialog open={matchOpen} onOpenChange={setMatchOpen}>
        <DialogContent title={t("invoices.matchPo")} description="Candidates are filtered by vendor, currency and amount tolerance." wide>
          <div className="space-y-3">
            {(invoice?.purchase_order_candidates ?? []).map((candidate) => (
              <div key={candidate.id} className="flex items-center justify-between rounded border border-[var(--line)] px-3 py-2">
                <div>
                  <p className="mono text-[12px] font-semibold">{candidate.po_number}</p>
                  <p className="num text-[11px] text-[var(--muted)]">
                    {formatMoney(candidate.total, candidate.currency)} · {candidate.percent_difference}% difference
                  </p>
                </div>
                <Button size="sm" variant={candidate.within_tolerance ? "primary" : "secondary"} loading={match.isPending} onClick={() => match.mutate(candidate.id)}>
                  {t("common.select")}
                </Button>
              </div>
            ))}
            {(invoice?.purchase_order_candidates ?? []).length === 0 ? (
              <EmptyState title="No candidates" body="No open purchase order matches this vendor, currency and amount." />
            ) : null}
            <div className="flex justify-end border-t border-[var(--line)] pt-3">
              <Button variant="secondary" loading={match.isPending} onClick={() => match.mutate(null)}>
                Auto-match best candidate
              </Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}
