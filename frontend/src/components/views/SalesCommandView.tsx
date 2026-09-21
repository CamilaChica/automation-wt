import React, { useEffect, useState } from 'react';
import { WorldMapTelemetry } from '../common/WorldMapTelemetry';
import { apiService } from '../../services/api';
import { RFQ } from '../../types';
import { 
  Send, 
  FileText, 
  CheckCircle, 
  Sliders, 
  Download,
  Mail,
  UserCheck
} from 'lucide-react';

export const SalesCommandView: React.FC = () => {
  const [selectedRfqId, setSelectedRfqId] = useState('');
  const [rfqInbox, setRfqInbox] = useState<RFQ[]>([]);
  const [selectedQuoteId, setSelectedQuoteId] = useState('');
  const [quoteReady, setQuoteReady] = useState(false);
  const [unitPrice, setUnitPrice] = useState<number>(14200);
  const [marginPercent, setMarginPercent] = useState<number>(20);
  const [shippingOption, setShippingOption] = useState<'NFO' | 'HotShot'>('HotShot');
  const [issuing, setIssuing] = useState(false);
  const [notification, setNotification] = useState<string | null>(null);

  const loadRfqDetail = (rfqId: string) => {
    setSelectedRfqId(rfqId);
    setQuoteReady(false);
    void apiService.getRFQDetail(rfqId).then(detail => {
      setSelectedQuoteId(detail.quote_details?.quote.id || '');
      setQuoteReady(true);
    });
  };

  useEffect(() => {
    void apiService.getRFQs().then(rfqs => {
      setRfqInbox(rfqs);
      const quoteReadyRfq = rfqs.find(rfq => rfq.status === 'Quoted') || rfqs[0];
      if (quoteReadyRfq) {
        loadRfqDetail(quoteReadyRfq.id);
      }
    });
  }, []);

  const calculateTotal = () => {
    return unitPrice;
  };

  const downloadQuote = (format: 'pdf' | 'csv') => {
    const selectedRfq = rfqInbox.find(rfq => rfq.id === selectedRfqId);
    const customer = selectedRfq?.customer_name || 'Customer';
    const content = format === 'csv'
      ? `RFQ,Customer,Part Number,Quantity,Unit Price\n${selectedRfqId},${customer},32-11-45-01,1,${unitPrice}`
      : `Winged Tycoons Quote\nRFQ: ${selectedRfqId}\nCustomer: ${customer}\nPart: 32-11-45-01\nUnit price: $${unitPrice.toLocaleString()}\nShipping: customer-selected`;
    const blob = new Blob([content], { type: format === 'csv' ? 'text/csv' : 'application/pdf' });
    const link = document.createElement('a');
    link.href = URL.createObjectURL(blob);
    link.download = `${selectedRfqId || 'quote'}.${format}`;
    link.click();
    URL.revokeObjectURL(link.href);
  };

  const handleIssueQuote = async () => {
    setIssuing(true);
    if (!selectedQuoteId) {
      setIssuing(false);
      setNotification('Select a quote-ready RFQ before issuing a customer quote.');
      return;
    }
    await apiService.approveQuote(selectedQuoteId, 'Alex R. (Sales Lead)', [
      { quote_item_id: 'QITEM-01', unit_price: unitPrice }
    ]);
    setIssuing(false);
    const customer = rfqInbox.find(rfq => rfq.id === selectedRfqId)?.customer_name || 'customer';
    setNotification(`Quote ${selectedRfqId} issued to ${customer}! Customer communication dispatched.`);
    setTimeout(() => setNotification(null), 5000);
  };

  return (
    <div className="p-4 md:p-6 space-y-6 max-w-7xl mx-auto font-sans text-slate-900 dark:text-slate-100">
      {/* Toast Notification */}
      {notification && (
        <div className="bg-emerald-50 dark:bg-emerald-500/20 border border-emerald-300 dark:border-emerald-500 text-emerald-800 dark:text-emerald-300 p-4 rounded-2xl flex items-center justify-between text-xs font-semibold animate-fade-in shadow-sm">
          <div className="flex items-center space-x-2">
            <CheckCircle className="w-5 h-5 text-emerald-600 dark:text-emerald-400" />
            <span>{notification}</span>
          </div>
          <button onClick={() => setNotification(null)} className="text-slate-400 hover:text-slate-700 dark:hover:text-white">✕</button>
        </div>
      )}

      {/* Main Grid: 3 Columns */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        {/* Left Column (5 cols): GLOBAL RFQ INBOX */}
        <div className="lg:col-span-5 bg-white dark:bg-card-dark border border-slate-200 dark:border-slate-800 rounded-2xl p-5 shadow-sm space-y-4">
          <div className="flex items-center justify-between border-b border-slate-100 dark:border-slate-800 pb-3">
            <h2 className="font-display font-bold text-xs tracking-wider text-slate-900 dark:text-slate-100 uppercase flex items-center space-x-2">
              <span className="w-2 h-2 rounded-full bg-aero-blue animate-pulse" />
              <span>GLOBAL RFQ INBOX</span>
            </h2>
            <span className="px-2.5 py-0.5 rounded-full bg-blue-50 dark:bg-emerald-500/10 text-aero-blue dark:text-emerald-400 font-mono text-[10px] font-bold border border-blue-200 dark:border-emerald-500/30">
              REAL TIME DATA
            </span>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-left font-mono text-[11px]">
              <thead>
                <tr className="text-slate-400 border-b border-slate-100 dark:border-slate-800 text-[10px]">
                  <th className="pb-2">RFQ ID</th>
                  <th className="pb-2">Customer</th>
                  <th className="pb-2">Part Number</th>
                  <th className="pb-2">Urgency</th>
                  <th className="pb-2 text-right">Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 dark:divide-slate-800/60">
                {rfqInbox.length === 0 && (
                  <tr><td colSpan={5} className="py-8 text-center text-slate-400">No RFQs currently require attention.</td></tr>
                )}
                {rfqInbox.map((rfq) => (
                  <tr
                    key={rfq.id}
                    onClick={() => loadRfqDetail(rfq.id)}
                    className={`cursor-pointer transition-colors ${
                      selectedRfqId === rfq.id
                        ? 'bg-blue-50/80 dark:bg-aero-blue/20 text-slate-900 dark:text-white font-semibold'
                        : 'hover:bg-slate-50 dark:hover:bg-slate-800/40 text-slate-700 dark:text-slate-300'
                    }`}
                  >
                    <td className="py-2.5 font-bold text-aero-blue">{rfq.id}</td>
                    <td className="py-2.5 text-slate-800 dark:text-slate-200 text-[10px]">{rfq.customer_name}</td>
                    <td className="py-2.5 font-mono text-[10px]">{rfq.part_number || 'Pending extraction'}</td>
                    <td className="py-2.5">
                      <span className={`px-2 py-0.5 rounded-full text-[9px] font-bold ${
                        rfq.urgency === 'AOG' ? 'bg-red-50 dark:bg-aog-red/20 text-aog-red border border-red-200 dark:border-aog-red/40 aog-pulse-badge' : 'bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300'
                      }`}>
                        {rfq.urgency || 'Routine'}
                      </span>
                    </td>
                    <td className="py-2.5 text-right text-emerald-600 dark:text-emerald-400 font-bold">{rfq.status}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        {/* Center Column (4 cols): QUOTATION BUILDER & SMART QUOTE EDITOR */}
        <div className="lg:col-span-4 space-y-6">
          {/* Active Workflow: Quotation Builder */}
          <div className="bg-white dark:bg-card-dark border border-slate-200 dark:border-slate-800 rounded-2xl p-5 shadow-sm space-y-4">
            <div className="flex items-center justify-between border-b border-slate-100 dark:border-slate-800 pb-3">
              <h2 className="font-display font-bold text-xs tracking-wider text-slate-900 dark:text-slate-100 uppercase">
                ACTIVE WORKFLOW ({selectedRfqId})
              </h2>
            </div>

            <div className="space-y-2.5 font-mono text-[11px]">
              <div className="text-slate-500 dark:text-slate-400 uppercase text-[9px] font-bold">PARTS RESOLVER & SOURCE MATRICES</div>
              <div className="bg-slate-50 dark:bg-slate-900/80 p-2.5 rounded-xl border border-slate-200 dark:border-slate-800 flex items-center justify-between text-slate-800 dark:text-slate-200">
                <span className="font-bold">32-11-45-01</span>
                <span className="text-slate-500 dark:text-slate-400 text-[10px]">Lead Time: 1 Day</span>
              </div>

              {/* Source matrix comparison snippet */}
              <div className="bg-slate-50 dark:bg-slate-900/60 p-3 rounded-xl border border-slate-200 dark:border-slate-800 space-y-2">
                <div className="flex items-center justify-between font-bold text-slate-800 dark:text-slate-200">
                  <span>Supplier A (Stock)</span>
                  <span className="text-emerald-600 dark:text-emerald-400">$14,200</span>
                </div>
                <div className="flex items-center justify-between text-[10px] text-slate-600 dark:text-slate-400">
                  <span>Supplier B (FRA)</span>
                  <span className="text-slate-800 dark:text-slate-200">$11,800</span>
                </div>
                <div className="flex items-center justify-between text-[10px] text-slate-600 dark:text-slate-400">
                  <span>Supplier C (DFW)</span>
                  <span className="text-slate-800 dark:text-slate-200">$12,500</span>
                </div>
              </div>
            </div>
          </div>

          {/* Smart Quote Editor */}
          <div className="bg-white dark:bg-card-dark border border-slate-200 dark:border-slate-800 rounded-2xl p-5 shadow-sm space-y-4">
            <div className="flex items-center justify-between border-b border-slate-100 dark:border-slate-800 pb-3">
              <h2 className="font-display font-bold text-xs tracking-wider text-slate-900 dark:text-slate-100 uppercase flex items-center space-x-2">
                <Sliders className="w-4 h-4 text-aero-blue" />
                <span>SMART QUOTE EDITOR</span>
              </h2>
              <span className="text-[9px] font-mono text-slate-500 dark:text-slate-400">Markup Controls</span>
            </div>

            <div className="space-y-3 font-mono text-[11px]">
              <div className="grid grid-cols-4 gap-2 text-slate-400 text-[10px] border-b border-slate-100 dark:border-slate-800 pb-1">
                <div>Part</div>
                <div>Qty</div>
                <div>Unit Price</div>
                <div className="text-right">Margin</div>
              </div>

              <div className="grid grid-cols-4 gap-2 items-center text-slate-800 dark:text-slate-100 font-bold">
                <div className="text-aero-blue">32-11-45-01</div>
                <div>1</div>
                <div>${unitPrice.toLocaleString()}</div>
                <div className="text-right text-emerald-600 dark:text-emerald-400">{marginPercent}%</div>
              </div>

              {/* Dynamic Interactive Unit Price & Margin Slider */}
              <div className="space-y-1.5 bg-slate-50 dark:bg-slate-900/90 p-3 rounded-xl border border-slate-200 dark:border-slate-800">
                <div className="flex items-center justify-between text-[10px] text-slate-600 dark:text-slate-300">
                  <span>Adjust Unit Price / Margin:</span>
                  <span className="font-bold text-aero-blue">${unitPrice.toLocaleString()}</span>
                </div>
                <input
                  type="range"
                  min="10000"
                  max="20000"
                  step="100"
                  value={unitPrice}
                  onChange={(e) => {
                    const price = parseFloat(e.target.value);
                    setUnitPrice(price);
                    setMarginPercent(Math.round(((price - 9800) / price) * 100));
                  }}
                  className="w-full h-1.5 bg-slate-200 dark:bg-slate-800 rounded-lg appearance-none cursor-pointer accent-aero-blue"
                />
              </div>

              {/* Shipping Premium Selectors */}
              <div className="space-y-1.5">
                <label className="text-[10px] text-slate-500 dark:text-slate-400 uppercase font-bold">Shipping Cost Option:</label>
                <div className="flex items-center space-x-4 bg-slate-50 dark:bg-slate-900 p-2.5 rounded-xl border border-slate-200 dark:border-slate-800">
                  <label className="flex items-center space-x-2 cursor-pointer text-[10px] text-slate-700 dark:text-slate-300">
                    <input
                      type="radio"
                      name="shipping"
                      checked={shippingOption === 'NFO'}
                      onChange={() => setShippingOption('NFO')}
                      className="text-aero-blue"
                    />
                    <span>NFO ($120)</span>
                  </label>
                  <label className="flex items-center space-x-2 cursor-pointer text-[10px] text-amber-600 dark:text-amber-400 font-bold">
                    <input
                      type="radio"
                      name="shipping"
                      checked={shippingOption === 'HotShot'}
                      onChange={() => setShippingOption('HotShot')}
                      className="text-aero-blue"
                    />
                    <span>Hot Shot ($250)</span>
                  </label>
                </div>
              </div>

              {/* Total Calculation */}
              <div className="bg-slate-50 dark:bg-slate-900 p-3 rounded-xl border border-slate-200 dark:border-slate-800 flex items-center justify-between">
                <span className="font-bold text-slate-700 dark:text-slate-300">TOTAL PROPOSAL:</span>
                <span className="font-extrabold text-emerald-600 dark:text-emerald-400 text-sm">${calculateTotal().toLocaleString()}</span>
              </div>

              {/* PDF & Excel Action buttons */}
              <div className="flex items-center space-x-2 pt-1">
                <button onClick={() => downloadQuote('pdf')} className="flex-1 bg-slate-100 hover:bg-slate-200 dark:bg-slate-800 dark:hover:bg-slate-700 text-slate-700 dark:text-slate-200 py-2 px-3 rounded-xl text-[10px] font-bold border border-slate-200 dark:border-slate-700 flex items-center justify-center space-x-1.5 transition-colors">
                  <FileText className="w-3.5 h-3.5 text-aog-red" />
                  <span>PDF Export</span>
                </button>
                <button onClick={() => downloadQuote('csv')} className="flex-1 bg-slate-100 hover:bg-slate-200 dark:bg-slate-800 dark:hover:bg-slate-700 text-slate-700 dark:text-slate-200 py-2 px-3 rounded-xl text-[10px] font-bold border border-slate-200 dark:border-slate-700 flex items-center justify-center space-x-1.5 transition-colors">
                  <Download className="w-3.5 h-3.5 text-emerald-500" />
                  <span>Excel Export</span>
                </button>
              </div>

              {/* Action Buttons */}
              <div className="grid grid-cols-2 gap-2 pt-1 font-display">
                <button
                  onClick={handleIssueQuote}
                  disabled={issuing || !quoteReady}
                  className="bg-aero-blue hover:bg-blue-600 text-white font-bold py-2.5 px-3 rounded-xl text-xs flex items-center justify-center space-x-1.5 shadow-sm"
                >
                  <Send className="w-3.5 h-3.5" />
                  <span>{issuing ? 'ISSUING...' : quoteReady ? 'ISSUE QUOTE' : 'LOADING QUOTE...'}</span>
                </button>
                <button onClick={() => setNotification('Purchase orders are submitted by customers through the customer portal after quote approval.')} className="bg-slate-100 hover:bg-slate-200 dark:bg-slate-800 dark:hover:bg-slate-700 text-slate-800 dark:text-slate-200 font-bold py-2.5 px-3 rounded-xl text-xs border border-slate-200 dark:border-slate-700 transition-colors">
                  ISSUE PO
                </button>
              </div>
            </div>
          </div>
        </div>

        {/* Right Column (3 cols): CUSTOMER 360 & HISTORY & TELEMETRY */}
        <div className="lg:col-span-3 space-y-6">
          {/* Customer 360 & History */}
          <div className="bg-white dark:bg-card-dark border border-slate-200 dark:border-slate-800 rounded-2xl p-5 shadow-sm space-y-4 font-mono text-[11px]">
            <div className="flex items-center justify-between border-b border-slate-100 dark:border-slate-800 pb-3">
              <h2 className="font-display font-bold text-xs tracking-wider text-slate-900 dark:text-slate-100 uppercase flex items-center space-x-2">
                <UserCheck className="w-4 h-4 text-emerald-500" />
                <span>CUSTOMER 360</span>
              </h2>
            </div>

            <div className="bg-slate-50 dark:bg-slate-900/80 p-3 rounded-xl border border-slate-200 dark:border-slate-800 space-y-1.5">
              <div className="font-extrabold text-slate-900 dark:text-slate-100 text-xs">GLOBAL AIRLINES</div>
              <div className="flex items-center justify-between text-[10px]">
                <span className="text-slate-500 dark:text-slate-400">Credit Standing:</span>
                <span className="px-2 py-0.5 rounded-full bg-emerald-50 dark:bg-emerald-500/20 text-emerald-700 dark:text-emerald-400 font-bold border border-emerald-200 dark:border-emerald-500/30">Verified</span>
              </div>
              <div className="flex items-center justify-between text-[10px]">
                <span className="text-slate-500 dark:text-slate-400">Quote Conversion:</span>
                <span className="text-emerald-600 dark:text-emerald-400 font-bold">90%</span>
              </div>
            </div>

            {/* Communications Feed */}
            <div className="space-y-2">
              <div className="text-slate-500 dark:text-slate-400 text-[10px] uppercase font-bold">COMMUNICATIONS FEED</div>
              
              <div className="bg-slate-50 dark:bg-slate-900/60 p-2.5 rounded-xl border border-slate-200 dark:border-slate-800 flex items-center justify-between text-[10px]">
                <div className="flex items-center space-x-2 text-aero-blue font-semibold">
                  <Mail className="w-3.5 h-3.5" />
                  <span>WT-31005 Trace Packet</span>
                </div>
                <Download className="w-3.5 h-3.5 text-slate-400 cursor-pointer hover:text-slate-700 dark:hover:text-white" />
              </div>

              <div className="bg-slate-50 dark:bg-slate-900/60 p-2.5 rounded-xl border border-slate-200 dark:border-slate-800 flex items-center justify-between text-[10px]">
                <div className="flex items-center space-x-2 text-slate-700 dark:text-slate-300 font-semibold">
                  <Mail className="w-3.5 h-3.5" />
                  <span>WT-31006 Invoice PDF</span>
                </div>
                <Download className="w-3.5 h-3.5 text-slate-400 cursor-pointer hover:text-slate-700 dark:hover:text-white" />
              </div>
            </div>
          </div>

          {/* Real-Time Tracking & Delivery Map */}
          <WorldMapTelemetry title="REAL-TIME TRACKING" subtitle="In-transit flight telemetry" />
        </div>
      </div>
    </div>
  );
};
