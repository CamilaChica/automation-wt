import QuoteView from "../../customer/QuoteView";
import CustomerPortalGate from "../../customer/CustomerPortalGate";

export default async function QuotePage({ params }: { params: Promise<{ quote_id: string }> }) {
  const { quote_id: quoteId } = await params;
  return <CustomerPortalGate><QuoteView quoteId={quoteId} /></CustomerPortalGate>;
}
