import { Link } from "react-router-dom";
import { useI18n } from "@/lib/i18n";
import { usePageTitle } from "@/hooks/use-page-title";

const NotFound = () => {
  const { t } = useI18n();
  usePageTitle(t("title.notFound"));

  return (
    <div className="container py-16 text-center">
      <h1 className="mb-4 text-2xl font-bold tracking-tight">
        {t("notFound.heading")}
      </h1>
      <p className="mb-6 text-muted-foreground">{t("notFound.text")}</p>
      <Link to="/" className="text-primary underline hover:text-primary/90">
        {t("notFound.home")}
      </Link>
    </div>
  );
};

export default NotFound;
