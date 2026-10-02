const http = require("node:http");

const quote = {
  quote: {
    id: "QTE-9921",
    rfq_id: "RFQ-1001",
    subtotal: 9200,
    shipping_cost: 125,
    total_amount: 9325,
    status: "Sent",
    lead_time_days: 5,
    valid_until: "2027-10-15",
  },
  rfq_status: "Quote_Sent",
  items: [{
    part_number: "XYZ123",
    quantity: 2,
    unit_price: 4600,
    certificate_type: "FAA Form 8130-3",
    compliance_status: "Pass",
    condition: "Overhauled",
  }],
};

let sessionActive = false;
let nextAttachment = 1;

function json(response, status, payload, headers = {}) {
  response.writeHead(status, { "Content-Type": "application/json", ...headers });
  response.end(JSON.stringify(payload));
}

function readJson(request) {
  return new Promise((resolve, reject) => {
    let body = "";
    request.setEncoding("utf8");
    request.on("data", chunk => { body += chunk; });
    request.on("end", () => {
      try {
        resolve(body ? JSON.parse(body) : {});
      } catch (error) {
        reject(error);
      }
    });
    request.on("error", reject);
  });
}

function hasSession(request) {
  return sessionActive && request.headers.cookie?.includes("wt_session=mock-backend-session");
}

const server = http.createServer(async (request, response) => {
  const url = new URL(request.url, "http://127.0.0.1:3210");
  if (request.method === "GET" && url.pathname === "/healthz") {
    return json(response, 200, { status: "ok" });
  }
  if (request.method === "POST" && url.pathname === "/__test/reset") {
    sessionActive = false;
    nextAttachment = 1;
    response.writeHead(204);
    return response.end();
  }
  if (request.method === "POST" && url.pathname === "/api/auth/otp/request") {
    const payload = await readJson(request);
    if (payload.role !== "CUSTOMER" || !payload.email) return json(response, 400, { detail: "Invalid sign-in request." });
    return json(response, 200, {
      challenge_id: "challenge-e2e",
      message: "If eligible, a code was sent.",
      development_otp: "123456",
    });
  }
  if (request.method === "POST" && url.pathname === "/api/auth/otp/verify") {
    const payload = await readJson(request);
    if (payload.challenge_id !== "challenge-e2e" || payload.code !== "123456") {
      return json(response, 401, { detail: "OTP is invalid or expired." });
    }
    sessionActive = true;
    return json(response, 200, { role: "ROLE_CUSTOMER", email: "buyer@example.com" }, {
      "Set-Cookie": "wt_session=mock-backend-session; HttpOnly; Path=/; Max-Age=28800; SameSite=Lax",
    });
  }
  if (request.method === "GET" && url.pathname === "/api/auth/session") {
    return hasSession(request)
      ? json(response, 200, { email: "buyer@example.com", role: "ROLE_CUSTOMER" })
      : json(response, 401, { detail: "Authentication required." });
  }
  if (request.method === "POST" && url.pathname === "/api/auth/logout") {
    if (!hasSession(request)) return json(response, 401, { detail: "Authentication required." });
    sessionActive = false;
    response.writeHead(204, { "Set-Cookie": "wt_session=; HttpOnly; Path=/; Max-Age=0" });
    return response.end();
  }
  if (!hasSession(request)) return json(response, 401, { detail: "Authentication required." });
  if (request.method === "POST" && url.pathname === "/api/attachments") {
    return json(response, 200, {
      attachment_id: `ATT-E2E-${nextAttachment++}`,
      filename: "signed.pdf",
      content_type: "application/pdf",
      size_bytes: 24,
      sha256: "internal-content-hash",
      stored_path: "/var/data/attachments/signed.pdf",
      status: "ACCEPTED",
    });
  }
  if (request.method === "GET" && url.pathname === "/api/quotes/QTE-9921") {
    return json(response, 200, quote);
  }
  if (request.method === "POST" && url.pathname === "/api/purchase-orders") {
    const payload = await readJson(request);
    return json(response, 200, {
      status: "Pending_PO_Review",
      po_number: payload.po_number,
      quote_id: payload.quote_id,
      internal_notification: { recipient: "internal@example.com", message_id: "private-message-id" },
      supplier_confirmation_count: 0,
    });
  }
  if (request.method === "POST" && url.pathname === "/api/rfqs/intake") {
    return json(response, 201, { rfq_id: "RFQ-E2E-1", status: "Intake", message: "Request received." });
  }
  return json(response, 404, { detail: "Not found." });
});

server.listen(3210, "127.0.0.1");
