import { forwardRef } from "react";

interface PasswordFieldProps {
  id: string;
  label: string;
  /** What is asked of it, said before it is typed. */
  hint?: string;
  /** Something else on the page that says what it is for. */
  describedBy?: string;
  autoComplete: "new-password" | "current-password";
  autoFocus?: boolean;
  value: string;
  /** Why it was not taken, if it was not. */
  error: string | null;
  onChange: (value: string) => void;
}

/** A field for a password, with its name, its hint and its error by it. */
export const PasswordField = forwardRef<HTMLInputElement, PasswordFieldProps>(
  (
    {
      id,
      label,
      hint,
      describedBy,
      autoComplete,
      autoFocus,
      value,
      error,
      onChange,
    },
    ref,
  ) => {
    const described = [
      describedBy ?? null,
      hint ? `${id}-hint` : null,
      error ? `${id}-error` : null,
    ]
      .filter(Boolean)
      .join(" ");
    return (
      <div className="grid gap-1.5">
        <label htmlFor={id} className="text-sm font-medium">
          {label}
        </label>
        <input
          ref={ref}
          id={id}
          type="password"
          autoComplete={autoComplete}
          autoFocus={autoFocus}
          value={value}
          aria-invalid={error !== null}
          aria-describedby={described || undefined}
          onChange={(event) => onChange(event.target.value)}
          className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-1 text-base shadow-sm ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        />
        {hint && (
          <p id={`${id}-hint`} className="text-sm text-muted-foreground">
            {hint}
          </p>
        )}
        {error && (
          <p
            id={`${id}-error`}
            role="alert"
            className="text-sm leading-relaxed text-danger"
          >
            {error}
          </p>
        )}
      </div>
    );
  },
);
PasswordField.displayName = "PasswordField";
