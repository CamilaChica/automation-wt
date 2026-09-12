import React, { useEffect, useState } from 'react';
import { FileCheck } from 'lucide-react';
import { apiService } from '../../services/api';
import { ProcurementOverview } from '../../types';
import { WorldMapTelemetry } from '../common/WorldMapTelemetry';

export const AeroProcurementView: React.FC = () => {
  const [overview, setOverview] = useState<ProcurementOverview>({
    supplier_inventory: [],
    active_purchase_orders: [],
  });

  useEffect(() => {
    const load = async () => {
      const data = await apiService.getProcurementOverview();
      setOverview(data);
    };
    void load();
  }, []);

  return (
    <div className="p-4 md:p-6 space-y-6 max-w-7xl mx-auto font-sans text-slate-900 dark:text-slate-100">
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        <div className="lg:col-span-7 rounded-2xl p-5 border bg-white dark:bg-card-dark">
          <div className="flex items-center justify-between mb-4">
            <h2 className="font-display text-sm font-bold">Supplier Inventory</h2>
            <span className="text-xs text-slate-500">{overview.supplier_inventory.length} records</span>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead>
                <tr className="text-slate-500 border-b">
                  <th className="py-2">Part</th>
                  <th className="py-2">Supplier</th>
                  <th className="py-2">Qty</th>
                  <th className="py-2">Condition</th>
                  <th className="py-2">Unit Cost</th>
                </tr>
              </thead>
              <tbody>
                {overview.supplier_inventory.map((item) => (
                  <tr key={item.id} className="border-b">
                    <td className="py-2 font-mono">{item.part_number}</td>
                    <td className="py-2">{item.supplier_name}</td>
                    <td className="py-2">{item.quantity_available}</td>
                    <td className="py-2">{item.condition_code}</td>
                    <td className="py-2">${item.unit_cost.toLocaleString()}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        <div className="lg:col-span-5 rounded-2xl p-5 border bg-white dark:bg-card-dark">
          <div className="flex items-center gap-2 mb-4">
            <FileCheck className="w-4 h-4 text-emerald-500" />
            <h2 className="font-display text-sm font-bold">Active Purchase Orders</h2>
          </div>
          <div className="space-y-3">
            {overview.active_purchase_orders.length === 0 && (
              <div className="text-xs text-slate-500">No active purchase orders.</div>
            )}
            {overview.active_purchase_orders.map((po) => (
              <div key={po.id} className="rounded-xl border p-3 text-xs">
                <div className="font-semibold text-aero-blue">{po.id}</div>
                <div className="mt-1">RFQ: {po.rfq_id}</div>
                <div>Supplier: {po.supplier_name}</div>
                <div>Part: <span className="font-mono">{po.part_number}</span> x {po.quantity}</div>
                <div>Status: {po.status}</div>
              </div>
            ))}
          </div>
        </div>
      </div>
      <WorldMapTelemetry title="Procurement Logistics" subtitle="Supplier and PO execution flow" />
    </div>
  );
};
