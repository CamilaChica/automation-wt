import React, { useEffect, useMemo, useState } from 'react';
import { CheckCircle, Send } from 'lucide-react';
import { apiService } from '../../services/api';
import { RFQ } from '../../types';
import { WorldMapTelemetry } from '../common/WorldMapTelemetry';

export const SalesCommandView: React.FC = () => {
  const [rfqs, setRfqs] = useState<RFQ[]>([]);
  const [selectedRfqId, setSelectedRfqId] = useState<string | null>(null);
  const [issuing, setIssuing] = useState(false);
  const [notification, setNotification] = useState<string | null>(null);

  useEffect(() => {
    const load = async () => {
      const items = await apiService.getSalesClientRfqs();
      setRfqs(items);
      if (items.length > 0) {
        setSelectedRfqId(items[0].id);
      }
    };
    void load();
  }, []);

  const selected = useMemo(
    () => rfqs.find((item) => item.id === selectedRfqId) || rfqs[0],
    [rfqs, selectedRfqId]
  );

  const counts = useMemo(() => {
    const pending = rfqs.filter((item) => item.lifecycle_status === 'Pending').length;
    const poPending = rfqs.filter((item) => item.lifecycle_status === 'PO Pending').length;
    const solved = rfqs.filter((item) => item.lifecycle_status === 'Solved').length;
    return { pending, poPending, solved };
  }, [rfqs]);

  const handleIssueQuote = async () => {
    if (!selected?.quote_id) {
      setNotification('Selected RFQ has no generated quote yet.');
      return;
    }
    setIssuing(true);
    const response = await apiService.approveQuote(
      selected.quote_id,
      'Alex R. (Sales Lead)',
      undefined,
      true
    );
    setIssuing(false);
    setNotification(
      `Quote ${response.quote_id} approved. Auto-procurement generated ${response.purchase_orders?.length ?? 0} PO(s).`
    );
    const refreshed = await apiService.getSalesClientRfqs();
    setRfqs(refreshed);
  };

  return (
    <div className="p-4 md:p-6 space-y-6 max-w-7xl mx-auto font-sans text-slate-900 dark:text-slate-100">
      {notification && (
        <div className="bg-emerald-50 dark:bg-emerald-500/20 border border-emerald-300 dark:border-emerald-500 text-emerald-800 dark:text-emerald-300 p-4 rounded-2xl text-xs font-semibold flex items-center gap-2">
          <CheckCircle className="w-4 h-4" />
          <span>{notification}</span>
        </div>
      )}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <div className="rounded-2xl p-4 border bg-white dark:bg-card-dark">
          <div className="text-xs uppercase text-slate-500">Pending</div>
          <div className="text-2xl font-bold">{counts.pending}</div>
        </div>
        <div className="rounded-2xl p-4 border bg-white dark:bg-card-dark">
          <div className="text-xs uppercase text-slate-500">PO Pending</div>
          <div className="text-2xl font-bold">{counts.poPending}</div>
        </div>
        <div className="rounded-2xl p-4 border bg-white dark:bg-card-dark">
          <div className="text-xs uppercase text-slate-500">Solved</div>
          <div className="text-2xl font-bold">{counts.solved}</div>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        <div className="lg:col-span-8 rounded-2xl p-5 border bg-white dark:bg-card-dark">
          <h2 className="font-display text-sm font-bold mb-4">Client RFQ Queue</h2>
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead>
                <tr className="text-slate-500 border-b">
                  <th className="py-2">RFQ</th>
                  <th className="py-2">Customer</th>
                  <th className="py-2">Part</th>
                  <th className="py-2">Qty</th>
                  <th className="py-2">Lifecycle</th>
                </tr>
              </thead>
              <tbody>
                {rfqs.map((item) => (
                  <tr
                    key={item.id}
                    onClick={() => setSelectedRfqId(item.id)}
                    className={`cursor-pointer border-b ${selected?.id === item.id ? 'bg-blue-50 dark:bg-blue-900/20' : ''}`}
                  >
                    <td className="py-2 font-semibold text-aero-blue">{item.id}</td>
                    <td className="py-2">{item.customer_name}</td>
                    <td className="py-2 font-mono">{item.part_number || '-'}</td>
                    <td className="py-2">{item.quantity ?? '-'}</td>
                    <td className="py-2">{item.lifecycle_status || 'Pending'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        <div className="lg:col-span-4 rounded-2xl p-5 border bg-white dark:bg-card-dark space-y-4">
          <h2 className="font-display text-sm font-bold">Selected RFQ</h2>
          <div className="text-xs space-y-1">
            <div><span className="text-slate-500">RFQ:</span> {selected?.id || '-'}</div>
            <div><span className="text-slate-500">Quote:</span> {selected?.quote_id || 'Not generated'}</div>
            <div><span className="text-slate-500">Amount:</span> {selected?.quote_total ? `$${selected.quote_total.toLocaleString()}` : '-'}</div>
            <div><span className="text-slate-500">PO:</span> {selected?.po_status || 'Pending'}</div>
          </div>
          <button
            onClick={handleIssueQuote}
            disabled={issuing || !selected?.quote_id}
            className="w-full bg-aero-blue text-white rounded-xl py-2.5 text-xs font-bold disabled:opacity-50 flex items-center justify-center gap-2"
          >
            <Send className="w-4 h-4" />
            {issuing ? 'ISSUING...' : 'APPROVE + AUTO-PO'}
          </button>
        </div>
      </div>
      <WorldMapTelemetry title="Sales Dispatch Telemetry" subtitle="Quote and PO movement" />
    </div>
  );
};
