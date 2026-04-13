import { FormEvent, useEffect, useState } from "react";
import type { AccountRow, AuditLogRow, SystemSettings, UserRole } from "../types";

type RequestJson = <T>(path: string, init?: RequestInit) => Promise<T>;
type SettingsTab = "system" | "accounts" | "audit";

type SettingsPanelProps = {
  requestJson: RequestJson;
};

const emptyAccountForm = {
  username: "",
  display_name: "",
  email: "",
  password: "",
  role: "staff" as UserRole
};

const formatDate = (value: string | null) => {
  if (!value) return "--";
  return new Intl.DateTimeFormat("en-PH", {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit"
  }).format(new Date(value));
};

export const SettingsPanel = ({ requestJson }: SettingsPanelProps) => {
  const [activeSettingsTab, setActiveSettingsTab] = useState<SettingsTab>("system");
  const [systemSettings, setSystemSettings] = useState<SystemSettings | null>(null);
  const [accounts, setAccounts] = useState<AccountRow[]>([]);
  const [auditLogs, setAuditLogs] = useState<AuditLogRow[]>([]);
  const [accountForm, setAccountForm] = useState(emptyAccountForm);
  const [settingsMessage, setSettingsMessage] = useState<string | null>(null);
  const [settingsError, setSettingsError] = useState<string | null>(null);
  const [isLoadingSettings, setIsLoadingSettings] = useState<boolean>(true);
  const [isCreatingAccount, setIsCreatingAccount] = useState<boolean>(false);

  const loadSettings = async () => {
    setIsLoadingSettings(true);
    setSettingsError(null);
    const [systemResult, accountsResult, auditLogsResult] = await Promise.allSettled([
      requestJson<SystemSettings>("/settings/system"),
      requestJson<AccountRow[]>("/settings/accounts"),
      requestJson<AuditLogRow[]>("/settings/audit-logs")
    ]);

    if (systemResult.status === "fulfilled") setSystemSettings(systemResult.value);
    if (accountsResult.status === "fulfilled") setAccounts(accountsResult.value);
    if (auditLogsResult.status === "fulfilled") setAuditLogs(auditLogsResult.value);

    const failedResult = [systemResult, accountsResult, auditLogsResult].find((result) => result.status === "rejected");
    if (failedResult?.status === "rejected") {
      setSettingsError(`Unable to load settings: ${String(failedResult.reason)}`);
    }
    setIsLoadingSettings(false);
  };

  useEffect(() => {
    void loadSettings();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const onCreateAccount = async (event: FormEvent) => {
    event.preventDefault();
    setSettingsMessage(null);
    setSettingsError(null);
    setIsCreatingAccount(true);
    try {
      await requestJson<AccountRow>("/settings/accounts", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          ...accountForm,
          email: accountForm.email.trim() || null
        })
      });
      setAccountForm(emptyAccountForm);
      setSettingsMessage("Account created.");
      await loadSettings();
    } catch (error) {
      setSettingsError(`Create account failed: ${String(error)}`);
    } finally {
      setIsCreatingAccount(false);
    }
  };

  const onDeactivateAccount = async (account: AccountRow) => {
    setSettingsMessage(null);
    setSettingsError(null);
    try {
      await requestJson<AccountRow>(`/settings/accounts/${account.id}`, { method: "DELETE" });
      setSettingsMessage(`${account.display_name} deactivated.`);
      await loadSettings();
    } catch (error) {
      setSettingsError(`Deactivate account failed: ${String(error)}`);
    }
  };

  return (
    <section className="settings-page" aria-labelledby="settings-title">
      <div className="settings-head">
        <div>
          <h2 id="settings-title">Settings</h2>
          <p>Configure system settings and manage users</p>
        </div>
        <button className="secondary-btn" onClick={() => void loadSettings()}>
          Refresh Settings
        </button>
      </div>

      <div className="settings-tab-group" aria-label="Settings sections">
        <button
          className={activeSettingsTab === "system" ? "settings-tab active" : "settings-tab"}
          onClick={() => setActiveSettingsTab("system")}
        >
          System
        </button>
        <button
          className={activeSettingsTab === "accounts" ? "settings-tab active" : "settings-tab"}
          onClick={() => setActiveSettingsTab("accounts")}
        >
          Accounts
        </button>
        <button
          className={activeSettingsTab === "audit" ? "settings-tab active" : "settings-tab"}
          onClick={() => setActiveSettingsTab("audit")}
        >
          Audit Logs
        </button>
      </div>

      {settingsError ? <p className="status status-error">{settingsError}</p> : null}
      {settingsMessage ? <p className="status">{settingsMessage}</p> : null}
      {isLoadingSettings ? <p className="status">Loading settings...</p> : null}

      {activeSettingsTab === "system" ? (
        <section className="settings-grid">
          <article className="settings-stat">
            <p className="kpi-label">Authentication</p>
            <p className="settings-stat-value">{systemSettings?.auth_enabled ? "Enabled" : "Disabled"}</p>
            <p className="meta">Configured: {systemSettings?.configured ? "yes" : "no"}</p>
          </article>
          <article className="settings-stat">
            <p className="kpi-label">Active Accounts</p>
            <p className="settings-stat-value">{systemSettings?.active_accounts ?? 0}</p>
            <p className="meta">
              Admin {systemSettings?.admin_accounts ?? 0} / Staff {systemSettings?.staff_accounts ?? 0}
            </p>
          </article>
          <article className="settings-stat">
            <p className="kpi-label">Session Policy</p>
            <p className="settings-stat-value">{Math.round((systemSettings?.session_ttl_seconds ?? 0) / 3600)}h</p>
            <p className="meta">Staff can use inventory tools. Admin can manage settings.</p>
          </article>
        </section>
      ) : null}

      {activeSettingsTab === "accounts" ? (
        <section className="settings-layout">
          <section className="panel settings-form-panel">
            <h3>Create Account</h3>
            <form className="form-grid" onSubmit={onCreateAccount}>
              <label>
                Username
                <input
                  value={accountForm.username}
                  onChange={(event) => setAccountForm((prev) => ({ ...prev, username: event.target.value }))}
                  required
                />
              </label>
              <label>
                Display name
                <input
                  value={accountForm.display_name}
                  onChange={(event) => setAccountForm((prev) => ({ ...prev, display_name: event.target.value }))}
                  required
                />
              </label>
              <label>
                Email
                <input
                  type="email"
                  value={accountForm.email}
                  onChange={(event) => setAccountForm((prev) => ({ ...prev, email: event.target.value }))}
                />
              </label>
              <label>
                Password
                <input
                  type="password"
                  value={accountForm.password}
                  onChange={(event) => setAccountForm((prev) => ({ ...prev, password: event.target.value }))}
                  minLength={8}
                  required
                />
              </label>
              <label>
                Role
                <select
                  value={accountForm.role}
                  onChange={(event) => setAccountForm((prev) => ({ ...prev, role: event.target.value as UserRole }))}
                >
                  <option value="staff">staff</option>
                  <option value="admin">admin</option>
                </select>
              </label>
              <button className="primary-btn" type="submit" disabled={isCreatingAccount}>
                {isCreatingAccount ? "Creating..." : "Create Account"}
              </button>
            </form>
          </section>

          <section className="panel settings-table-panel">
            <div className="panel-head">
              <h3>User Accounts</h3>
            </div>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Name</th>
                    <th>Email</th>
                    <th>Role</th>
                    <th>Status</th>
                    <th>Created</th>
                    <th>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {accounts.length === 0 ? (
                    <tr>
                      <td colSpan={6}>No accounts found.</td>
                    </tr>
                  ) : (
                    accounts.map((account) => (
                      <tr key={account.id}>
                        <td>
                          <strong>{account.display_name}</strong>
                          <span className="account-username">{account.username}</span>
                        </td>
                        <td>{account.email ?? "--"}</td>
                        <td>
                          <span className={`role-pill role-pill--${account.role}`}>{account.role}</span>
                        </td>
                        <td>
                          <span className={account.status === "active" ? "status-pill status-pill--healthy" : "status-pill"}>
                            {account.status}
                          </span>
                        </td>
                        <td>{formatDate(account.created_at)}</td>
                        <td>
                          <button
                            className="danger-link"
                            disabled={account.status !== "active"}
                            onClick={() => void onDeactivateAccount(account)}
                          >
                            Deactivate
                          </button>
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
            <p className="meta">Staff members can change their own passwords from their Profile page once profile tools are added.</p>
          </section>
        </section>
      ) : null}

      {activeSettingsTab === "audit" ? (
        <section className="panel settings-audit-panel">
          <div className="panel-head">
            <h3>Audit Logs</h3>
          </div>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Time</th>
                  <th>Actor</th>
                  <th>Action</th>
                  <th>Message</th>
                </tr>
              </thead>
              <tbody>
                {auditLogs.length === 0 ? (
                  <tr>
                    <td colSpan={4}>No audit logs recorded.</td>
                  </tr>
                ) : (
                  auditLogs.map((log) => (
                    <tr key={log.id}>
                      <td>{formatDate(log.created_at)}</td>
                      <td>{log.actor_username}</td>
                      <td>{log.action}</td>
                      <td>{log.message}</td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </section>
      ) : null}
    </section>
  );
};
