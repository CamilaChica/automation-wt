import React, { useState } from 'react';
import { UserRole, ROLE_LABELS } from '../../types';
import {
  ShieldCheck,
  Users,
  Settings,
  KeyRound,
  Trash2,
  Plus,
  Server,
  CheckCircle2
} from 'lucide-react';

interface AdminUser {
  id: string;
  name: string;
  email: string;
  role: UserRole;
  status: 'ACTIVE' | 'SUSPENDED';
}

export const AdminView: React.FC = () => {
  const [users, setUsers] = useState<AdminUser[]>([
    { id: 'U-001', name: 'Alex R.', email: 'alex.r@wingedtycoons.com', role: 'sales', status: 'ACTIVE' },
    { id: 'U-002', name: 'Eliza C.', email: 'eliza.c@wingedtycoons.com', role: 'purchasing', status: 'ACTIVE' },
    { id: 'U-003', name: 'Maria G.', email: 'maria.g@wingedtycoons.com', role: 'purchasing', status: 'ACTIVE' },
    { id: 'U-004', name: 'Marcus D.', email: 'marcus.d@wingedtycoons.com', role: 'purchasing', status: 'ACTIVE' },
    { id: 'U-005', name: 'Global Airlines Portal', email: 'ops@globalairlines.com', role: 'customer', status: 'ACTIVE' }
  ]);
  const [notification, setNotification] = useState<string | null>(null);

  const notify = (message: string) => {
    setNotification(message);
    setTimeout(() => setNotification(null), 4000);
  };

  const toggleStatus = (id: string) => {
    setUsers(prev => prev.map(u => {
      if (u.id !== id) return u;
      const next: AdminUser = { ...u, status: u.status === 'ACTIVE' ? 'SUSPENDED' : 'ACTIVE' };
      notify(`${u.name} is now ${next.status}.`);
      return next;
    }));
  };

  const changeRole = (id: string, role: UserRole) => {
    setUsers(prev => prev.map(u => (u.id === id ? { ...u, role } : u)));
    notify(`Role updated for user ${id}.`);
  };

  const handleAddUser = () => {
    const nextId = `U-${String(users.length + 1).padStart(3, '0')}`;
    setUsers(prev => [...prev, { id: nextId, name: 'New Operator', email: 'new.operator@wingedtycoons.com', role: 'customer', status: 'ACTIVE' }]);
    notify(`Invited new operator ${nextId}.`);
  };

  const handleRemoveUser = (id: string) => {
    setUsers(prev => prev.filter(u => u.id !== id));
    notify(`Removed user ${id}.`);
  };

  return (
    <div className="p-4 md:p-6 space-y-6 max-w-7xl mx-auto font-sans text-slate-900 dark:text-slate-100">
      {notification && (
        <div className="bg-emerald-50 dark:bg-emerald-500/20 border border-emerald-300 dark:border-emerald-500 text-emerald-800 dark:text-emerald-300 p-3 rounded-xl flex items-center justify-between text-[11px] font-semibold animate-fade-in shadow-sm">
          <span>{notification}</span>
          <button onClick={() => setNotification(null)} className="text-slate-400 hover:text-slate-700 dark:hover:text-white">✕</button>
        </div>
      )}

      {/* Header */}
      <div className="brand-card bg-white dark:bg-card-dark border border-slate-200 dark:border-slate-800 rounded-2xl p-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center space-x-3">
            <div className="w-10 h-10 rounded-xl bg-gradient-to-tr from-aero-blue to-aero-blue-light flex items-center justify-center shadow-md">
              <ShieldCheck className="w-5 h-5 text-white" />
            </div>
            <div>
              <h1 className="font-display font-bold text-sm uppercase tracking-wide">Administration Console</h1>
              <p className="text-[10px] text-slate-500">User Access & System Configuration</p>
            </div>
          </div>
          <span className="px-2.5 py-1 rounded-full bg-emerald-50 dark:bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 font-mono text-[10px] font-bold border border-emerald-200 dark:border-emerald-500/30">
            SUPERUSER ACCESS
          </span>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        {/* User & Role Management */}
        <div className="lg:col-span-8 brand-card bg-white dark:bg-card-dark border border-slate-200 dark:border-slate-800 rounded-2xl p-5 space-y-4">
          <div className="flex items-center justify-between border-b border-slate-100 dark:border-slate-800 pb-3">
            <h2 className="font-display font-bold text-xs tracking-wider uppercase flex items-center space-x-2">
              <Users className="w-4 h-4 text-aero-blue" />
              <span>User & Role Management</span>
            </h2>
            <button
              onClick={handleAddUser}
              className="bg-aero-blue hover:bg-blue-600 text-white font-bold py-1.5 px-3 rounded-xl text-[10px] flex items-center space-x-1 shadow-sm transition-colors"
            >
              <Plus className="w-3.5 h-3.5" />
              <span>INVITE USER</span>
            </button>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full min-w-[560px] text-left font-mono text-[11px]">
              <thead>
                <tr className="text-slate-400 border-b border-slate-100 dark:border-slate-800 text-[10px]">
                  <th className="pb-2">User</th>
                  <th className="pb-2">Interface Access (Role)</th>
                  <th className="pb-2">Status</th>
                  <th className="pb-2 text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 dark:divide-slate-800/60">
                {users.map((u) => (
                  <tr key={u.id} className="hover:bg-slate-50 dark:hover:bg-slate-800/40 transition-colors">
                    <td className="py-2.5">
                      <div className="font-bold text-slate-900 dark:text-slate-100">{u.name}</div>
                      <div className="text-[10px] text-slate-500">{u.email}</div>
                    </td>
                    <td className="py-2.5">
                      <select
                        value={u.role}
                        onChange={(e) => changeRole(u.id, e.target.value as UserRole)}
                        className="bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-lg px-2 py-1 text-[10px] font-mono focus:outline-none focus:border-aero-blue"
                      >
                        {(Object.keys(ROLE_LABELS) as UserRole[]).map((r) => (
                          <option key={r} value={r}>{ROLE_LABELS[r]}</option>
                        ))}
                      </select>
                    </td>
                    <td className="py-2.5">
                      <button
                        onClick={() => toggleStatus(u.id)}
                        className={`px-2 py-0.5 rounded-full text-[9px] font-bold border transition-colors ${
                          u.status === 'ACTIVE'
                            ? 'bg-emerald-50 dark:bg-emerald-500/20 text-emerald-700 dark:text-emerald-400 border-emerald-200 dark:border-emerald-500/30'
                            : 'bg-red-50 dark:bg-aog-red/20 text-aog-red border-red-200 dark:border-aog-red/40'
                        }`}
                      >
                        {u.status}
                      </button>
                    </td>
                    <td className="py-2.5 text-right">
                      <button
                        onClick={() => handleRemoveUser(u.id)}
                        className="text-slate-400 hover:text-aog-red transition-colors"
                        title="Remove user"
                      >
                        <Trash2 className="w-3.5 h-3.5" />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        {/* System Status & Config */}
        <div className="lg:col-span-4 space-y-4">
          <div className="brand-card bg-white dark:bg-card-dark border border-slate-200 dark:border-slate-800 rounded-2xl p-5 space-y-3">
            <h2 className="font-display font-bold text-xs tracking-wider uppercase flex items-center space-x-2">
              <Server className="w-4 h-4 text-aero-blue" />
              <span>System Status</span>
            </h2>
            <div className="flex items-center justify-between text-[11px] font-mono">
              <span className="text-slate-500">FASTAPI Backend</span>
              <span className="text-emerald-600 dark:text-emerald-400 font-bold flex items-center space-x-1">
                <CheckCircle2 className="w-3.5 h-3.5" /><span>ONLINE</span>
              </span>
            </div>
            <div className="flex items-center justify-between text-[11px] font-mono">
              <span className="text-slate-500">RFQ Intake Pipeline</span>
              <span className="text-emerald-600 dark:text-emerald-400 font-bold flex items-center space-x-1">
                <CheckCircle2 className="w-3.5 h-3.5" /><span>ONLINE</span>
              </span>
            </div>
            <div className="flex items-center justify-between text-[11px] font-mono">
              <span className="text-slate-500">Version</span>
              <span className="font-bold">v1.0.0</span>
            </div>
          </div>

          <div className="brand-card bg-white dark:bg-card-dark border border-slate-200 dark:border-slate-800 rounded-2xl p-5 space-y-3">
            <h2 className="font-display font-bold text-xs tracking-wider uppercase flex items-center space-x-2">
              <Settings className="w-4 h-4 text-aero-blue" />
              <span>Access Policy</span>
            </h2>
            <p className="text-[10px] text-slate-500 leading-relaxed">
              Each role is restricted to its own interface set: Customers only see the Customer Dashboard,
              Sales sees Sales Command, Purchasing/MRO Ops sees Sourcing, Procurement, Trace Vault and Fulfillment,
              and Admins can access every interface for oversight.
            </p>
            <button
              onClick={() => notify('Access policy configuration saved.')}
              className="w-full bg-slate-100 dark:bg-slate-800 hover:bg-slate-200 text-slate-800 dark:text-slate-200 font-bold py-2 px-3 rounded-xl text-[10px] border border-slate-200 dark:border-slate-700 flex items-center justify-center space-x-1.5 transition-colors"
            >
              <KeyRound className="w-3.5 h-3.5" />
              <span>SAVE POLICY</span>
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};
