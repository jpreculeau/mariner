import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { BrowserRouter, Route, Routes, useLocation } from "react-router-dom";
import { Toaster as Sonner } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";
import { AppNav } from "@/components/AppNav";
import { UploadProvider } from "@/components/UploadProvider";
import { UploadStatus } from "@/components/UploadStatus";
import { LanguageProvider, useI18n } from "@/lib/i18n";
import { shouldRetry } from "@/lib/api";
import Index from "./pages/Index";
import Files from "./pages/Files";
import NotFound from "./pages/NotFound";

/**
 * Put focus in the content when another page is shown: it would
 * otherwise stay on the link that was followed, or fall to the top of
 * the page with the button that was pressed.
 */
function useFocusOnNavigation() {
  const { pathname } = useLocation();
  const shown = useRef(pathname);
  useEffect(() => {
    if (shown.current === pathname) return;
    shown.current = pathname;
    document.getElementById("content")?.focus();
  }, [pathname]);
}

function Page() {
  const { t } = useI18n();
  useFocusOnNavigation();
  return (
    <div className="min-h-screen bg-background text-foreground">
      {/* First of the page: lets a keyboard go past the menu. Shown only
          when it is reached. */}
      <a
        href="#content"
        className="sr-only focus:not-sr-only focus:fixed focus:left-2 focus:top-2 focus:z-50 focus:rounded-md focus:bg-primary focus:px-3 focus:py-2 focus:text-sm focus:font-medium focus:text-primary-foreground"
      >
        {t("app.skipToContent")}
      </a>
      <AppNav />
      <UploadStatus />
      <main id="content" tabIndex={-1} className="focus:outline-none">
        <Routes>
          <Route path="/" element={<Index />} />
          <Route path="/files" element={<Files />} />
          <Route path="*" element={<NotFound />} />
        </Routes>
      </main>
    </div>
  );
}

const App = () => {
  // One per page shown, not one for the module: what it has fetched
  // belongs to that page.
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: { queries: { retry: shouldRetry } },
      }),
  );
  return (
    <QueryClientProvider client={queryClient}>
      <LanguageProvider>
        <TooltipProvider>
          <Sonner duration={8000} />
          <BrowserRouter>
            <UploadProvider>
              <Page />
            </UploadProvider>
          </BrowserRouter>
        </TooltipProvider>
      </LanguageProvider>
    </QueryClientProvider>
  );
};

export default App;
