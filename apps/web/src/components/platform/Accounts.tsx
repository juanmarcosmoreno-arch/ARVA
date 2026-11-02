import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { KeyRound, LogOut, ShieldCheck, UserPlus, Users } from "lucide-react";
import { useState, type FormEvent, type ReactNode } from "react";
import { ArvaMark } from "@/components/brand/ArvaLogo";
import { Explain } from "@/components/guide/Explain";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Field, Input, Select } from "@/components/ui/form";
import { ErrorNote } from "@/components/ui/misc";
import { useT, type TranslationKey } from "@/i18n";
import { fmtDate } from "@/lib/format";
import { platformApi, type Role } from "@/lib/platform";

const ROLES: Role[] = ["admin", "analyst", "viewer"];

export function useAuthStatus() {
  return useQuery({ queryKey: ["authStatus"], queryFn: platformApi.authStatus, staleTime: 60_000, retry: false });
}

/** With accounts on, the interface is shown only to a signed-in user; with them off (the default) it is unchanged. */
export function AuthGate({ children }: { children: ReactNode }) {
  const status = useAuthStatus();
  if (status.isLoading || !status.data?.enabled || status.data.user) return <>{children}</>;
  return status.data.setup_required ? <SetupScreen tokenFile={status.data.setup_token_file ?? ""} /> : <LoginScreen />;
}

function Frame({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="flex min-h-[70vh] items-center justify-center">
      <Card className="w-full max-w-sm">
        <CardBody className="space-y-4 pt-6">
          <div className="flex items-center gap-2"><ArvaMark className="h-8 w-8" /><h1 className="text-lg font-semibold">{title}</h1></div>
          {children}
        </CardBody>
      </Card>
    </div>
  );
}

function LoginScreen() {
  const t = useT();
  const qc = useQueryClient();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const login = useMutation({ mutationFn: () => platformApi.login(username, password), onSuccess: () => qc.invalidateQueries() });
  const submit = (e: FormEvent) => { e.preventDefault(); login.mutate(); };
  return (
    <Frame title={t("auth.signIn")}>
      <form className="space-y-3" onSubmit={submit}>
        <Field label={t("auth.username")}><Input autoComplete="username" value={username} onChange={(e) => setUsername(e.target.value)} /></Field>
        <Field label={t("auth.password")}><Input type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} /></Field>
        <ErrorNote error={login.error} />
        <Button type="submit" className="w-full" disabled={!username || !password || login.isPending}>{t("auth.signIn")}</Button>
      </form>
      <p className="text-[11px] text-muted-foreground">{t("auth.localNote")}</p>
    </Frame>
  );
}

function SetupScreen({ tokenFile }: { tokenFile: string }) {
  const t = useT();
  const qc = useQueryClient();
  const [form, setForm] = useState({ username: "", password: "", token: "" });
  const setup = useMutation({ mutationFn: () => platformApi.setup(form), onSuccess: () => qc.invalidateQueries() });
  return (
    <Frame title={t("auth.setupTitle")}>
      <p className="text-xs text-muted-foreground">{t("auth.setupHint", { file: tokenFile })}</p>
      <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); setup.mutate(); }}>
        <Field label={t("auth.setupToken")}><Input value={form.token} onChange={(e) => setForm({ ...form, token: e.target.value })} /></Field>
        <Field label={t("auth.username")}><Input autoComplete="username" value={form.username} onChange={(e) => setForm({ ...form, username: e.target.value })} /></Field>
        <Field label={t("auth.password")} hint={t("auth.passwordRule")}>
          <Input type="password" autoComplete="new-password" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} />
        </Field>
        <ErrorNote error={setup.error} />
        <Button type="submit" className="w-full" disabled={setup.isPending}>{t("auth.createAdmin")}</Button>
      </form>
    </Frame>
  );
}

/** The signed-in account in the header, with sign-out; nothing when accounts are off. */
export function UserMenu() {
  const t = useT();
  const qc = useQueryClient();
  const status = useAuthStatus();
  const logout = useMutation({ mutationFn: platformApi.logout, onSuccess: () => qc.invalidateQueries() });
  const user = status.data?.user;
  if (!status.data?.enabled || !user) return null;
  return (
    <div className="flex items-center gap-2 text-xs">
      <span className="hidden sm:inline">{user.display_name || user.username}</span>
      <Badge tone="teal">{t(`auth.role.${user.role}` as TranslationKey)}</Badge>
      <Button variant="ghost" size="icon" onClick={() => logout.mutate()} aria-label={t("auth.signOut")}><LogOut className="h-4 w-4" /></Button>
    </div>
  );
}

