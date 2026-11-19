import * as DropdownMenu from "@radix-ui/react-dropdown-menu";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Activity,
  BadgeCheck,
  Bell,
  Building2,
  Check,
  ChevronDown,
  ClipboardCheck,
  ClipboardList,
  FileSearch,
  FileText,
  Globe2,
  LayoutDashboard,
  LogOut,
  Menu,
  Moon,
  Network,
  PackageSearch,
  Search,
  Settings,
  ShieldCheck,
  Sun,
  Workflow,
  X,
} from "lucide-react";
import { useEffect, useMemo, useState, type FormEvent, type ReactNode } from "react";
import { NavLink, useLocation, useNavigate } from "react-router-dom";

import { api } from "@/lib/api";
import { formatNumber, humanize } from "@/lib/format";
import { cn } from "@/lib/utils";
import { ROLE_LABELS, useI18n } from "@/i18n";
import { useAuth } from "@/providers/auth";
import { useTheme } from "@/providers/theme";
import { Avatar, Badge, Button } from "@/components/ui";
import type { Notification, Page, SystemInfo } from "@/types/api";

interface NavEntry {
  to: string;
  labelKey: string;
  icon: ReactNode;
  permission: string;
}

const NAV_SECTIONS: { titleKey: string; items: NavEntry[] }[] = [
  {
    titleKey: "nav.sectionOps",
    items: [
      { to: "/", labelKey: "nav.commandCenter", icon: <LayoutDashboard className="h-4 w-4" />, permission: "analytics:read" },
      { to: "/exceptions", labelKey: "nav.exceptions", icon: <FileSearch className="h-4 w-4" />, permission: "exception:read" },
      { to: "/cases", labelKey: "nav.cases", icon: <ClipboardList className="h-4 w-4" />, permission: "case:read" },
    ],
  },
  {
    titleKey: "nav.sectionRecords",
    items: [
      { to: "/documents", labelKey: "nav.documents", icon: <FileText className="h-4 w-4" />, permission: "document:read" },
      { to: "/invoices", labelKey: "nav.invoices", icon: <FileSearch className="h-4 w-4" />, permission: "invoice:read" },
      { to: "/vendors", labelKey: "nav.vendors", icon: <Building2 className="h-4 w-4" />, permission: "vendor:read" },
      { to: "/purchase-orders", labelKey: "nav.purchaseOrders", icon: <PackageSearch className="h-4 w-4" />, permission: "po:read" },
    ],
  },
  {
    titleKey: "nav.sectionGovernance",
    items: [
      { to: "/approvals", labelKey: "nav.approvals", icon: <BadgeCheck className="h-4 w-4" />, permission: "approval:read" },
      { to: "/integrations", labelKey: "nav.integrations", icon: <Network className="h-4 w-4" />, permission: "integration:read" },
      { to: "/workflows", labelKey: "nav.workflows", icon: <Workflow className="h-4 w-4" />, permission: "workflow:read" },
      { to: "/evaluation", labelKey: "nav.evaluation", icon: <Activity className="h-4 w-4" />, permission: "evaluation:read" },
      { to: "/analytics", labelKey: "nav.analytics", icon: <ShieldCheck className="h-4 w-4" />, permission: "analytics:read" },
      { to: "/audit", labelKey: "nav.audit", icon: <ClipboardCheck className="h-4 w-4" />, permission: "audit:read" },
      { to: "/settings", labelKey: "nav.settings", icon: <Settings className="h-4 w-4" />, permission: "org:read" },
    ],
  },
];

const TITLES: [string, string][] = [
  ["/exceptions", "exceptions.title"],
  ["/cases", "cases.title"],
  ["/documents", "docs.title"],
  ["/invoices", "invoices.title"],
  ["/vendors", "vendors.title"],
  ["/purchase-orders", "po.title"],
  ["/approvals", "approvals.title"],
  ["/integrations", "integrations.title"],
  ["/workflows", "workflows.title"],
  ["/evaluation", "evaluation.title"],
  ["/analytics", "analytics.title"],
  ["/audit", "audit.title"],
  ["/settings", "settings.title"],
  ["/", "dashboard.title"],
];

