"use client";

import { useEffect, useMemo, useState } from "react";
import {
  createUser,
  deactivateUser,
  fetchUsers,
  updateUser,
} from "@/lib/api";
import { isAdmin } from "@/lib/auth";
import type { DashboardUser, UserRole } from "@/types";
import Badge from "@/components/ui/Badge";

const ROLES: UserRole[] = ["admin", "da", "expert"];

function roleVariant(role: UserRole): "success" | "warning" | "info" | "neutral" {
  if (role === "admin") return "success";
  if (role === "da") return "warning";
  if (role === "expert") return "info";
  return "neutral";
}

export default function UsersPage() {
  const admin = typeof window !== "undefined" ? isAdmin() : false;

  const [users, setUsers] = useState<DashboardUser[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [toast, setToast] = useState("");

  const [search, setSearch] = useState("");
  const [selected, setSelected] = useState<DashboardUser | null>(null);

  // Create form
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState<UserRole>("da");
  const [saving, setSaving] = useState(false);

  // Edit form
  const [editRole, setEditRole] = useState<UserRole>("da");
  const [editActive, setEditActive] = useState(true);
  const [editFullName, setEditFullName] = useState("");
  const [editPassword, setEditPassword] = useState("");
  const [updating, setUpdating] = useState(false);

  const showToast = (msg: string) => {
    setToast(msg);
    setTimeout(() => setToast(""), 3000);
  };

  const load = () => {
    setLoading(true);
    setError("");
    fetchUsers()
      .then((data) => {
        setUsers(data);
        if (selected) {
          const next = data.find((u) => u.user_id === selected.user_id) ?? null;
          setSelected(next);
        }
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    if (!admin) return;
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [admin]);

  useEffect(() => {
    if (!selected) return;
    setEditRole(selected.role);
    setEditActive(selected.is_active);
    setEditFullName(selected.full_name);
    setEditPassword("");
  }, [selected]);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return users;
    return users.filter((u) => {
      return (
        u.email.toLowerCase().includes(q) ||
        u.full_name.toLowerCase().includes(q) ||
        u.role.toLowerCase().includes(q)
      );
    });
  }, [users, search]);

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!fullName.trim() || !email.trim() || !password) return;
    setSaving(true);
    try {
      await createUser({
        full_name: fullName.trim(),
        email: email.trim(),
        password,
        role,
        is_active: true,
      });
      setFullName("");
      setEmail("");
      setPassword("");
      setRole("da");
      showToast("User created ✓");
      load();
    } catch (e) {
      showToast(e instanceof Error ? e.message : "Create failed");
    } finally {
      setSaving(false);
    }
  };

  const handleUpdate = async () => {
    if (!selected) return;
    setUpdating(true);
    try {
      await updateUser(selected.user_id, {
        full_name: editFullName.trim(),
        role: editRole,
        is_active: editActive,
        password: editPassword.trim() ? editPassword : undefined,
      });
      showToast("User updated ✓");
      load();
    } catch (e) {
      showToast(e instanceof Error ? e.message : "Update failed");
    } finally {
      setUpdating(false);
    }
  };

  const handleDeactivate = async () => {
    if (!selected) return;
    setUpdating(true);
    try {
      await deactivateUser(selected.user_id);
      showToast("User deactivated ✓");
      load();
    } catch (e) {
      showToast(e instanceof Error ? e.message : "Deactivate failed");
    } finally {
      setUpdating(false);
    }
  };

  if (!admin) {
    return (
      <div className="mt-8 bg-blue-50 border border-blue-200 rounded-xl p-6">
        <p className="text-sm font-medium text-blue-700">
          Read-only — only admins can manage dashboard users.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-8">
      {toast && (
        <div className="fixed top-4 right-4 z-50 bg-slate-900 text-white text-sm font-medium px-4 py-2.5 rounded-lg shadow-lg">
          {toast}
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-12 gap-8 mt-8">
        {/* Create user */}
        <div className="lg:col-span-4">
          <div className="bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden">
            <div className="px-8 py-6 border-b border-slate-100">
              <h3 className="text-base font-medium text-slate-800">
                Create Dashboard User
              </h3>
              <p className="text-sm text-slate-500 mt-1">
                Add admins, DAs, or experts.
              </p>
            </div>
            <form onSubmit={handleCreate} className="p-8 space-y-4">
              <div className="space-y-1.5">
                <label className="text-sm font-medium text-slate-700">
                  Full name
                </label>
                <input
                  value={fullName}
                  onChange={(e) => setFullName(e.target.value)}
                  className="w-full h-10 px-3 rounded-md border border-slate-300 text-sm focus:outline-none focus:ring-2 focus:ring-green-500 focus:border-green-500"
                  placeholder="Jane Doe"
                  required
                />
              </div>
              <div className="space-y-1.5">
                <label className="text-sm font-medium text-slate-700">
                  Email
                </label>
                <input
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  className="w-full h-10 px-3 rounded-md border border-slate-300 text-sm focus:outline-none focus:ring-2 focus:ring-green-500 focus:border-green-500"
                  placeholder="user@example.com"
                  type="email"
                  required
                />
              </div>
              <div className="space-y-1.5">
                <label className="text-sm font-medium text-slate-700">
                  Password
                </label>
                <input
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  className="w-full h-10 px-3 rounded-md border border-slate-300 text-sm focus:outline-none focus:ring-2 focus:ring-green-500 focus:border-green-500"
                  type="password"
                  required
                />
              </div>
              <div className="space-y-1.5">
                <label className="text-sm font-medium text-slate-700">
                  Role
                </label>
                <select
                  value={role}
                  onChange={(e) => setRole(e.target.value as UserRole)}
                  className="w-full h-10 px-3 rounded-md border border-slate-300 text-sm focus:outline-none focus:ring-2 focus:ring-green-500 focus:border-green-500 bg-white"
                >
                  {ROLES.map((r) => (
                    <option key={r} value={r}>
                      {r.toUpperCase()}
                    </option>
                  ))}
                </select>
              </div>

              <button
                type="submit"
                disabled={saving}
                className="w-full h-10 bg-slate-900 hover:bg-slate-800 disabled:opacity-50 text-white text-sm font-medium rounded-md transition-colors"
              >
                {saving ? "Creating…" : "Create user"}
              </button>
            </form>
          </div>
        </div>

        {/* List + details */}
        <div className="lg:col-span-8 space-y-8">
          <div className="bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden">
            <div className="px-8 py-6 border-b border-slate-100 flex flex-col sm:flex-row gap-4 sm:items-center sm:justify-between">
              <h3 className="text-base font-medium text-slate-800">
                Users
                {!loading && (
                  <span className="ml-2 text-sm font-normal text-slate-400">
                    ({users.length})
                  </span>
                )}
              </h3>
              <input
                type="search"
                placeholder="Search by name, email, role…"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                className="px-3 py-1.5 rounded-md border border-slate-200 text-sm text-slate-700 w-full sm:w-64 focus:outline-none focus:ring-2 focus:ring-green-500 focus:border-green-500"
              />
            </div>

            {loading && (
              <div className="p-8 space-y-3 animate-pulse">
                {[1, 2, 3, 4].map((i) => (
                  <div key={i} className="h-10 bg-slate-100 rounded-md" />
                ))}
              </div>
            )}

            {error && (
              <div className="m-8 bg-red-50 border border-red-200 rounded-lg p-4">
                <p className="text-sm text-red-700">{error}</p>
              </div>
            )}

            {!loading && !error && (
              <div className="overflow-x-auto">
                <table className="w-full text-left">
                  <thead>
                    <tr className="border-b border-slate-100">
                      <th className="py-4 px-8 text-xs font-semibold text-slate-500 uppercase tracking-wide">
                        Name
                      </th>
                      <th className="py-4 px-8 text-xs font-semibold text-slate-500 uppercase tracking-wide">
                        Email
                      </th>
                      <th className="py-4 px-8 text-xs font-semibold text-slate-500 uppercase tracking-wide">
                        Role
                      </th>
                      <th className="py-4 px-8 text-xs font-semibold text-slate-500 uppercase tracking-wide">
                        Status
                      </th>
                      <th className="py-4 px-8 text-xs font-semibold text-slate-500 uppercase tracking-wide text-right">
                        Action
                      </th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {filtered.length > 0 ? (
                      filtered.map((u) => (
                        <tr
                          key={u.user_id}
                          className={`hover:bg-slate-50 transition-colors cursor-pointer ${
                            selected?.user_id === u.user_id ? "bg-slate-50" : ""
                          }`}
                          onClick={() => setSelected(u)}
                        >
                          <td className="py-4 px-8 text-sm font-medium text-slate-900">
                            {u.full_name}
                          </td>
                          <td className="py-4 px-8 text-sm text-slate-600 font-mono">
                            {u.email}
                          </td>
                          <td className="py-4 px-8">
                            <Badge
                              label={u.role.toUpperCase()}
                              variant={roleVariant(u.role)}
                            />
                          </td>
                          <td className="py-4 px-8">
                            <Badge
                              label={u.is_active ? "Active" : "Disabled"}
                              variant={u.is_active ? "success" : "danger"}
                            />
                          </td>
                          <td className="py-4 px-8 text-right">
                            <button className="text-sm font-medium text-blue-600 hover:text-blue-700">
                              Edit
                            </button>
                          </td>
                        </tr>
                      ))
                    ) : (
                      <tr>
                        <td
                          colSpan={5}
                          className="py-16 text-center text-sm text-slate-400"
                        >
                          No users match your search.
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          {/* Detail editor */}
          <div className="bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden">
            <div className="px-8 py-6 border-b border-slate-100">
              <h3 className="text-base font-medium text-slate-800">
                {selected ? `Edit: ${selected.full_name}` : "Select a user"}
              </h3>
              <p className="text-sm text-slate-500 mt-1">
                {selected
                  ? selected.email
                  : "Click a row above to edit role, status, or reset password."}
              </p>
            </div>

            {!selected ? (
              <div className="p-10 text-center text-sm text-slate-400">
                No user selected.
              </div>
            ) : (
              <div className="p-8 grid grid-cols-1 md:grid-cols-2 gap-4">
                <div className="space-y-1.5">
                  <label className="text-sm font-medium text-slate-700">
                    Full name
                  </label>
                  <input
                    value={editFullName}
                    onChange={(e) => setEditFullName(e.target.value)}
                    className="w-full h-10 px-3 rounded-md border border-slate-300 text-sm focus:outline-none focus:ring-2 focus:ring-green-500 focus:border-green-500"
                  />
                </div>

                <div className="space-y-1.5">
                  <label className="text-sm font-medium text-slate-700">
                    Role
                  </label>
                  <select
                    value={editRole}
                    onChange={(e) => setEditRole(e.target.value as UserRole)}
                    className="w-full h-10 px-3 rounded-md border border-slate-300 text-sm focus:outline-none focus:ring-2 focus:ring-green-500 focus:border-green-500 bg-white"
                  >
                    {ROLES.map((r) => (
                      <option key={r} value={r}>
                        {r.toUpperCase()}
                      </option>
                    ))}
                  </select>
                </div>

                <div className="space-y-1.5">
                  <label className="text-sm font-medium text-slate-700">
                    Status
                  </label>
                  <select
                    value={editActive ? "active" : "disabled"}
                    onChange={(e) => setEditActive(e.target.value === "active")}
                    className="w-full h-10 px-3 rounded-md border border-slate-300 text-sm focus:outline-none focus:ring-2 focus:ring-green-500 focus:border-green-500 bg-white"
                  >
                    <option value="active">Active</option>
                    <option value="disabled">Disabled</option>
                  </select>
                </div>

                <div className="space-y-1.5">
                  <label className="text-sm font-medium text-slate-700">
                    Reset password (optional)
                  </label>
                  <input
                    value={editPassword}
                    onChange={(e) => setEditPassword(e.target.value)}
                    className="w-full h-10 px-3 rounded-md border border-slate-300 text-sm focus:outline-none focus:ring-2 focus:ring-green-500 focus:border-green-500"
                    type="password"
                    placeholder="Leave blank to keep unchanged"
                  />
                </div>

                <div className="md:col-span-2 flex flex-col sm:flex-row gap-3 pt-2">
                  <button
                    onClick={handleUpdate}
                    disabled={updating}
                    className="h-10 px-6 bg-slate-900 hover:bg-slate-800 disabled:opacity-50 text-white text-sm font-medium rounded-md transition-colors"
                  >
                    {updating ? "Saving…" : "Save changes"}
                  </button>
                  <button
                    onClick={handleDeactivate}
                    disabled={updating}
                    className="h-10 px-6 bg-red-600 hover:bg-red-700 disabled:opacity-50 text-white text-sm font-medium rounded-md transition-colors"
                  >
                    Deactivate user
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