/** Settings → Accounts: own password; for administrators, the accounts and the access audit log. */
export function AccountsSection() {
  const t = useT();
  const status = useAuthStatus();
  if (!status.data) return null;
  if (!status.data.enabled) {
    return (
      <Card>
        <CardHeader title={t("auth.accounts")} action={<Explain id="accounts_access" compact />} />
        <CardBody className="flex gap-2 text-xs text-muted-foreground">
          <ShieldCheck className="h-4 w-4 shrink-0 text-arva-teal" />{t("auth.offHint")}
        </CardBody>
      </Card>
    );
  }
  const admin = status.data.user?.role === "admin";
  return (
    <>
      <PasswordCard />
      {admin && <UsersCard />}
      {admin && <AuditCard />}
    </>
  );
}

function PasswordCard() {
  const t = useT();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const change = useMutation({ mutationFn: () => platformApi.changePassword(current, next), onSuccess: () => { setCurrent(""); setNext(""); } });
  return (
    <Card>
      <CardHeader title={t("auth.myPassword")} description={t("auth.myPasswordHint")} action={<Explain id="accounts_access" compact />} />
      <CardBody className="space-y-3">
        <Field label={t("auth.currentPassword")}><Input type="password" autoComplete="current-password" value={current} onChange={(e) => setCurrent(e.target.value)} /></Field>
        <Field label={t("auth.newPassword")} hint={t("auth.passwordRule")}><Input type="password" autoComplete="new-password" value={next} onChange={(e) => setNext(e.target.value)} /></Field>
        <ErrorNote error={change.error} />
        {change.isSuccess && <p className="text-xs text-success">{t("auth.passwordChanged")}</p>}
        <Button size="sm" disabled={!current || !next || change.isPending} onClick={() => change.mutate()}><KeyRound className="h-4 w-4" />{t("auth.changePassword")}</Button>
      </CardBody>
    </Card>
  );
}

function UsersCard() {
  const t = useT();
  const qc = useQueryClient();
  const users = useQuery({ queryKey: ["users"], queryFn: platformApi.users });
  const [form, setForm] = useState({ username: "", password: "", role: "analyst" as Role });
  const create = useMutation({ mutationFn: () => platformApi.createUser(form),
    onSuccess: () => { setForm({ username: "", password: "", role: "analyst" }); qc.invalidateQueries({ queryKey: ["users"] }); } });
  const update = useMutation({ mutationFn: ({ id, body }: { id: string; body: { role?: Role; is_active?: boolean } }) => platformApi.updateUser(id, body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["users"] }) });
  return (
    <Card className="lg:col-span-2">
      <CardHeader title={<span className="flex items-center gap-2"><Users className="h-4 w-4" />{t("auth.users")}</span>} description={t("auth.usersHint")} />
      <CardBody className="space-y-4 text-xs">
        <table className="w-full">
          <thead><tr className="text-left text-muted-foreground"><th className="py-1">{t("auth.username")}</th><th>{t("auth.role")}</th><th>{t("auth.lastLogin")}</th><th>{t("auth.active")}</th></tr></thead>
          <tbody>
            {users.data?.map((u) => (
              <tr key={u.id} className="border-t">
                <td className="py-1.5">{u.username}{u.locked && <Badge tone="warning" className="ml-2">{t("auth.locked")}</Badge>}</td>
                <td>
                  <Select className="h-7 w-32" value={u.role} onChange={(e) => update.mutate({ id: u.id, body: { role: e.target.value as Role } })}>
                    {ROLES.map((r) => <option key={r} value={r}>{t(`auth.role.${r}` as TranslationKey)}</option>)}
                  </Select>
                </td>
                <td>{u.last_login_at ? fmtDate(u.last_login_at) : "–"}</td>
                <td><input type="checkbox" className="accent-[#00B4A6]" checked={u.is_active} aria-label={t("auth.active")}
                  onChange={(e) => update.mutate({ id: u.id, body: { is_active: e.target.checked } })} /></td>
              </tr>
            ))}
          </tbody>
        </table>
        <ErrorNote error={update.error} />
        <div className="grid items-end gap-2 sm:grid-cols-4">
          <Field label={t("auth.username")}><Input value={form.username} onChange={(e) => setForm({ ...form, username: e.target.value })} /></Field>
          <Field label={t("auth.password")}><Input type="password" autoComplete="new-password" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} /></Field>
          <Field label={t("auth.role")}>
            <Select value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value as Role })}>
              {ROLES.map((r) => <option key={r} value={r}>{t(`auth.role.${r}` as TranslationKey)}</option>)}
            </Select>
          </Field>
          <Button size="sm" disabled={!form.username || !form.password || create.isPending} onClick={() => create.mutate()}><UserPlus className="h-4 w-4" />{t("auth.addUser")}</Button>
        </div>
        <ErrorNote error={create.error} />
        <p className="text-muted-foreground">{t("auth.rolesHint")}</p>
      </CardBody>
    </Card>
  );
}

