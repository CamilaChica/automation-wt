import { NextResponse } from "next/server";

export async function POST(request: Request) {
  const body = await request.json();
  if (!body.email || !String(body.email).includes("@")) return NextResponse.json({ error: "Invalid email" }, { status: 400 });
  return NextResponse.json({ rfq_id: `RFQ-WEB-${Date.now()}`, status: "RECEIVED" }, { status: 201 });
}
