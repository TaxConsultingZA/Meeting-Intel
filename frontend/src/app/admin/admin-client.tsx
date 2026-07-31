"use client";
import { useState } from "react";
import { UserPlus, Trash2, Shield, ShieldOff, Pencil } from "lucide-react";
import { registerUser, removeUser, updateUser } from "@/lib/api";
import type { RegisteredUser, BusinessUnit } from "@/lib/types";

interface Props {
  initialUsers: RegisteredUser[];
  businessUnits: BusinessUnit[];
  callerUpn: string;
  accessToken: string;
}

export default function AdminClient({ initialUsers, businessUnits, callerUpn, accessToken }: Props) {
  const [users, setUsers] = useState<RegisteredUser[]>(initialUsers);
  const [showAdd, setShowAdd] = useState(false);
  const [editUser, setEditUser] = useState<RegisteredUser | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function handleAdd(form: AddUserForm) {
    setError(null);
    try {
      const created = await registerUser(
        form.upn,
        {
          upn: form.upn,
          display_name: form.display_name || undefined,
          business_unit_id: form.business_unit_id ?? undefined,
          is_admin: form.is_admin,
        },
        accessToken,
      );
      setUsers((prev) => [...prev, created]);
      setShowAdd(false);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to register user");
    }
  }

  async function handleUpdate(targetUpn: string, payload: { display_name?: string; business_unit_id?: number; is_admin?: boolean }) {
    setError(null);
    try {
      const updated = await updateUser(targetUpn, payload, accessToken);
      setUsers((prev) => prev.map((u) => (u.upn === targetUpn ? updated : u)));
      setEditUser(null);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to update user");
    }
  }

  async function handleRemove(targetUpn: string) {
    if (!confirm(`Remove ${targetUpn} from the platform?`)) return;
    setError(null);
    try {
      await removeUser(targetUpn, accessToken);
      setUsers((prev) => prev.filter((u) => u.upn !== targetUpn));
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to remove user");
    }
  }

  return (
    <main className="max-w-5xl mx-auto px-6 py-7">
      <div className="mb-6 flex items-start justify-between gap-4">
        <div>
          <h1 className="text-[22px] font-bold text-[#003366]">User Management</h1>
          <p className="text-[#6b7280] text-[13.5px] mt-0.5">
            Register colleagues and assign them to their business unit. Only registered users have their meetings processed.
          </p>
        </div>
        <button
          type="button"
          onClick={() => setShowAdd(true)}
          className="shrink-0 inline-flex items-center gap-2 bg-[#003366] hover:bg-[#0a4a8c] text-white text-[13px] font-semibold px-4 py-2 rounded-md transition-colors"
        >
          <UserPlus size={15} /> Register User
        </button>
      </div>

      {error && (
        <div className="mb-4 bg-red-50 border border-red-200 text-red-700 text-[13px] px-4 py-3 rounded-lg">
          {error}
        </div>
      )}

      {/* Users table */}
      <div className="bg-white rounded-lg border border-[#dde1e8] shadow-sm overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr>
              {["Name / Email", "Business Unit", "Role", "Registered", "Actions"].map((h) => (
                <th key={h} className="bg-[#003366] text-white text-xs font-semibold px-4 py-2.5 text-left border border-white/10">
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {users.length === 0 && (
              <tr>
                <td colSpan={5} className="px-4 py-8 text-center text-[#9ca3af] text-[13px]">
                  No users registered yet. Add one using the button above.
                </td>
              </tr>
            )}
            {users.map((u, i) => (
              <tr key={u.upn} className={`${i % 2 === 1 ? "bg-[#f8fafc]" : ""} hover:bg-blue-50/30 transition-colors`}>
                <td className="px-4 py-2.5 border border-[#dde1e8]">
                  <div className="font-medium text-[#1a1a2e] text-[13px]">
                    {u.display_name ?? formatUpn(u.upn)}
                  </div>
                  <div className="text-[11.5px] text-[#6b7280]">{u.upn}</div>
                </td>
                <td className="px-4 py-2.5 border border-[#dde1e8] text-[#6b7280] text-[12.5px]">
                  {u.business_unit_name ?? <span className="text-[#d1d5db] italic">Unassigned</span>}
                </td>
                <td className="px-4 py-2.5 border border-[#dde1e8]">
                  {u.is_admin ? (
                    <span className="inline-flex items-center gap-1 text-[11.5px] font-semibold text-amber-700 bg-amber-50 px-2 py-0.5 rounded-full">
                      <Shield size={11} /> Admin
                    </span>
                  ) : (
                    <span className="text-[12px] text-[#6b7280]">Member</span>
                  )}
                </td>
                <td className="px-4 py-2.5 border border-[#dde1e8] text-[#6b7280] text-[12px] whitespace-nowrap">
                  {new Date(u.registered_at).toLocaleDateString("en-ZA", { day: "2-digit", month: "short", year: "numeric" })}
                </td>
                <td className="px-4 py-2.5 border border-[#dde1e8]">
                  <div className="flex items-center gap-2">
                    <button
                      type="button"
                      onClick={() => setEditUser(u)}
                      className="text-[#6b7280] hover:text-[#003366] transition-colors"
                      title="Edit"
                    >
                      <Pencil size={14} />
                    </button>
                    {u.upn !== callerUpn && (
                      <button
                        type="button"
                        onClick={() => handleRemove(u.upn)}
                        className="text-[#6b7280] hover:text-red-600 transition-colors"
                        title="Remove"
                      >
                        <Trash2 size={14} />
                      </button>
                    )}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Add User dialog */}
      {showAdd && (
        <AddUserDialog
          businessUnits={businessUnits}
          onSave={handleAdd}
          onClose={() => setShowAdd(false)}
        />
      )}

      {/* Edit User dialog */}
      {editUser && (
        <EditUserDialog
          user={editUser}
          businessUnits={businessUnits}
          onSave={(payload) => handleUpdate(editUser.upn, payload)}
          onClose={() => setEditUser(null)}
        />
      )}
    </main>
  );
}

function formatUpn(upn: string): string {
  return upn.split("@")[0].split(".").map((p) => p.charAt(0).toUpperCase() + p.slice(1)).join(" ");
}

interface AddUserForm {
  upn: string;
  display_name: string;
  business_unit_id: number | null;
  is_admin: boolean;
}

function AddUserDialog({
  businessUnits,
  onSave,
  onClose,
}: {
  businessUnits: BusinessUnit[];
  onSave: (form: AddUserForm) => void;
  onClose: () => void;
}) {
  const [form, setForm] = useState<AddUserForm>({ upn: "", display_name: "", business_unit_id: null, is_admin: false });

  return (
    <Dialog title="Register New User" onClose={onClose}>
      <div className="flex flex-col gap-4">
        <Field label="Work Email (@taxconsulting.co.za)" required>
          <input
            type="email"
            placeholder="firstname.lastname@taxconsulting.co.za"
            value={form.upn}
            onChange={(e) => setForm({ ...form, upn: e.target.value })}
            className="w-full border border-[#dde1e8] rounded-md px-3 py-2 text-[13px] focus:outline-none focus:ring-2 focus:ring-[#003366]"
          />
        </Field>
        <Field label="Display Name">
          <input
            type="text"
            placeholder="Full Name (optional)"
            value={form.display_name}
            onChange={(e) => setForm({ ...form, display_name: e.target.value })}
            className="w-full border border-[#dde1e8] rounded-md px-3 py-2 text-[13px] focus:outline-none focus:ring-2 focus:ring-[#003366]"
          />
        </Field>
        <Field label="Business Unit" required>
          <select
            value={form.business_unit_id ?? ""}
            onChange={(e) => setForm({ ...form, business_unit_id: e.target.value ? Number(e.target.value) : null })}
            className="w-full border border-[#dde1e8] rounded-md px-3 py-2 text-[13px] focus:outline-none focus:ring-2 focus:ring-[#003366]"
          >
            <option value="">Select business unit...</option>
            {businessUnits.map((bu) => (
              <option key={bu.id} value={bu.id}>{bu.name}</option>
            ))}
          </select>
        </Field>
        <label className="flex items-center gap-2 text-[13px] text-[#374151] cursor-pointer">
          <input
            type="checkbox"
            checked={form.is_admin}
            onChange={(e) => setForm({ ...form, is_admin: e.target.checked })}
            className="rounded border-[#dde1e8]"
          />
          Grant admin access (can manage users)
        </label>
        <div className="flex justify-end gap-2 mt-2">
          <button type="button" onClick={onClose} className="px-4 py-2 text-[13px] text-[#6b7280] hover:text-[#1a1a2e]">Cancel</button>
          <button
            type="button"
            onClick={() => onSave(form)}
            disabled={!form.upn || !form.business_unit_id}
            className="px-4 py-2 text-[13px] font-semibold bg-[#003366] text-white rounded-md hover:bg-[#0a4a8c] disabled:opacity-50 disabled:cursor-not-allowed"
          >
            Register
          </button>
        </div>
      </div>
    </Dialog>
  );
}

function EditUserDialog({
  user,
  businessUnits,
  onSave,
  onClose,
}: {
  user: RegisteredUser;
  businessUnits: BusinessUnit[];
  onSave: (payload: { display_name?: string; business_unit_id?: number; is_admin?: boolean }) => void;
  onClose: () => void;
}) {
  const [displayName, setDisplayName] = useState(user.display_name ?? "");
  const [buId, setBuId] = useState<number | null>(user.business_unit_id);
  const [isAdmin, setIsAdmin] = useState(user.is_admin);

  return (
    <Dialog title={`Edit — ${user.display_name ?? user.upn}`} onClose={onClose}>
      <div className="flex flex-col gap-4">
        <Field label="Display Name">
          <input
            type="text"
            value={displayName}
            onChange={(e) => setDisplayName(e.target.value)}
            className="w-full border border-[#dde1e8] rounded-md px-3 py-2 text-[13px] focus:outline-none focus:ring-2 focus:ring-[#003366]"
          />
        </Field>
        <Field label="Business Unit">
          <select
            value={buId ?? ""}
            onChange={(e) => setBuId(e.target.value ? Number(e.target.value) : null)}
            className="w-full border border-[#dde1e8] rounded-md px-3 py-2 text-[13px] focus:outline-none focus:ring-2 focus:ring-[#003366]"
          >
            <option value="">Select business unit...</option>
            {businessUnits.map((bu) => (
              <option key={bu.id} value={bu.id}>{bu.name}</option>
            ))}
          </select>
        </Field>
        <label className="flex items-center gap-2 text-[13px] text-[#374151] cursor-pointer">
          <input
            type="checkbox"
            checked={isAdmin}
            onChange={(e) => setIsAdmin(e.target.checked)}
            className="rounded border-[#dde1e8]"
          />
          Admin access
        </label>
        <div className="flex justify-end gap-2 mt-2">
          <button type="button" onClick={onClose} className="px-4 py-2 text-[13px] text-[#6b7280] hover:text-[#1a1a2e]">Cancel</button>
          <button
            type="button"
            onClick={() => onSave({ display_name: displayName || undefined, business_unit_id: buId ?? undefined, is_admin: isAdmin })}
            className="px-4 py-2 text-[13px] font-semibold bg-[#003366] text-white rounded-md hover:bg-[#0a4a8c]"
          >
            Save Changes
          </button>
        </div>
      </div>
    </Dialog>
  );
}

function Dialog({ title, children, onClose }: { title: string; children: React.ReactNode; onClose: () => void }) {
  return (
    <div className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center p-4">
      <div className="bg-white rounded-xl shadow-xl w-full max-w-md">
        <div className="bg-[#003366] border-b-4 border-[#C9A52C] px-6 py-4 rounded-t-xl">
          <h2 className="text-white font-semibold text-[15px]">{title}</h2>
        </div>
        <div className="px-6 py-5">{children}</div>
      </div>
    </div>
  );
}

function Field({ label, required, children }: { label: string; required?: boolean; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-1.5">
      <label className="text-[12.5px] font-medium text-[#374151]">
        {label}{required && <span className="text-red-500 ml-0.5">*</span>}
      </label>
      {children}
    </div>
  );
}