function AuditCard() {
  const t = useT();
  const audit = useQuery({ queryKey: ["audit"], queryFn: () => platformApi.audit(100) });
  return (
    <Card className="lg:col-span-2">
      <CardHeader title={t("auth.audit")} description={t("auth.auditHint")} />
      <CardBody className="max-h-80 overflow-y-auto text-xs">
        <table className="w-full">
          <thead><tr className="text-left text-muted-foreground"><th className="py-1">{t("auth.when")}</th><th>{t("auth.username")}</th><th>{t("auth.action")}</th><th>{t("auth.outcome")}</th><th>{t("auth.route")}</th></tr></thead>
          <tbody>
            {audit.data?.map((e) => (
              <tr key={e.id} className="border-t">
                <td className="py-1">{fmtDate(e.at)}</td><td>{e.username ?? "–"}</td><td>{e.action}</td>
                <td><Badge tone={e.outcome === "denied" ? "danger" : "success"}>{t(`auth.outcome.${e.outcome === "denied" ? "denied" : "allowed"}`)}</Badge></td>
                <td className="font-mono">{[e.method, e.route].filter(Boolean).join(" ")}{e.project_name ? ` · ${e.project_name}` : ""}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </CardBody>
    </Card>
  );
}

/** Project page: who owns the project and who it is shared with (only with accounts on). */
export function ProjectSharing({ projectId }: { projectId: string }) {
  const t = useT();
  const qc = useQueryClient();
  const status = useAuthStatus();
  const enabled = !!status.data?.enabled;
  const shares = useQuery({ queryKey: ["shares", projectId], queryFn: () => platformApi.shares(projectId), enabled });
  const directory = useQuery({ queryKey: ["directory"], queryFn: platformApi.directory, enabled });
  const [userId, setUserId] = useState("");
  const [access, setAccess] = useState<"read" | "write">("read");
  const share = useMutation({ mutationFn: ({ id, level }: { id: string; level: "read" | "write" | null }) => platformApi.share(projectId, id, level),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["shares", projectId] }) });
  if (!enabled || !shares.data) return null;
  const me = status.data?.user;
  const canShare = me?.role === "admin" || shares.data.owner?.id === me?.id;
  return (
    <Card className="mt-6">
      <CardHeader title={t("share.title")} description={t("share.owner", { owner: shares.data.owner?.username ?? t("share.noOwner") })}
        action={<Explain id="accounts_access" compact />} />
      <CardBody className="space-y-3 text-xs">
        {shares.data.shares.length ? shares.data.shares.map((s) => (
          <div key={s.user.id} className="flex items-center gap-3">
            <span className="w-40">{s.user.username}</span>
            <Badge tone={s.access === "write" ? "teal" : "neutral"}>{t(`share.access.${s.access}`)}</Badge>
            {canShare && <Button size="sm" variant="ghost" onClick={() => share.mutate({ id: s.user.id, level: null })}>{t("share.remove")}</Button>}
          </div>
        )) : <p className="text-muted-foreground">{t("share.none")}</p>}
        {canShare && (
          <div className="flex flex-wrap items-end gap-2">
            <Field label={t("auth.username")} className="w-48">
              <Select value={userId} onChange={(e) => setUserId(e.target.value)}>
                <option value="">—</option>
                {directory.data?.filter((u) => u.id !== shares.data?.owner?.id).map((u) => <option key={u.id} value={u.id}>{u.username}</option>)}
              </Select>
            </Field>
            <Field label={t("share.accessLabel")} className="w-36">
              <Select value={access} onChange={(e) => setAccess(e.target.value as "read" | "write")}>
                <option value="read">{t("share.access.read")}</option>
                <option value="write">{t("share.access.write")}</option>
              </Select>
            </Field>
            <Button size="sm" disabled={!userId || share.isPending} onClick={() => share.mutate({ id: userId, level: access })}>{t("share.add")}</Button>
          </div>
        )}
        <ErrorNote error={share.error} />
      </CardBody>
    </Card>
  );
}
