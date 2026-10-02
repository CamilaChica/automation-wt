import CustomerRFQForm from "./customer/CustomerRFQForm";
import CustomerPortalGate from "./customer/CustomerPortalGate";

export default function Home() {
  return <CustomerPortalGate><CustomerRFQForm /></CustomerPortalGate>;
}
