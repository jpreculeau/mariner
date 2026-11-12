import { Link, useLocation } from "react-router-dom";
import { Printer, FolderOpen } from "lucide-react";
import { cn } from "@/lib/utils";
import { PowerMenu } from "@/components/PowerMenu";
import { ThemeSwitcher } from "@/components/ThemeSwitcher";
import { useI18n, type TextKey } from "@/lib/i18n";

const navItems: { to: string; label: TextKey; icon: typeof Printer }[] = [
  { to: "/", label: "nav.dashboard", icon: Printer },
  { to: "/files", label: "nav.files", icon: FolderOpen },
];

export function AppNav() {
  const location = useLocation();
  const { t } = useI18n();

  return (
    <header className="sticky top-0 z-40 border-b bg-card/80 backdrop-blur-sm">
      <div className="container flex h-14 items-center justify-between">
        <div className="flex items-center gap-2">
          <div
            className="flex h-8 w-8 items-center justify-center rounded bg-primary"
            aria-hidden
          >
            <Printer className="h-4 w-4 text-primary-foreground" />
          </div>
          <span className="font-display text-lg font-bold tracking-tight">
            Mariner 2
          </span>
        </div>

        <div className="flex items-center gap-1">
          <nav aria-label={t("nav.main")} className="flex items-center gap-1">
            {navItems.map((item) => {
              const isActive = location.pathname === item.to;
              return (
                <Link
                  key={item.to}
                  to={item.to}
                  aria-current={isActive ? "page" : undefined}
                  className={cn(
                    "flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-medium transition-colors",
                    isActive
                      ? "bg-primary/10 text-primary"
                      : "text-muted-foreground hover:text-foreground",
                  )}
                >
                  <item.icon className="h-4 w-4" aria-hidden />
                  {/* On a phone only the icon shows: the word stays for
                      those who cannot see it. */}
                  <span className="sr-only sm:not-sr-only">
                    {t(item.label)}
                  </span>
                </Link>
              );
            })}
          </nav>
          <div className="ml-1 flex items-center gap-0.5 border-l border-border pl-1">
            <ThemeSwitcher />
            <PowerMenu />
          </div>
        </div>
      </div>
    </header>
  );
}
