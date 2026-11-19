import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { TooltipProvider } from "@radix-ui/react-tooltip";
import { Toaster } from "sonner";
import type { ReactNode } from "react";

import { I18nProvider } from "@/i18n";
import { AuthProvider } from "@/providers/auth";
import { ThemeProvider } from "@/providers/theme";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 15_000,
      refetchOnWindowFocus: false,
      retry: (failureCount, error: any) => {
        if (error?.status === 401 || error?.status === 403 || error?.status === 404) return false;
        return failureCount < 1;
      },
    },
  },
});

export function AppProviders({ children }: { children: ReactNode }) {
  return (
    <QueryClientProvider client={queryClient}>
      <I18nProvider>
        <ThemeProvider>
          <AuthProvider>
            <TooltipProvider delayDuration={250}>
              {children}
              <Toaster
                position="bottom-right"
                toastOptions={{
                  style: {
                    background: "var(--surface)",
                    color: "var(--ink)",
                    border: "1px solid var(--line)",
                    fontSize: "13px",
                  },
                }}
              />
            </TooltipProvider>
          </AuthProvider>
        </ThemeProvider>
      </I18nProvider>
    </QueryClientProvider>
  );
}
