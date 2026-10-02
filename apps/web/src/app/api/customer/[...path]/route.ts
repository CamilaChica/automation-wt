import { NextRequest, NextResponse } from "next/server";

export const runtime = "nodejs";

const sessionCookieName = "wt_customer_session";
const publicPostRoutes = new Set(["auth/otp/request", "auth/otp/verify"]);
const protectedPostRoutes = new Set([
  "auth/logout",
  "rfqs/intake",
  "attachments",
  "purchase-orders",
]);

type RouteContext = { params: { path: string[] } };

function backendUrl(path: string[]): string | null {
  const baseUrl = process.env.API_BASE_URL?.trim();
  if (!baseUrl) return null;
  try {
    const url = new URL(baseUrl);
    if (url.protocol !== "http:" && url.protocol !== "https:") return null;
    if (process.env.NODE_ENV === "production" && url.protocol !== "https:") return null;
    return `${url.toString().replace(/\/$/, "")}/api/${path.map(encodeURIComponent).join("/")}`;
  } catch {
    return null;
  }
}

function sessionToken(request: NextRequest): string | null {
  return request.cookies.get(sessionCookieName)?.value ?? null;
}

function isSameOrigin(request: NextRequest): boolean {
  const origin = request.headers.get("origin");
  if (!origin) return false;
  try {
    const parsedOrigin = new URL(origin);
    const configuredOrigin = process.env.CUSTOMER_PORTAL_ORIGIN?.trim();
    const expectedOrigin = configuredOrigin ? new URL(configuredOrigin).origin : request.nextUrl.origin;
    return parsedOrigin.origin === expectedOrigin;
  } catch {
    return false;
  }
}

function backendHeaders(token: string | null): HeadersInit {
  return token ? { cookie: `wt_session=${token}`, accept: "application/json" } : { accept: "application/json" };
}

async function upstreamResponse(response: Response): Promise<NextResponse> {
  if (response.status === 204) return new NextResponse(null, { status: 204 });
  const body = await response.json().catch(() => ({ detail: "The service returned an invalid response." }));
  if (body && typeof body === "object" && "development_otp" in body) {
    delete body.development_otp;
  }
  const result = NextResponse.json(body, { status: response.status });
  result.headers.set("Cache-Control", "no-store");
  return result;
}

async function customerResponse(response: Response, route: string): Promise<NextResponse> {
  if (!response.ok) return upstreamResponse(response);
  if (route === "attachments" || route === "purchase-orders") {
    const payload = await response.json().catch(() => null);
    if (!payload || typeof payload !== "object") {
      return NextResponse.json({ detail: "The service returned an invalid response." }, { status: 502 });
    }
    const safePayload = route === "attachments"
      ? {
          attachment_id: payload.attachment_id,
          filename: payload.filename,
          size_bytes: payload.size_bytes,
          status: payload.status,
        }
      : {
          status: payload.status,
          po_number: payload.po_number,
          quote_id: payload.quote_id,
        };
    const result = NextResponse.json(safePayload, { status: response.status });
    result.headers.set("Cache-Control", "no-store");
    return result;
  }
  return upstreamResponse(response);
}

async function forwardGet(request: NextRequest, context: RouteContext): Promise<NextResponse> {
  const path = context.params.path ?? [];
  const route = path.join("/");
  if (route !== "auth/session" && !(path.length === 2 && path[0] === "quotes" && path[1])) {
    return NextResponse.json({ detail: "Not found." }, { status: 404 });
  }
  const token = sessionToken(request);
  if (!token) return NextResponse.json({ detail: "Sign in to continue." }, { status: 401 });
  const url = backendUrl(path);
  if (!url) return NextResponse.json({ detail: "The customer service is not configured." }, { status: 503 });
  try {
    return await upstreamResponse(await fetch(url, {
      headers: backendHeaders(token),
      cache: "no-store",
    }));
  } catch {
    return NextResponse.json({ detail: "The customer service is temporarily unavailable." }, { status: 502 });
  }
}

async function forwardPost(request: NextRequest, context: RouteContext): Promise<NextResponse> {
  const path = context.params.path ?? [];
  const route = path.join("/");
  const isPublic = publicPostRoutes.has(route);
  if (!isPublic && !protectedPostRoutes.has(route)) {
    return NextResponse.json({ detail: "Not found." }, { status: 404 });
  }
  const token = sessionToken(request);
  if (!isPublic && !token) {
    return NextResponse.json({ detail: "Sign in to continue." }, { status: 401 });
  }
  if (!isSameOrigin(request)) {
    return NextResponse.json({ detail: "Request origin could not be verified." }, { status: 403 });
  }
  const url = backendUrl(path);
  if (!url) return NextResponse.json({ detail: "The customer service is not configured." }, { status: 503 });

  let body: BodyInit | undefined;
  const headers = new Headers(backendHeaders(isPublic ? null : token));
  try {
    if (route === "attachments") {
      body = await request.formData();
    } else if (route !== "auth/logout") {
      body = JSON.stringify(await request.json());
      headers.set("Content-Type", "application/json");
    }
  } catch {
    return NextResponse.json({ detail: "The request body is invalid." }, { status: 400 });
  }

  try {
    const response = await fetch(url, { method: "POST", headers, body, cache: "no-store" });
    if (route === "auth/otp/verify" && response.ok) {
      const setCookie = response.headers.get("set-cookie") ?? "";
      const tokenMatch = setCookie.match(/(?:^|[,;]\s*)wt_session=([^;]+)/);
      if (!tokenMatch) {
        return NextResponse.json({ detail: "The sign-in service did not create a session." }, { status: 502 });
      }
      const result = await customerResponse(response, route);
      result.cookies.set(sessionCookieName, tokenMatch[1], {
        httpOnly: true,
        secure: process.env.NODE_ENV === "production",
        sameSite: "strict",
        path: "/",
        maxAge: 8 * 60 * 60,
      });
      return result;
    }
    const result = await customerResponse(response, route);
    if (route === "auth/logout" && response.ok) {
      result.cookies.delete(sessionCookieName);
    }
    return result;
  } catch {
    return NextResponse.json({ detail: "The customer service is temporarily unavailable." }, { status: 502 });
  }
}

export async function GET(request: NextRequest, context: RouteContext) {
  return forwardGet(request, context);
}

export async function POST(request: NextRequest, context: RouteContext) {
  return forwardPost(request, context);
}
