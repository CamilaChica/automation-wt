import React, { useEffect, useState } from 'react';
import { HelpCircle, X } from 'lucide-react';
import { CustomerLanguage } from '../../i18n/customerPortal';

type Audience = 'client' | 'internal';
type QaEntry = { question: string; answer: string };
type ClientQaCopy = { button: string; title: string; intro: string; entries: QaEntry[] };

const clientQa: Record<CustomerLanguage, ClientQaCopy> = {
  en: { button: 'Customer Q&A', title: 'Customer questions', intro: 'Quick answers about parts, requests, and orders.', entries: [
    { question: 'How do I find a part?', answer: 'Search by the manufacturer or customer part number. Availability shown here is preliminary; our team confirms it before sending a quote.' },
    { question: 'How do I request a quote?', answer: 'Complete the request form with your contact details, part number, quantity, condition, and any useful delivery or certification details.' },
    { question: 'What is required for a purchase order?', answer: 'Use the quote reference from your email and provide the signed export certification, signed KYC form, and purchase order document.' },
    { question: 'How do I track a shipment?', answer: 'Enter the private tracking token from your shipment email. Tracking updates appear when carrier events are available.' },
    { question: 'How can I contact the team?', answer: 'Use Contact Us above to email the parts desk or open voice support.' },
  ] },
  fr: { button: 'Questions clients', title: 'Questions des clients', intro: 'Réponses rapides sur les pièces, demandes et commandes.', entries: [
    { question: 'Comment trouver une pièce ?', answer: 'Recherchez par référence fabricant ou client. La disponibilité affichée est préliminaire ; notre équipe la confirme avant le devis.' },
    { question: 'Comment demander un devis ?', answer: 'Remplissez le formulaire avec vos coordonnées, la référence, la quantité, l’état et les détails utiles de livraison ou de certification.' },
    { question: 'Quels documents faut-il pour une commande ?', answer: 'Utilisez la référence du devis reçue par e-mail et fournissez la certification export signée, le formulaire KYC signé et le bon de commande.' },
    { question: 'Comment suivre une expédition ?', answer: 'Saisissez le jeton privé reçu par e-mail. Les mises à jour apparaissent lorsque les événements du transporteur sont disponibles.' },
    { question: 'Comment contacter l’équipe ?', answer: 'Utilisez « Nous contacter » pour écrire au service pièces ou ouvrir l’assistance vocale.' },
  ] },
  es: { button: 'Preguntas del cliente', title: 'Preguntas de clientes', intro: 'Respuestas rápidas sobre piezas, solicitudes y pedidos.', entries: [
    { question: '¿Cómo encuentro una pieza?', answer: 'Busque por el número del fabricante o del cliente. La disponibilidad mostrada es preliminar; nuestro equipo la confirma antes de cotizar.' },
    { question: '¿Cómo solicito una cotización?', answer: 'Complete el formulario con sus datos, número de pieza, cantidad, condición y detalles de entrega o certificación.' },
    { question: '¿Qué documentos requiere una orden?', answer: 'Use la referencia de cotización recibida por correo e incluya la certificación de exportación firmada, el formulario KYC firmado y la orden de compra.' },
    { question: '¿Cómo rastreo un envío?', answer: 'Introduzca el token privado recibido por correo. Las actualizaciones aparecen cuando hay eventos del transportista.' },
    { question: '¿Cómo contacto al equipo?', answer: 'Use «Contacto» para enviar un correo al equipo de piezas o abrir la asistencia por voz.' },
  ] },
  de: { button: 'Kundenfragen', title: 'Kundenfragen', intro: 'Kurze Antworten zu Teilen, Anfragen und Bestellungen.', entries: [
    { question: 'Wie finde ich ein Teil?', answer: 'Suchen Sie nach Hersteller- oder Kundenteilenummer. Die angezeigte Verfügbarkeit ist vorläufig und wird vor dem Angebot bestätigt.' },
    { question: 'Wie fordere ich ein Angebot an?', answer: 'Füllen Sie das Formular mit Kontaktdaten, Teilenummer, Menge, Zustand und relevanten Liefer- oder Zertifizierungsangaben aus.' },
    { question: 'Welche Unterlagen braucht eine Bestellung?', answer: 'Verwenden Sie die Angebotsreferenz aus der E-Mail und fügen Sie Exportzertifikat, KYC-Formular und Bestellung unterschrieben bei.' },
    { question: 'Wie verfolge ich eine Sendung?', answer: 'Geben Sie das private Tracking-Token aus Ihrer E-Mail ein. Aktualisierungen erscheinen, sobald Transportereignisse vorliegen.' },
    { question: 'Wie erreiche ich das Team?', answer: 'Über „Kontakt“ können Sie dem Teileteam schreiben oder die Sprachunterstützung öffnen.' },
  ] },
  pt: { button: 'Perguntas do cliente', title: 'Perguntas dos clientes', intro: 'Respostas rápidas sobre peças, solicitações e pedidos.', entries: [
    { question: 'Como encontro uma peça?', answer: 'Pesquise pelo número do fabricante ou do cliente. A disponibilidade exibida é preliminar e será confirmada antes da cotação.' },
    { question: 'Como solicito uma cotação?', answer: 'Preencha o formulário com contato, número da peça, quantidade, condição e detalhes de entrega ou certificação.' },
    { question: 'Quais documentos são necessários para o pedido?', answer: 'Use a referência da cotação recebida por e-mail e envie a certificação de exportação assinada, o formulário KYC assinado e o pedido de compra.' },
    { question: 'Como rastreio uma remessa?', answer: 'Digite o token privado recebido por e-mail. As atualizações aparecem quando há eventos da transportadora.' },
    { question: 'Como entro em contato com a equipe?', answer: 'Use “Contato” para enviar um e-mail à equipe de peças ou abrir o atendimento por voz.' },
  ] },
  it: { button: 'Domande clienti', title: 'Domande dei clienti', intro: 'Risposte rapide su ricambi, richieste e ordini.', entries: [
    { question: 'Come trovo un ricambio?', answer: 'Cerca per codice del produttore o del cliente. La disponibilità mostrata è preliminare e viene confermata prima del preventivo.' },
    { question: 'Come richiedo un preventivo?', answer: 'Compila il modulo con contatti, codice ricambio, quantità, condizione e dettagli utili di consegna o certificazione.' },
    { question: 'Quali documenti servono per un ordine?', answer: 'Usa il riferimento del preventivo ricevuto via e-mail e allega la certificazione export firmata, il modulo KYC firmato e l’ordine.' },
    { question: 'Come traccio una spedizione?', answer: 'Inserisci il token privato ricevuto via e-mail. Gli aggiornamenti appaiono quando sono disponibili eventi del corriere.' },
    { question: 'Come contatto il team?', answer: 'Usa “Contattaci” per scrivere al team ricambi o aprire l’assistenza vocale.' },
  ] },
  ja: { button: 'お客様 Q&A', title: 'お客様からの質問', intro: '部品、リクエスト、注文に関する回答です。', entries: [
    { question: '部品を検索するには？', answer: 'メーカーまたはお客様の部品番号で検索してください。表示される在庫は仮情報で、見積もり前に担当チームが確認します。' },
    { question: '見積もりを依頼するには？', answer: '連絡先、部品番号、数量、状態、必要な配送先や認証情報を入力してください。' },
    { question: '注文には何の書類が必要ですか？', answer: 'メールに記載された見積番号を使い、署名済み輸出証明、KYCフォーム、発注書を提出してください。' },
    { question: '配送を追跡するには？', answer: '配送メールの専用追跡トークンを入力してください。運送会社のイベントが届くと更新されます。' },
    { question: 'チームに連絡するには？', answer: '上部の「お問い合わせ」から部品チームへのメールまたは音声サポートを利用できます。' },
  ] },
  zh: { button: '客户问答', title: '客户常见问题', intro: '关于零件、请求和订单的快速解答。', entries: [
    { question: '如何查找零件？', answer: '可按制造商或客户零件号搜索。页面显示的库存为初步信息，报价前由团队确认。' },
    { question: '如何申请报价？', answer: '填写联系人、零件号、数量、状态，以及相关交付或认证信息。' },
    { question: '提交采购订单需要哪些文件？', answer: '使用邮件中的报价编号，并提交已签署的出口认证、KYC 表格和采购订单文件。' },
    { question: '如何追踪货件？', answer: '输入货件邮件中的专用追踪令牌。收到承运商事件后会显示更新。' },
    { question: '如何联系团队？', answer: '点击上方“联系我们”，可给零件团队发送邮件或开启语音客服。' },
  ] },
  ko: { button: '고객 Q&A', title: '고객 자주 묻는 질문', intro: '부품, 요청 및 주문에 대한 빠른 답변입니다.', entries: [
    { question: '부품을 어떻게 찾나요?', answer: '제조업체 또는 고객 부품 번호로 검색하세요. 표시된 재고는 예비 정보이며 견적 전에 담당 팀이 확인합니다.' },
    { question: '견적을 어떻게 요청하나요?', answer: '연락처, 부품 번호, 수량, 상태와 배송 또는 인증 세부 정보를 입력하세요.' },
    { question: '구매 주문에 필요한 문서는 무엇인가요?', answer: '이메일의 견적 참조 번호를 사용하고 서명된 수출 인증서, KYC 양식, 구매 주문서를 제출하세요.' },
    { question: '배송을 어떻게 추적하나요?', answer: '배송 이메일의 비공개 추적 토큰을 입력하세요. 운송사 이벤트가 도착하면 업데이트됩니다.' },
    { question: '팀에 어떻게 연락하나요?', answer: '위쪽의 “문의하기”에서 부품팀 이메일 또는 음성 상담을 이용하세요.' },
  ] },
  nl: { button: 'Klantvragen', title: 'Veelgestelde klantvragen', intro: 'Snelle antwoorden over onderdelen, aanvragen en bestellingen.', entries: [
    { question: 'Hoe vind ik een onderdeel?', answer: 'Zoek op fabrikant- of klantonderdeelnummer. De getoonde beschikbaarheid is voorlopig; ons team bevestigt dit vóór de offerte.' },
    { question: 'Hoe vraag ik een offerte aan?', answer: 'Vul uw contactgegevens, onderdeelnummer, aantal, staat en relevante leverings- of certificeringsgegevens in.' },
    { question: 'Welke documenten zijn nodig voor een bestelling?', answer: 'Gebruik de offerteverwijzing uit onze e-mail en voeg het ondertekende exportcertificaat, KYC-formulier en de inkooporder toe.' },
    { question: 'Hoe volg ik een zending?', answer: 'Voer het privétrackingtoken uit uw verzendmail in. Updates verschijnen zodra vervoerdergebeurtenissen beschikbaar zijn.' },
    { question: 'Hoe neem ik contact op?', answer: 'Gebruik “Contact” om het onderdelenteam te mailen of spraakondersteuning te openen.' },
  ] },
  ar: { button: 'أسئلة العملاء', title: 'أسئلة العملاء الشائعة', intro: 'إجابات سريعة حول القطع والطلبات والشحنات.', entries: [
    { question: 'كيف أبحث عن قطعة؟', answer: 'ابحث برقم القطعة لدى الشركة المصنعة أو العميل. التوفر المعروض مبدئي، ويؤكده فريقنا قبل إرسال عرض السعر.' },
    { question: 'كيف أطلب عرض سعر؟', answer: 'أكمل النموذج ببيانات الاتصال ورقم القطعة والكمية والحالة وتفاصيل التسليم أو الاعتماد.' },
    { question: 'ما المستندات المطلوبة لأمر الشراء؟', answer: 'استخدم مرجع عرض السعر في البريد وأرفق شهادة التصدير الموقعة ونموذج KYC وأمر الشراء.' },
    { question: 'كيف أتتبع الشحنة؟', answer: 'أدخل رمز التتبع الخاص الوارد في رسالة الشحنة. تظهر التحديثات عند توفر أحداث شركة النقل.' },
    { question: 'كيف أتواصل مع الفريق؟', answer: 'استخدم «اتصل بنا» لإرسال بريد إلى فريق القطع أو فتح الدعم الصوتي.' },
  ] },
  hi: { button: 'ग्राहक प्रश्नोत्तर', title: 'ग्राहकों के सामान्य प्रश्न', intro: 'पुर्ज़ों, अनुरोधों और ऑर्डर के बारे में त्वरित उत्तर।', entries: [
    { question: 'पुर्ज़ा कैसे खोजें?', answer: 'निर्माता या ग्राहक के पुर्ज़े के नंबर से खोजें। दिखाई गई उपलब्धता प्रारंभिक है; कोटेशन से पहले टीम पुष्टि करती है।' },
    { question: 'कोटेशन कैसे माँगें?', answer: 'संपर्क विवरण, पुर्ज़े का नंबर, मात्रा, स्थिति और डिलीवरी या प्रमाणन विवरण भरें।' },
    { question: 'खरीद आदेश के लिए कौन से दस्तावेज़ चाहिए?', answer: 'ईमेल में दिए कोटेशन संदर्भ का उपयोग करें और हस्ताक्षरित निर्यात प्रमाणपत्र, KYC फ़ॉर्म तथा खरीद आदेश दें।' },
    { question: 'शिपमेंट कैसे ट्रैक करें?', answer: 'शिपमेंट ईमेल से निजी ट्रैकिंग टोकन दर्ज करें। वाहक के अपडेट उपलब्ध होने पर दिखाई देंगे।' },
    { question: 'टीम से कैसे संपर्क करें?', answer: 'ऊपर “संपर्क करें” से पुर्ज़ा टीम को ईमेल करें या वॉइस सहायता खोलें।' },
  ] },
};

