"""Stock Reservation Service.

Manages 2-hour temporary stock holds for parts quoted to clients today.
Enables instant purchase order checkout with locked pricing, dynamic countdowns,
and mandatory compliance verification.
"""

from __future__ import annotations

import json
import logging
import os
import re
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from services.operations_store import operations_store

logger = logging.getLogger("winged-tycoons-stock-reservation")


def _norm_pn(val: Any) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(val or "").upper())


class StockReservationService:
    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path
        self._init_table()

    def _get_connection(self):
        if self.db_path:
            import sqlite3
            return sqlite3.connect(self.db_path)
        return operations_store._connect()

    def _init_table(self) -> None:
        try:
            conn = self._get_connection()
            try:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS stock_reservations (
                        id TEXT PRIMARY KEY,
                        part_number TEXT NOT NULL,
                        normalized_part_number TEXT NOT NULL,
                        client_email TEXT NOT NULL,
                        company_name TEXT,
                        quote_number TEXT NOT NULL,
                        rfq_id TEXT,
                        unit_price REAL NOT NULL DEFAULT 0.0,
                        total_price REAL NOT NULL DEFAULT 0.0,
                        currency TEXT NOT NULL DEFAULT 'USD',
                        quantity INTEGER NOT NULL DEFAULT 1,
                        condition TEXT,
                        certification TEXT,
                        lead_time TEXT,
                        reserved_at TEXT NOT NULL,
                        expires_at TEXT NOT NULL,
                        status TEXT NOT NULL DEFAULT 'ACTIVE',
                        po_number TEXT,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );
                """)
                conn.execute("CREATE INDEX IF NOT EXISTS idx_stock_res_client_status ON stock_reservations(client_email, status);")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_stock_res_part ON stock_reservations(normalized_part_number, status);")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_stock_res_expires ON stock_reservations(expires_at, status);")
                conn.commit()
            finally:
                conn.close()
        except Exception as exc:
            logger.warning("Stock reservation table init failed: %s", exc)

    def check_part_quoted_today(self, part_number: str, client_email: str = "") -> Optional[Dict[str, Any]]:
        """Check if part was quoted formally today in client_quote_history.
        
        If the email of the client is different than the original recipient,
        a new RFQ number is provisioned for this client.
        """
        norm = _norm_pn(part_number)
        if not norm:
            return None

        today_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        clean_email = str(client_email or "").strip().lower()

        conn = self._get_connection()
        conn.row_factory = None
        try:
            cursor = conn.cursor()
            query = """
                SELECT 
                    id, client_email, client_name, company_name, quote_number, rfq_id,
                    part_number, normalized_part_number, description, quantity,
                    unit_price, total_price, currency, condition, certification,
                    lead_time, sent_at
                FROM client_quote_history
                WHERE normalized_part_number = ?
                  AND sent_at LIKE ?
                ORDER BY sent_at DESC
                LIMIT 1
            """
            cursor.execute(query, (norm, f"{today_utc}%"))
            row = cursor.fetchone()
            if not row:
                # Also check recent 24h as fallback for timezone variances
                since_yesterday = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
                cursor.execute("""
                    SELECT 
                        id, client_email, client_name, company_name, quote_number, rfq_id,
                        part_number, normalized_part_number, description, quantity,
                        unit_price, total_price, currency, condition, certification,
                        lead_time, sent_at
                    FROM client_quote_history
                    WHERE normalized_part_number = ?
                      AND sent_at >= ?
                    ORDER BY sent_at DESC
                    LIMIT 1
                """, (norm, since_yesterday))
                row = cursor.fetchone()

            if not row:
                return None

            (
                _id, quoted_client_email, client_name, company_name, quote_number, rfq_id,
                pn, norm_pn, description, quantity,
                unit_price, total_price, currency, condition, certification,
                lead_time, sent_at
            ) = row

            is_same_client = bool(clean_email and clean_email == (quoted_client_email or "").lower())

            # If logged in client is different than original quote recipient:
            # Generate a new RFQ number for this client
            if not is_same_client and clean_email:
                now_str = datetime.now(timezone.utc).strftime("%Y%m%d")
                new_rfq_id = f"RFQ-{now_str}-{uuid.uuid4().hex[:6].upper()}"
                active_quote_number = f"QTE-{now_str}-{uuid.uuid4().hex[:6].upper()}"
                active_rfq_id = new_rfq_id
            else:
                active_quote_number = quote_number or f"QTE-{uuid.uuid4().hex[:8].upper()}"
                active_rfq_id = rfq_id or f"RFQ-{uuid.uuid4().hex[:8].upper()}"

            return {
                "quoted_today": True,
                "part_number": pn,
                "normalized_part_number": norm_pn,
                "description": description or pn,
                "quote_number": active_quote_number,
                "original_quote_number": quote_number,
                "rfq_id": active_rfq_id,
                "unit_price": float(unit_price or 0.0),
                "total_price": float(total_price or unit_price or 0.0),
                "currency": str(currency or "USD"),
                "quantity": int(quantity or 1),
                "condition": str(condition or "NE"),
                "certification": str(certification or "FAA 8130-3 Dual Release"),
                "lead_time": str(lead_time or "Stock"),
                "is_same_client": is_same_client,
                "original_client_email": quoted_client_email,
                "client_name": client_name or "",
                "company_name": company_name or "",
                "sent_at": sent_at,
            }
        finally:
            conn.close()

    def create_stock_hold(
        self,
        *,
        client_email: str,
        part_number: str,
        quote_number: str,
        unit_price: float,
        quantity: int = 1,
        total_price: Optional[float] = None,
        company_name: Optional[str] = None,
        rfq_id: Optional[str] = None,
        condition: Optional[str] = None,
        certification: Optional[str] = None,
        lead_time: Optional[str] = None,
        duration_minutes: int = 120,
    ) -> Dict[str, Any]:
        """Register an immediate 2-hour stock reservation hold."""
        clean_email = str(client_email or "").strip().lower()
        if not clean_email or "@" not in clean_email:
            raise ValueError(f"Valid client email is required: {client_email}")

        clean_pn = str(part_number or "").strip()
        norm_pn = _norm_pn(clean_pn)
        qty = max(1, int(quantity or 1))
        u_price = float(unit_price or 0.0)
        t_price = float(total_price) if total_price is not None else (u_price * qty)

        now = datetime.now(timezone.utc)
        expires = now + timedelta(minutes=duration_minutes)

        conn = self._get_connection()
        try:
            # Check if active hold already exists for this client and part
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, expires_at, quote_number, rfq_id
                FROM stock_reservations
                WHERE client_email = ? AND normalized_part_number = ? AND status = 'ACTIVE'
            """, (clean_email, norm_pn))
            existing = cursor.fetchone()
            if existing:
                res_id, existing_expires, ex_quote, ex_rfq = existing
                exp_dt = datetime.fromisoformat(existing_expires.replace("Z", "+00:00"))
                if exp_dt > now:
                    remaining = int((exp_dt - now).total_seconds())
                    return {
                        "reservation_id": res_id,
                        "part_number": clean_pn,
                        "quote_number": ex_quote,
                        "rfq_id": ex_rfq,
                        "client_email": clean_email,
                        "company_name": company_name or "",
                        "unit_price": u_price,
                        "total_price": t_price,
                        "quantity": qty,
                        "condition": condition or "NE",
                        "certification": certification or "FAA 8130-3 Dual Release",
                        "lead_time": lead_time or "Stock",
                        "reserved_at": now.isoformat(),
                        "expires_at": existing_expires,
                        "remaining_seconds": remaining,
                        "status": "ACTIVE",
                    }

            res_id = f"HLD-{uuid.uuid4().hex[:12].upper()}"
            conn.execute("""
                INSERT INTO stock_reservations (
                    id, part_number, normalized_part_number, client_email, company_name,
                    quote_number, rfq_id, unit_price, total_price, currency,
                    quantity, condition, certification, lead_time,
                    reserved_at, expires_at, status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'ACTIVE', ?, ?)
            """, (
                res_id, clean_pn, norm_pn, clean_email, company_name or "",
                quote_number, rfq_id or "", u_price, t_price, "USD",
                qty, condition or "NE", certification or "FAA 8130-3 Dual Release", lead_time or "Stock",
                now.isoformat(), expires.isoformat(), now.isoformat(), now.isoformat(),
            ))
            conn.commit()

            return {
                "reservation_id": res_id,
                "part_number": clean_pn,
                "quote_number": quote_number,
                "rfq_id": rfq_id or "",
                "client_email": clean_email,
                "company_name": company_name or "",
                "unit_price": u_price,
                "total_price": t_price,
                "quantity": qty,
                "condition": condition or "NE",
                "certification": certification or "FAA 8130-3 Dual Release",
                "lead_time": lead_time or "Stock",
                "reserved_at": now.isoformat(),
                "expires_at": expires.isoformat(),
                "remaining_seconds": int(duration_minutes * 60),
                "status": "ACTIVE",
            }
        finally:
            conn.close()

    def get_active_hold_for_client(self, client_email: str) -> Optional[Dict[str, Any]]:
        """Return the latest active stock hold for this client, or None."""
        clean_email = str(client_email or "").strip().lower()
        if not clean_email:
            return None

        now = datetime.now(timezone.utc)
        conn = self._get_connection()
        conn.row_factory = None
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT 
                    id, part_number, normalized_part_number, client_email, company_name,
                    quote_number, rfq_id, unit_price, total_price, currency,
                    quantity, condition, certification, lead_time,
                    reserved_at, expires_at, status
                FROM stock_reservations
                WHERE client_email = ? AND status = 'ACTIVE'
                ORDER BY created_at DESC
                LIMIT 1
            """, (clean_email,))
            row = cursor.fetchone()
            if not row:
                return None

            (
                res_id, pn, norm_pn, c_email, comp,
                q_num, rfq_id, u_price, t_price, curr,
                qty, cond, cert, lead,
                res_at, exp_at, status
            ) = row

            exp_dt = datetime.fromisoformat(exp_at.replace("Z", "+00:00"))
            if exp_dt <= now:
                # Mark as expired
                cursor.execute("UPDATE stock_reservations SET status = 'EXPIRED', updated_at = ? WHERE id = ?", (now.isoformat(), res_id))
                conn.commit()
                return None

            remaining = int((exp_dt - now).total_seconds())
            return {
                "reservation_id": res_id,
                "part_number": pn,
                "normalized_part_number": norm_pn,
                "client_email": c_email,
                "company_name": comp or "",
                "quote_number": q_num,
                "rfq_id": rfq_id or "",
                "unit_price": u_price,
                "total_price": t_price,
                "currency": curr,
                "quantity": qty,
                "condition": cond,
                "certification": cert,
                "lead_time": lead,
                "reserved_at": res_at,
                "expires_at": exp_at,
                "remaining_seconds": remaining,
                "status": "ACTIVE",
            }
        finally:
            conn.close()

    def release_hold(self, reservation_id: str, client_email: str) -> bool:
        """Manually release a stock hold back to general availability."""
        conn = self._get_connection()
        try:
            now = datetime.now(timezone.utc).isoformat()
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE stock_reservations SET status = 'RELEASED', updated_at = ? WHERE id = ? AND client_email = ?",
                (now, reservation_id, client_email.strip().lower()),
            )
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()

    def convert_hold_to_order(self, quote_number: str, po_number: str, client_email: Optional[str] = None) -> bool:
        """Mark an active hold as converted upon successful purchase order submission."""
        conn = self._get_connection()
        try:
            now = datetime.now(timezone.utc).isoformat()
            cursor = conn.cursor()
            if client_email:
                cursor.execute(
                    "UPDATE stock_reservations SET status = 'CONVERTED', po_number = ?, updated_at = ? WHERE quote_number = ? AND client_email = ? AND status = 'ACTIVE'",
                    (po_number, now, quote_number, client_email.strip().lower()),
                )
            else:
                cursor.execute(
                    "UPDATE stock_reservations SET status = 'CONVERTED', po_number = ?, updated_at = ? WHERE quote_number = ? AND status = 'ACTIVE'",
                    (po_number, now, quote_number),
                )
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()


stock_reservation_service = StockReservationService()
