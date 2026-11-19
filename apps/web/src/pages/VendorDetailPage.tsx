import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, Mail, Phone, ShieldAlert } from "lucide-react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { api } from "@/lib/api";
import { formatDate, formatMoney, formatNumber, humanize } from "@/lib/format";
import { useI18n } from "@/i18n";
import { useAuth } from "@/providers/auth";
import {
  Badge,
  Button,
  Card,
  CardBody,
  CardHeader,
  EmptyState,
  ErrorState,
  PageHeader,
  Skeleton,
  StatusBadge,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "@/components/ui";
import type { VendorDetail } from "@/types/api";

export function VendorDetailPage() {
  const { id = "" } = useParams();
  const { t } = useI18n();
  const { can } = useAuth();
  const navigate = useNavigate();

  const detail = useQuery({
    queryKey: ["vendor", id],
    queryFn: () => api.get<VendorDetail>(`/vendors/${id}`),
  });

  const vendor = detail.data;

  if (detail.isError) {
    return <Card><ErrorState message={(detail.error as Error).message} onRetry={() => detail.refetch()} /></Card>;
  }

  return (
    <>
      <button className="mb-3 inline-flex items-center gap-1.5 text-[12px] font-semibold text-[var(--muted)] hover:text-[var(--ink)]" onClick={() => navigate("/vendors")}>
        <ArrowLeft className="h-3.5 w-3.5" />
        {t("vendors.title")}
      </button>

      {detail.isLoading || !vendor ? (
        <Skeleton className="h-56" />
      ) : (
        <>
          <PageHeader
            title={vendor.legal_name}
            subtitle={`${vendor.vendor_number} · ${vendor.city ?? ""} ${vendor.country ?? ""}`.trim()}
            actions={
              can("vendor:update") ? (
                <Button size="sm" variant="secondary">{t("common.edit")}</Button>
              ) : undefined
            }
          >
            <div className="mt-2 flex flex-wrap items-center gap-2">
              <StatusBadge status={vendor.status} />
              <Badge tone="neutral">{vendor.currency}</Badge>
              <Badge tone="neutral">{vendor.payment_terms_days} days</Badge>
              {vendor.is_demo ? <Badge tone="neutral">demo</Badge> : null}
              {vendor.risk_flags.map((flag) => <Badge key={flag} tone="warning">{humanize(flag)}</Badge>)}
            </div>
          </PageHeader>

          <div className="grid gap-4 xl:grid-cols-[320px_1fr]">
            <div className="space-y-4">
              <Card>
                <CardHeader title={t("common.details")} />
                <CardBody className="space-y-2 text-[12px]">
                  <div className="flex justify-between gap-2"><span className="text-[var(--muted)]">{t("vendors.taxId")}</span><span className="mono">{vendor.tax_id ?? "—"}</span></div>
                  <div className="flex justify-between gap-2"><span className="text-[var(--muted)]">{t("vendors.contact")}</span><span>{vendor.contact_name ?? "—"}</span></div>
                  <div className="flex items-center justify-between gap-2"><span className="text-[var(--muted)]">{t("common.email")}</span><span className="flex items-center gap-1 truncate"><Mail className="h-3 w-3" />{vendor.email ?? "—"}</span></div>
                  <div className="flex items-center justify-between gap-2"><span className="text-[var(--muted)]">Phone</span><span className="flex items-center gap-1"><Phone className="h-3 w-3" />{vendor.phone ?? "—"}</span></div>
                  <div className="flex justify-between gap-2"><span className="text-[var(--muted)]">Address</span><span className="text-right">{[vendor.address_line1, vendor.city, vendor.payment_terms_days ? vendor.country : null].filter(Boolean).join(", ") || "—"}</span></div>
                  <div className="flex justify-between gap-2 border-t border-[var(--line)] pt-2"><span className="text-[var(--muted)]">{t("vendors.invoices")}</span><span className="num font-semibold">{formatNumber(vendor.invoice_count)}</span></div>
                  <div className="flex justify-between gap-2"><span className="text-[var(--muted)]">{t("vendors.exceptions")}</span><span className="num font-semibold">{formatNumber(vendor.open_exception_count)}</span></div>
                </CardBody>
              </Card>
              {vendor.notes ? (
                <Card><CardBody><p className="eyebrow mb-1">{t("common.notes")}</p><p className="text-[12px]">{vendor.notes}</p></CardBody></Card>
              ) : null}
            </div>

            <Card>
              <Tabs defaultValue="invoices">
                <div className="px-3 pt-1">
                  <TabsList>
                    <TabsTrigger value="invoices">{t("vendors.invoices")}</TabsTrigger>
                    <TabsTrigger value="pos">{t("vendors.purchaseOrders")}</TabsTrigger>
                    <TabsTrigger value="docs">{t("nav.documents")}</TabsTrigger>
                    <TabsTrigger value="exceptions">{t("vendors.exceptions")}</TabsTrigger>
                  </TabsList>
                </div>
                <TabsContent value="invoices" className="px-4 pb-4">
                  {vendor.recent_invoices.length === 0 ? <EmptyState title="No invoices" /> : (
                    <div className="divide-y divide-[var(--line)]">
                      {vendor.recent_invoices.map((invoice) => (
                        <Link key={String(invoice.id)} to={`/invoices/${invoice.id}`} className="flex items-center justify-between py-2 text-[12px] hover:bg-[var(--surface-2)]">
                          <div><span className="mono font-semibold">{String(invoice.invoice_number)}</span><span className="ml-2 text-[var(--muted)]">{formatDate(String(invoice.invoice_date))}</span></div>
                          <div className="flex items-center gap-2"><span className="num">{formatMoney(String(invoice.total), String(invoice.currency))}</span><StatusBadge status={String(invoice.status)} /></div>
                        </Link>
                      ))}
                    </div>
                  )}
                </TabsContent>
                <TabsContent value="pos" className="px-4 pb-4">
                  {vendor.purchase_orders.length === 0 ? <EmptyState title="No purchase orders" /> : (
                    <div className="divide-y divide-[var(--line)]">
                      {vendor.purchase_orders.map((po) => (
                        <Link key={String(po.id)} to={`/purchase-orders/${po.id}`} className="flex items-center justify-between py-2 text-[12px] hover:bg-[var(--surface-2)]">
                          <div><span className="mono font-semibold">{String(po.po_number)}</span><span className="ml-2 text-[var(--muted)]">{formatDate(String(po.issue_date))}</span></div>
                          <div className="flex items-center gap-2"><span className="num">{formatMoney(String(po.total), String(po.currency))}</span><StatusBadge status={String(po.status)} /></div>
                        </Link>
                      ))}
                    </div>
                  )}
                </TabsContent>
                <TabsContent value="docs" className="px-4 pb-4">
                  {vendor.documents.length === 0 ? <EmptyState title="No documents" /> : (
                    <div className="divide-y divide-[var(--line)]">
                      {vendor.documents.map((doc) => (
                        <Link key={doc.id} to={`/documents/${doc.id}`} className="flex items-center justify-between py-2 text-[12px] hover:bg-[var(--surface-2)]">
                          <span>{doc.original_filename}</span>
                          <div className="flex items-center gap-2"><Badge tone="neutral">{humanize(doc.document_type)}</Badge><StatusBadge status={doc.status} /></div>
                        </Link>
                      ))}
                    </div>
                  )}
                </TabsContent>
                <TabsContent value="exceptions" className="px-4 pb-4">
                  {vendor.exceptions.length === 0 ? <EmptyState title="No vendor exceptions" /> : (
                    <div className="divide-y divide-[var(--line)]">
                      {vendor.exceptions.map((exception) => (
                        <div key={exception.id} className="flex items-center justify-between py-2 text-[12px]">
                          <div className="flex items-center gap-2"><ShieldAlert className="h-3.5 w-3.5 text-[var(--warning)]" />{exception.title}</div>
                          <div className="flex items-center gap-2"><Badge tone="warning">{humanize(exception.severity)}</Badge><StatusBadge status={exception.status} /></div>
                        </div>
                      ))}
                    </div>
                  )}
                </TabsContent>
              </Tabs>
            </Card>
          </div>
        </>
      )}
    </>
  );
}