const internalQa: ClientQaCopy = { button: 'Internal Q&A', title: 'Internal operations Q&A', intro: 'Quick guidance for RFQ and operations workflows.', entries: [
  { question: 'Why is an RFQ action disabled?', answer: 'Actions stay disabled while data is loading, unavailable, sample-only, or the selected RFQ has Intake_Failed status. Confirm the selected record and data source first.' },
  { question: 'What should I do with an Intake_Failed RFQ?', answer: 'Do not issue a quote or advance compliance actions. An admin or manager must record a reset reason in Procurement; after the RFQ returns to Intake, processing requires a separate explicit action. NEEDS_HUMAN_REVIEW must be resolved through its review queue.' },
  { question: 'Are DEMO ROUTE and SAMPLE values live?', answer: 'No. Those labels identify example route or workflow content. Do not use sample locations, prices, counts, or compliance states as operational evidence.' },
  { question: 'Where may I test mutation actions?', answer: 'Use staging with disposable records only. Verify confirmation, one-time submission, result feedback, rollback/cleanup, and audit trail; never test destructive actions on production.' },
  { question: 'How should a data-load failure be handled?', answer: 'Use the visible Retry control and check service/API health. If data remains unavailable, stop mutations and escalate to the owning operations team.' },
] };

interface FloatingQaProps {
  audience: Audience;
  language?: CustomerLanguage;
}

