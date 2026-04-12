import { FormEvent, useState } from "react";

type AdminLoginProps = {
  apiBaseUrl: string;
  error: string | null;
  isChecking: boolean;
  isSubmitting: boolean;
  onSubmit: (username: string, password: string) => Promise<void>;
};

export const AdminLogin = ({ apiBaseUrl, error, isChecking, isSubmitting, onSubmit }: AdminLoginProps) => {
  const [username, setUsername] = useState("admin");
  const [password, setPassword] = useState("");

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault();
    await onSubmit(username, password);
  };

  return (
    <main className="auth-shell">
      <section className="auth-panel" aria-labelledby="admin-login-title">
        <p className="kicker">Stock Sage</p>
        <h1 id="admin-login-title">Admin access</h1>
        <p className="auth-copy">Sign in before opening inventory operations.</p>

        <form className="auth-form" onSubmit={handleSubmit}>
          <label>
            Username
            <input
              autoComplete="username"
              disabled={isChecking || isSubmitting}
              onChange={(event) => setUsername(event.target.value)}
              required
              value={username}
            />
          </label>
          <label>
            Password
            <input
              autoComplete="current-password"
              disabled={isChecking || isSubmitting}
              onChange={(event) => setPassword(event.target.value)}
              required
              type="password"
              value={password}
            />
          </label>
          <button className="primary-btn auth-submit" disabled={isChecking || isSubmitting} type="submit">
            {isChecking ? "Checking session..." : isSubmitting ? "Signing in..." : "Sign in"}
          </button>
        </form>

        {error ? (
          <p className="status status-error auth-status" role="alert">
            {error}
          </p>
        ) : null}
        <p className="meta auth-api">API: {apiBaseUrl}</p>
      </section>
    </main>
  );
};
