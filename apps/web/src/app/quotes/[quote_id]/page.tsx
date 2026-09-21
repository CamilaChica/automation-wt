import QuoteView from "../../customer/QuoteView";

export default async function QuotePage({ params }: { params: Promise<{ quote_id: string }> }) {
  const { quote_id: quoteId } = await params;
  return <QuoteView quoteId={quoteId} />;
}
