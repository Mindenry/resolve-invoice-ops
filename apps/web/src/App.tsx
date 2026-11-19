import type { ReactNode } from "react";
import { Navigate, Outlet, Route, Routes, useLocation, useNavigate } from "react-router-dom";

import { useAuth } from "@/providers/auth";
import { AppShell } from "@/layouts/AppShell";
import { Button, Card, EmptyState, Spinner } from "@/components/ui";
import { LoginPage } from "@/pages/auth/LoginPage";
import { RegisterPage } from "@/pages/auth/RegisterPage";
import { ForgotPasswordPage, ResetPasswordPage } from "@/pages/auth/PasswordPages";
import { CommandCenterPage } from "@/pages/CommandCenterPage";
import { ExceptionsPage } from "@/pages/ExceptionsPage";
import { CasesPage } from "@/pages/CasesPage";
import { CaseDetailPage } from "@/pages/CaseDetailPage";
import { DocumentsPage } from "@/pages/DocumentsPage";
import { DocumentDetailPage } from "@/pages/DocumentDetailPage";
import { InvoicesPage } from "@/pages/InvoicesPage";
import { InvoiceDetailPage } from "@/pages/InvoiceDetailPage";
import { VendorsPage } from "@/pages/VendorsPage";
import { VendorDetailPage } from "@/pages/VendorDetailPage";
import { PurchaseOrderDetailPage, PurchaseOrdersPage } from "@/pages/PurchaseOrdersPage";
import { ApprovalsPage } from "@/pages/ApprovalsPage";
import { IntegrationsPage } from "@/pages/IntegrationsPage";
import { WorkflowsPage } from "@/pages/WorkflowsPage";
import { EvaluationPage } from "@/pages/EvaluationPage";
import { AnalyticsPage } from "@/pages/AnalyticsPage";
import { AuditPage } from "@/pages/AuditPage";
import { SettingsPage } from "@/pages/SettingsPage";

function Splash() {
  return (
    <div className="flex min-h-screen items-center justify-center">
      <div className="flex items-center gap-2 text-[13px] text-[var(--muted)]">
        <Spinner />
        Loading workspace…
      </div>
    </div>
  );
}

function ProtectedLayout() {
  const { status } = useAuth();
  const location = useLocation();
  if (status === "loading") return <Splash />;
  if (status === "anonymous") return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  return (
    <AppShell>
      <Outlet />
    </AppShell>
  );
}

function Require({ permission, children }: { permission: string; children: ReactNode }) {
  const { can } = useAuth();
  const navigate = useNavigate();
  if (!can(permission)) {
    return (
      <Card>
        <EmptyState
          title="You do not have access to this area"
          body="Your role does not include the required permission. Ask an organization administrator if you need access."
          action={
            <Button size="sm" variant="secondary" onClick={() => navigate("/")}>
              Back to command center
            </Button>
          }
        />
      </Card>
    );
  }
  return <>{children}</>;
}

function NotFound() {
  const navigate = useNavigate();
  return (
    <div className="flex min-h-screen items-center justify-center px-6">
      <Card className="max-w-md">
        <EmptyState
          title="Page not found"
          body="The page you requested does not exist or has moved."
          action={
            <Button size="sm" variant="primary" onClick={() => navigate("/")}>
              Open command center
            </Button>
          }
        />
      </Card>
    </div>
  );
}

export function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/register" element={<RegisterPage />} />
      <Route path="/forgot-password" element={<ForgotPasswordPage />} />
      <Route path="/reset-password" element={<ResetPasswordPage />} />

      <Route element={<ProtectedLayout />}>
        <Route index element={<Require permission="analytics:read"><CommandCenterPage /></Require>} />
        <Route path="exceptions" element={<Require permission="exception:read"><ExceptionsPage /></Require>} />
        <Route path="cases" element={<Require permission="case:read"><CasesPage /></Require>} />
        <Route path="cases/:id" element={<Require permission="case:read"><CaseDetailPage /></Require>} />
        <Route path="documents" element={<Require permission="document:read"><DocumentsPage /></Require>} />
        <Route path="documents/:id" element={<Require permission="document:read"><DocumentDetailPage /></Require>} />
        <Route path="invoices" element={<Require permission="invoice:read"><InvoicesPage /></Require>} />
        <Route path="invoices/:id" element={<Require permission="invoice:read"><InvoiceDetailPage /></Require>} />
        <Route path="vendors" element={<Require permission="vendor:read"><VendorsPage /></Require>} />
        <Route path="vendors/:id" element={<Require permission="vendor:read"><VendorDetailPage /></Require>} />
        <Route path="purchase-orders" element={<Require permission="po:read"><PurchaseOrdersPage /></Require>} />
        <Route path="purchase-orders/:id" element={<Require permission="po:read"><PurchaseOrderDetailPage /></Require>} />
        <Route path="approvals" element={<Require permission="approval:read"><ApprovalsPage /></Require>} />
        <Route path="integrations" element={<Require permission="integration:read"><IntegrationsPage /></Require>} />
        <Route path="workflows" element={<Require permission="workflow:read"><WorkflowsPage /></Require>} />
        <Route path="evaluation" element={<Require permission="evaluation:read"><EvaluationPage /></Require>} />
        <Route path="analytics" element={<Require permission="analytics:read"><AnalyticsPage /></Require>} />
        <Route path="audit" element={<Require permission="audit:read"><AuditPage /></Require>} />
        <Route path="settings" element={<Require permission="org:read"><SettingsPage /></Require>} />
      </Route>

      <Route path="*" element={<NotFound />} />
    </Routes>
  );
}
