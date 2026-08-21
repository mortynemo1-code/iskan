import { FormEvent, useState } from "react";

export type UserInfo = {
  id: string;
  login: string;
  display_name: string;
  role: string;
  employee_id: string | null;
  scope_type: string;
  permissions: string[];
};

type AuthResponse = {
  status: "AUTHENTICATED" | "TOTP_REQUIRED" | "TOTP_SETUP_REQUIRED";
  user?: UserInfo;
  setup_token?: string;
  totp_secret?: string;
  totp_uri?: string;
};

async function post<T>(url: string, body: object): Promise<T> {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    let message = "Не удалось выполнить вход";
    try {
      const data = await response.json();
      if (typeof data.detail === "string") message = data.detail;
    } catch {
      // Keep the user-friendly fallback.
    }
    throw new Error(message);
  }
  return response.json() as Promise<T>;
}

export function LoginScreen({ onAuthenticated }: { onAuthenticated: (user: UserInfo) => void }) {
  const [login, setLogin] = useState("");
  const [password, setPassword] = useState("");
  const [totpCode, setTotpCode] = useState("");
  const [stage, setStage] = useState<"credentials" | "totp" | "setup">("credentials");
  const [setupToken, setSetupToken] = useState("");
  const [totpSecret, setTotpSecret] = useState("");
  const [totpUri, setTotpUri] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submitLogin = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const result = await post<AuthResponse>("/api/v1/auth/login", {
        login,
        password,
        totp_code: stage === "totp" ? totpCode : null,
      });
      if (result.status === "AUTHENTICATED" && result.user) {
        onAuthenticated(result.user);
      } else if (result.status === "TOTP_REQUIRED") {
        setStage("totp");
        setTotpCode("");
      } else if (result.status === "TOTP_SETUP_REQUIRED") {
        setStage("setup");
        setSetupToken(result.setup_token ?? "");
        setTotpSecret(result.totp_secret ?? "");
        setTotpUri(result.totp_uri ?? "");
        setTotpCode("");
      }
    } catch (submitError) {
      setError(submitError instanceof Error ? submitError.message : "Не удалось выполнить вход");
    } finally {
      setBusy(false);
    }
  };

  const confirmSetup = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const result = await post<AuthResponse>("/api/v1/auth/totp/confirm", {
        setup_token: setupToken,
        code: totpCode,
      });
      if (result.user) onAuthenticated(result.user);
    } catch (submitError) {
      setError(submitError instanceof Error ? submitError.message : "Не удалось подтвердить 2FA");
    } finally {
      setBusy(false);
    }
  };

  return (
    <main className="login-page">
      <section className="login-brand">
        <p className="eyebrow">Workforce Monitoring</p>
        <h1>Рабочий день<br />виден целиком.</h1>
        <p>Онлайн-присутствие, активность и отчётность команды — в защищённом внутреннем контуре.</p>
        <div className="security-note"><i /> Данные доступны только в рамках вашей роли</div>
      </section>

      <section className="login-card">
        {stage === "setup" ? (
          <>
            <p className="eyebrow">Защита аккаунта</p>
            <h2>Подключите 2FA</h2>
            <p className="login-help">Добавьте секрет в приложение-аутентификатор и введите текущий шестизначный код.</p>
            <div className="totp-secret">
              <span>Секрет TOTP</span>
              <code>{totpSecret}</code>
              <a href={totpUri}>Открыть в аутентификаторе</a>
            </div>
            <form className="login-form" onSubmit={confirmSetup}>
              <label><span>Одноразовый код</span><input inputMode="numeric" autoComplete="one-time-code" value={totpCode} onChange={(event) => setTotpCode(event.target.value.replace(/\D/g, "").slice(0, 6))} placeholder="000000" required pattern="\d{6}" autoFocus /></label>
              {error && <div className="login-error">{error}</div>}
              <button className="login-button" disabled={busy}>{busy ? "Проверяем…" : "Подтвердить и войти"}</button>
            </form>
          </>
        ) : (
          <>
            <p className="eyebrow">Внутренний портал</p>
            <h2>{stage === "totp" ? "Подтвердите вход" : "Вход в систему"}</h2>
            <p className="login-help">{stage === "totp" ? `Введите код для ${login}` : "Используйте выданные администратором данные."}</p>
            <form className="login-form" onSubmit={submitLogin}>
              {stage === "credentials" ? (
                <>
                  <label><span>Логин</span><input autoComplete="username" value={login} onChange={(event) => setLogin(event.target.value)} placeholder="name@company.ru" required autoFocus /></label>
                  <label><span>Пароль</span><input type="password" autoComplete="current-password" value={password} onChange={(event) => setPassword(event.target.value)} placeholder="Не менее 12 символов" required /></label>
                </>
              ) : (
                <label><span>Одноразовый код</span><input inputMode="numeric" autoComplete="one-time-code" value={totpCode} onChange={(event) => setTotpCode(event.target.value.replace(/\D/g, "").slice(0, 6))} placeholder="000000" required pattern="\d{6}" autoFocus /></label>
              )}
              {error && <div className="login-error">{error}</div>}
              <button className="login-button" disabled={busy}>{busy ? "Проверяем…" : stage === "totp" ? "Подтвердить" : "Войти"}</button>
              {stage === "totp" && <button type="button" className="back-button" onClick={() => { setStage("credentials"); setError(null); }}>Назад к логину</button>}
            </form>
          </>
        )}
      </section>
    </main>
  );
}