export function AppShell({ children }: { children: ReactNode }) {
  const { t, locale, setLocale } = useI18n();
  const { theme, toggleTheme } = useTheme();
  const { session, can, logout, switchOrganization, isDemo } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const queryClient = useQueryClient();
  const [mobileOpen, setMobileOpen] = useState(false);
  const [search, setSearch] = useState("");

  useEffect(() => {
    setMobileOpen(false);
  }, [location.pathname]);

  const unread = useQuery({
    queryKey: ["notifications", "unread"],
    queryFn: () => api.get<{ unread: number }>("/notifications/unread-count"),
    refetchInterval: 60_000,
  });

  const notifications = useQuery({
    queryKey: ["notifications", "recent"],
    queryFn: () => api.get<Page<Notification>>(`/notifications${"?page_size=8"}`),
  });

  const system = useQuery({
    queryKey: ["system", "info"],
    queryFn: () => api.get<SystemInfo>("/system/info"),
    staleTime: 120_000,
  });

  const titleKey = useMemo(() => {
    const match = TITLES.find(([prefix]) =>
      prefix === "/" ? location.pathname === "/" : location.pathname.startsWith(prefix),
    );
    return match?.[1] ?? "dashboard.title";
  }, [location.pathname]);

  const aiConfigured = Boolean(system.data?.ai?.llm_configured);

  const markAllRead = async () => {
    await api.post("/notifications/read-all");
    await queryClient.invalidateQueries({ queryKey: ["notifications"] });
  };

  const handleSearch = (event: FormEvent) => {
    event.preventDefault();
    if (!search.trim()) return;
    navigate(`/cases?search=${encodeURIComponent(search.trim())}`);
  };

  return (
    <div className="flex min-h-screen">
      {mobileOpen ? (
        <div
          className="fixed inset-0 z-30 bg-black/40 lg:hidden"
          onClick={() => setMobileOpen(false)}
          aria-hidden
        />
      ) : null}

      <aside
        className={cn(
          "fixed inset-y-0 left-0 z-40 flex w-[236px] flex-col border-r border-[var(--line)] bg-[var(--bg-elevated)] transition-transform lg:static lg:translate-x-0",
          mobileOpen ? "translate-x-0" : "-translate-x-full",
        )}
      >
        <div className="flex items-center justify-between px-4 pb-3 pt-4">
          <div className="flex items-center gap-2.5">
            <span className="flex h-9 w-9 items-center justify-center rounded-[9px] bg-[var(--accent)] font-display text-[17px] font-bold text-[var(--on-accent)]">
              R
            </span>
            <div className="leading-tight">
              <div className="font-display text-[15px] font-bold tracking-tight">RESOLVE</div>
              <div className="text-[10px] font-medium uppercase tracking-[0.14em] text-[var(--muted)]">
                Operations
              </div>
            </div>
          </div>
          <button className="lg:hidden" onClick={() => setMobileOpen(false)} aria-label="Close navigation">
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="mx-3 mb-2 rounded-md border border-[var(--line)] bg-[var(--surface)] px-2.5 py-2">
          <div className="flex items-center gap-2">
            <span
              className="flex h-6 w-6 items-center justify-center rounded text-[10px] font-bold text-white"
              style={{ background: (session?.organization.branding?.accent as string) || "var(--accent)" }}
            >
              {(session?.organization.branding?.initials as string) || session?.organization.name.slice(0, 2).toUpperCase()}
            </span>
            <div className="min-w-0">
              <p className="truncate text-[12px] font-semibold leading-tight">{session?.organization.name}</p>
              <p className="truncate text-[10.5px] text-[var(--muted)]">{ROLE_LABELS[session?.role ?? "viewer"]}</p>
            </div>
          </div>
          {isDemo ? <Badge tone="warning" className="mt-1.5">Demo workspace</Badge> : null}
        </div>

        <nav className="flex-1 overflow-y-auto pb-4">
          {NAV_SECTIONS.map((section) => {
            const items = section.items.filter((item) => can(item.permission));
            if (items.length === 0) return null;
            return (
              <div key={section.titleKey}>
                <div className="nav-section">{t(section.titleKey)}</div>
                {items.map((item) => (
                  <NavLink
                    key={item.to}
                    to={item.to}
                    end={item.to === "/"}
                    className="nav-item"
                    data-active={location.pathname === item.to || (item.to !== "/" && location.pathname.startsWith(item.to))}
                  >
                    {item.icon}
                    <span>{t(item.labelKey)}</span>
                  </NavLink>
                ))}
              </div>
            );
          })}
        </nav>

        <div className="border-t border-[var(--line)] p-3">
          <div className="flex items-center gap-2 text-[11px] text-[var(--muted)]">
            <span className={cn("dot", aiConfigured ? "text-[var(--success)]" : "text-[var(--warning)]")} />
            <span>{aiConfigured ? `AI · ${system.data?.ai?.llm_provider}` : t("common.aiUnavailable")}</span>
          </div>
          <div className="mt-1 flex items-center gap-2 text-[11px] text-[var(--muted)]">
            <span className="dot text-[var(--success)]" />
            <span className="truncate">{system.data?.environment ?? "development"} · {system.data?.version ?? ""}</span>
          </div>
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col lg:pl-0">
        <header className="sticky top-0 z-20 flex h-[58px] items-center gap-3 border-b border-[var(--line)] bg-[color-mix(in_srgb,var(--bg)_88%,transparent)] px-4 backdrop-blur-md lg:px-6">
          <button className="lg:hidden" onClick={() => setMobileOpen(true)} aria-label="Open navigation">
            <Menu className="h-5 w-5" />
          </button>
          <div className="hidden min-w-0 lg:block">
            <span className="eyebrow">{t("app.name")}</span>
            <span className="mx-2 text-[var(--line-strong)]">/</span>
            <span className="text-[13px] font-semibold">{t(titleKey)}</span>
          </div>

          <form onSubmit={handleSearch} className="relative ml-auto hidden w-full max-w-[320px] md:block">
            <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-[var(--muted)]" />
            <input
              className="input h-[30px] py-0 pl-8 text-[12.5px]"
              placeholder={t("common.searchPlaceholder")}
              value={search}
              onChange={(event) => setSearch(event.target.value)}
            />
          </form>

          <div className="ml-auto flex items-center gap-1 md:ml-0">
            <DropdownMenu.Root>
              <DropdownMenu.Trigger asChild>
                <button
                  className="relative flex h-8 w-8 items-center justify-center rounded-md text-[var(--ink-soft)] hover:bg-[var(--surface-3)]"
                  aria-label={t("common.notifications")}
                >
                  <Bell className="h-4 w-4" />
                  {(unread.data?.unread ?? 0) > 0 ? (
                    <span className="absolute right-1 top-1 flex h-3.5 min-w-3.5 items-center justify-center rounded-full bg-[var(--danger)] px-0.5 text-[9px] font-bold text-white">
                      {unread.data?.unread}
                    </span>
                  ) : null}
                </button>
              </DropdownMenu.Trigger>
              <DropdownMenu.Portal>
                <DropdownMenu.Content
                  align="end"
                  sideOffset={6}
                  className="z-50 w-[340px] rounded-lg border border-[var(--line)] bg-[var(--surface)] p-0 shadow-[var(--shadow-md)]"
                >
                  <div className="flex items-center justify-between border-b border-[var(--line)] px-3 py-2.5">
                    <span className="text-[12.5px] font-semibold">{t("common.notifications")}</span>
                    <button className="text-[11px] font-semibold text-[var(--accent)]" onClick={markAllRead}>
                      {t("common.markAllRead")}
                    </button>
                  </div>
                  <div className="max-h-[360px] overflow-y-auto">
                    {(notifications.data?.items ?? []).length === 0 ? (
                      <p className="px-3 py-6 text-center text-[12px] text-[var(--muted)]">
                        {t("common.noNotifications")}
                      </p>
                    ) : (
                      notifications.data?.items.map((item) => (
                        <button
                          key={item.id}
                          className="block w-full border-b border-[var(--line)] px-3 py-2.5 text-left hover:bg-[var(--surface-2)]"
                          onClick={() => {
                            if (item.entity_type === "CASE" && item.entity_id) navigate(`/cases/${item.entity_id}`);
                            else if (item.entity_type === "APPROVAL") navigate("/approvals");
                            else if (item.entity_type === "DOCUMENT") navigate("/documents");
                          }}
                        >
                          <div className="flex items-start gap-2">
                            <span
                              className={cn(
                                "mt-1.5 dot",
                                item.read_at ? "text-[var(--line-strong)]" : "text-[var(--accent)]",
                              )}
                            />
                            <div className="min-w-0">
                              <p className="truncate text-[12px] font-semibold">{item.title}</p>
                              <p className="line-clamp-2 text-[11px] text-[var(--muted)]">{item.body}</p>
                              <p className="mt-0.5 text-[10px] text-[var(--muted)]">{humanize(item.type)}</p>
                            </div>
                          </div>
                        </button>
                      ))
                    )}
                  </div>
                </DropdownMenu.Content>
              </DropdownMenu.Portal>
            </DropdownMenu.Root>

            <Button variant="ghost" size="icon" onClick={toggleTheme} aria-label={t("common.theme")}>
              {theme === "dark" ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
            </Button>

            <DropdownMenu.Root>
              <DropdownMenu.Trigger asChild>
                <button className="flex h-8 items-center gap-1 rounded-md px-1.5 text-[11px] font-bold text-[var(--ink-soft)] hover:bg-[var(--surface-3)]">
                  <Globe2 className="h-3.5 w-3.5" />
                  {locale.toUpperCase()}
                </button>
              </DropdownMenu.Trigger>
              <DropdownMenu.Portal>
                <DropdownMenu.Content
                  align="end"
                  sideOffset={6}
                  className="z-50 min-w-[140px] rounded-lg border border-[var(--line)] bg-[var(--surface)] p-1 shadow-[var(--shadow-md)]"
                >
                  {(["en", "th"] as const).map((code) => (
                    <DropdownMenu.Item
                      key={code}
                      className="flex cursor-pointer items-center justify-between rounded px-2 py-1.5 text-[12px] outline-none hover:bg-[var(--surface-3)]"
                      onSelect={() => setLocale(code)}
                    >
                      {code === "en" ? "English" : "ไทย"}
                      {locale === code ? <Check className="h-3.5 w-3.5 text-[var(--accent)]" /> : null}
                    </DropdownMenu.Item>
                  ))}
                </DropdownMenu.Content>
              </DropdownMenu.Portal>
            </DropdownMenu.Root>

            <DropdownMenu.Root>
              <DropdownMenu.Trigger asChild>
                <button className="flex h-8 items-center gap-1.5 rounded-md px-1.5 hover:bg-[var(--surface-3)]">
                  <Avatar name={session?.user.full_name} color={session?.user.avatar_color} />
                  <ChevronDown className="h-3 w-3 text-[var(--muted)]" />
                </button>
              </DropdownMenu.Trigger>
              <DropdownMenu.Portal>
                <DropdownMenu.Content
                  align="end"
                  sideOffset={6}
                  className="z-50 w-[260px] rounded-lg border border-[var(--line)] bg-[var(--surface)] p-1 shadow-[var(--shadow-md)]"
                >
                  <div className="border-b border-[var(--line)] px-2.5 py-2">
                    <p className="text-[12.5px] font-semibold">{session?.user.full_name}</p>
                    <p className="truncate text-[11px] text-[var(--muted)]">{session?.user.email}</p>
                    <Badge tone="neutral" className="mt-1.5">
                      {ROLE_LABELS[session?.role ?? "viewer"]}
                    </Badge>
                  </div>
                  {(session?.organizations?.length ?? 0) > 1 ? (
                    <>
                      <DropdownMenu.Label className="px-2.5 pb-1 pt-2 text-[10px] font-semibold uppercase tracking-wider text-[var(--muted)]">
                        {t("common.organization")}
                      </DropdownMenu.Label>
                      {session?.organizations.map((org) => (
                        <DropdownMenu.Item
                          key={org.id}
                          className="flex cursor-pointer items-center justify-between rounded px-2 py-1.5 text-[12px] outline-none hover:bg-[var(--surface-3)]"
                          onSelect={() => {
                            void switchOrganization(org.id).then(() => queryClient.invalidateQueries());
                          }}
                        >
                          <span className="truncate">{org.name}</span>
                          {org.id === session.organization.id ? (
                            <Check className="h-3.5 w-3.5 text-[var(--accent)]" />
                          ) : null}
                        </DropdownMenu.Item>
                      ))}
                      <DropdownMenu.Separator className="my-1 h-px bg-[var(--line)]" />
                    </>
                  ) : null}
                  <DropdownMenu.Item
                    className="cursor-pointer rounded px-2 py-1.5 text-[12px] outline-none hover:bg-[var(--surface-3)]"
                    onSelect={() => navigate("/settings")}
                  >
                    <Settings className="mr-2 inline h-3.5 w-3.5" />
                    {t("common.settings")}
                  </DropdownMenu.Item>
                  <DropdownMenu.Item
                    className="cursor-pointer rounded px-2 py-1.5 text-[12px] text-[var(--danger)] outline-none hover:bg-[var(--danger-soft)]"
                    onSelect={() => {
                      void logout().then(() => navigate("/login"));
                    }}
                  >
                    <LogOut className="mr-2 inline h-3.5 w-3.5" />
                    {t("common.signOut")}
                  </DropdownMenu.Item>
                </DropdownMenu.Content>
              </DropdownMenu.Portal>
            </DropdownMenu.Root>
          </div>
        </header>

        <main className="mx-auto w-full max-w-[1500px] flex-1 px-4 py-5 lg:px-6 lg:py-6">
          <div className="page-enter">{children}</div>
        </main>

        <footer className="border-t border-[var(--line)] px-4 py-2.5 text-[10.5px] text-[var(--muted)] lg:px-6">
          <div className="mx-auto flex max-w-[1500px] flex-wrap items-center justify-between gap-2">
            <span>RESOLVE · evidence-grounded exception management</span>
            <span className="num">
              {formatNumber(notifications.data?.meta.total ?? 0)} notifications · {t("common.demo")}: {isDemo ? "on" : "off"}
            </span>
          </div>
        </footer>
      </div>
    </div>
  );
}

export function RoleHint({ allowed }: { allowed: boolean }) {
  return allowed ? null : <Badge tone="warning">Read-only for your role</Badge>;
}


