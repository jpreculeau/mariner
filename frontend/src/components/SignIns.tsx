import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { useI18n, type TextKey } from "@/lib/i18n";

const KNOWN: Record<string, TextKey> = {
  signed_in: "journal.signed_in",
  wrong_password: "journal.wrong_password",
  wrong_code: "journal.wrong_code",
  code_locked: "journal.code_locked",
  sign_in_closed: "journal.sign_in_closed",
  password_chosen: "journal.password_chosen",
  password_changed: "journal.password_changed",
  code_set: "journal.code_set",
  code_removed: "journal.code_removed",
};

/**
 * The last sign-ins and attempts Mariner remembers: for its owner to see
 * that somebody has been at the door.
 */
export function SignIns() {
  const { t, lang } = useI18n();
  const { data, isError, isLoading } = useQuery({
    queryKey: ["auth", "journal"],
    queryFn: () => api.journal(),
    // As it stood when the page was opened: asked again at each visit.
    staleTime: 0,
  });

  if (isLoading) {
    return (
      <p className="text-base text-muted-foreground">{t("journal.loading")}</p>
    );
  }
  if (isError || !data) {
    return (
      <p className="text-base text-muted-foreground">{t("journal.unread")}</p>
    );
  }

  const when = new Intl.DateTimeFormat(lang, {
    dateStyle: "medium",
    timeStyle: "short",
  });
  const tried = data.wrong_since_last_visit;

  return (
    <div className="grid gap-4">
      {tried > 0 && (
        <p className="text-base font-medium leading-relaxed">
          {t(tried === 1 ? "journal.tried.one" : "journal.tried.many", {
            count: String(tried),
          })}
        </p>
      )}
      {data.entries.length === 0 ? (
        <p className="text-base text-muted-foreground">{t("journal.none")}</p>
      ) : (
        <div className="overflow-x-auto">
          <table
            aria-label={t("journal.caption")}
            className="w-full border-collapse text-left text-sm"
          >
            <thead>
              <tr className="border-b">
                <th scope="col" className="py-2 pr-4 font-medium">
                  {t("journal.when")}
                </th>
                <th scope="col" className="py-2 pr-4 font-medium">
                  {t("journal.what")}
                </th>
                <th scope="col" className="py-2 font-medium">
                  {t("journal.where")}
                </th>
              </tr>
            </thead>
            <tbody>
              {data.entries.map((entry, index) => (
                <tr key={`${entry.at}-${index}`} className="border-b">
                  <td className="py-2 pr-4 align-top">
                    <time dateTime={new Date(entry.at * 1000).toISOString()}>
                      {when.format(new Date(entry.at * 1000))}
                    </time>
                  </td>
                  <td className="py-2 pr-4 align-top">
                    {KNOWN[entry.what] ? t(KNOWN[entry.what]) : entry.what}
                    {(entry.count ?? 1) > 1 &&
                      t("journal.times", { count: String(entry.count) })}
                  </td>
                  <td className="py-2 align-top [overflow-wrap:anywhere]">
                    {t(entry.internet ? "journal.internet" : "journal.local", {
                      address: entry.from,
                    })}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