export const FloatingQa: React.FC<FloatingQaProps> = ({ audience, language = 'en' }) => {
  const [isOpen, setIsOpen] = useState(false);
  const copy = audience === 'client' ? clientQa[language] : internalQa;
  const titleId = `${audience}-qa-title`;

  useEffect(() => {
    if (!isOpen) return undefined;
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setIsOpen(false);
    };
    window.addEventListener('keydown', closeOnEscape);
    return () => window.removeEventListener('keydown', closeOnEscape);
  }, [isOpen]);

  return (
    <>
      <button
        type="button"
        aria-label={copy.button}
        aria-expanded={isOpen}
        aria-controls={`${audience}-qa-panel`}
        title={copy.button}
        onClick={() => setIsOpen(open => !open)}
        className="fixed bottom-5 right-5 z-[1100] inline-flex h-12 w-12 items-center justify-center rounded-full border border-cyan-800 bg-cyan-800 text-white shadow-lg transition-colors hover:bg-cyan-900 focus:outline-none focus-visible:ring-2 focus-visible:ring-cyan-500 focus-visible:ring-offset-2"
      >
        {isOpen ? <X aria-hidden="true" className="h-5 w-5" /> : <HelpCircle aria-hidden="true" className="h-6 w-6" />}
      </button>
      {isOpen && (
        <section
          id={`${audience}-qa-panel`}
          role="dialog"
          aria-modal="false"
          aria-labelledby={titleId}
          className="fixed bottom-20 right-5 z-[1100] flex max-h-[min(70vh,36rem)] w-[min(22rem,calc(100vw-2.5rem))] flex-col overflow-hidden border border-slate-200 bg-white shadow-2xl"
        >
          <header className="shrink-0 border-b border-slate-200 px-4 py-3">
            <h2 id={titleId} className="font-display text-base font-bold text-slate-900">{copy.title}</h2>
            <p className="mt-1 text-xs leading-5 text-slate-600">{copy.intro}</p>
          </header>
          <div className="overflow-y-auto p-3">
            {copy.entries.map(entry => (
              <details key={entry.question} className="border-b border-slate-200 last:border-b-0">
                <summary className="cursor-pointer py-3 text-sm font-semibold leading-5 text-slate-800 focus:outline-none focus-visible:ring-2 focus-visible:ring-cyan-600">
                  {entry.question}
                </summary>
                <p className="pb-3 text-sm leading-6 text-slate-600">{entry.answer}</p>
              </details>
            ))}
          </div>
        </section>
      )}
    </>
  );
};
