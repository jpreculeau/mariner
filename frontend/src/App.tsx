import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import { Toaster as Sonner } from "@/components/ui/sonner";
import { Toaster } from "@/components/ui/toaster";
import { TooltipProvider } from "@/components/ui/tooltip";
import { AppNav } from "@/components/AppNav";
import { LanguageProvider, useI18n } from "@/lib/i18n";
import Index from "./pages/Index";
import Files from "./pages/Files";
import NotFound from "./pages/NotFound";

const queryClient = new QueryClient();

function Page() {
  const { t } = useI18n();
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

const App = () => (
  <QueryClientProvider client={queryClient}>
    <LanguageProvider>
      <TooltipProvider>
        <Toaster />
        {/* Long enough to read a refusal and what to do about it. */}
        <Sonner duration={8000} closeButton />
        <BrowserRouter>
          <Page />
        </BrowserRouter>
      </TooltipProvider>
    </LanguageProvider>
  </QueryClientProvider>
);

export default App;
