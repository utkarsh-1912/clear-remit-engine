"""Data models for the B2B Remittance & Short-Pay Reconciliation Engine."""

from __future__ import annotations
from dataclasses import dataclass, field, asdict
from decimal import Decimal
from typing import List, Optional, Dict, Any


@dataclass
class OpenInvoice:
    invoice_id: str
    customer_id: str
    customer_name: str
    issue_date: str
    due_date: str
    gross_amount: Decimal
    open_amount: Decimal
    currency: str = "USD"
    payment_terms: str = "Net 30"  # e.g., "2/10 Net 30", "1/15 Net 45", "Net 30"
    eligible_discount_pct: Decimal = Decimal("0.00")
    expected_tds_pct: Decimal = Decimal("0.00")
    po_number: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        for k, v in d.items():
            if isinstance(v, Decimal):
                d[k] = float(v)
        return d


@dataclass
class CreditMemo:
    memo_id: str
    customer_id: str
    customer_name: str
    amount: Decimal
    reason: str
    related_invoice_id: Optional[str] = None
    currency: str = "USD"

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        for k, v in d.items():
            if isinstance(v, Decimal):
                d[k] = float(v)
        return d


@dataclass
class StructuredDocRef:
    doc_type: str  # e.g. "CINV" (Commercial Invoice), "CREN" (Credit Note)
    doc_number: str
    invoiced_amount: Optional[Decimal] = None
    paid_amount: Optional[Decimal] = None
    discount_amount: Optional[Decimal] = None
    tax_withheld_amount: Optional[Decimal] = None
    adjustment_amount: Optional[Decimal] = None
    adjustment_reason: Optional[str] = None


@dataclass
class RemittanceHint:
    referenced_invoices: List[str] = field(default_factory=list)
    referenced_credit_memos: List[str] = field(default_factory=list)
    claimed_discount_pct: Optional[Decimal] = None
    claimed_discount_amount: Optional[Decimal] = None
    claimed_tds_pct: Optional[Decimal] = None
    claimed_tds_amount: Optional[Decimal] = None
    claimed_wire_fee: Optional[Decimal] = None
    claimed_deduction_amount: Optional[Decimal] = None
    claimed_deduction_reason: Optional[str] = None
    structured_refs: List[StructuredDocRef] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "referenced_invoices": self.referenced_invoices,
            "referenced_credit_memos": self.referenced_credit_memos,
            "claimed_discount_pct": float(self.claimed_discount_pct) if self.claimed_discount_pct is not None else None,
            "claimed_discount_amount": float(self.claimed_discount_amount) if self.claimed_discount_amount is not None else None,
            "claimed_tds_pct": float(self.claimed_tds_pct) if self.claimed_tds_pct is not None else None,
            "claimed_tds_amount": float(self.claimed_tds_amount) if self.claimed_tds_amount is not None else None,
            "claimed_wire_fee": float(self.claimed_wire_fee) if self.claimed_wire_fee is not None else None,
            "claimed_deduction_amount": float(self.claimed_deduction_amount) if self.claimed_deduction_amount is not None else None,
            "claimed_deduction_reason": self.claimed_deduction_reason,
            "structured_refs_count": len(self.structured_refs),
        }


@dataclass
class BankTransaction:
    tx_id: str
    booking_date: str
    payer_name: str
    amount: Decimal
    currency: str = "USD"
    payment_rail: str = "ISO20022_CAMT053"  # e.g., FEDNOW, RTP, ACH, SWIFT, SEPA, UPI/NEFT
    bank_reference: str = ""
    raw_remittance_unstructured: str = ""
    hints: RemittanceHint = field(default_factory=RemittanceHint)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tx_id": self.tx_id,
            "booking_date": self.booking_date,
            "payer_name": self.payer_name,
            "amount": float(self.amount),
            "currency": self.currency,
            "payment_rail": self.payment_rail,
            "bank_reference": self.bank_reference,
            "raw_remittance_unstructured": self.raw_remittance_unstructured,
            "hints": self.hints.to_dict(),
        }


@dataclass
class DeductionLine:
    deduction_type: str  # "EARLY_PAY_DISCOUNT", "TAX_WITHHOLDING_TDS", "BANK_WIRE_FEE", "CREDIT_MEMO", "SHORT_PAY_DISPUTE"
    description: str
    amount: Decimal
    gl_account_code: str
    gl_account_name: str
    is_authorized: bool = True
    related_invoice_id: Optional[str] = None
    credit_memo_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "deduction_type": self.deduction_type,
            "description": self.description,
            "amount": float(self.amount),
            "gl_account_code": self.gl_account_code,
            "gl_account_name": self.gl_account_name,
            "is_authorized": self.is_authorized,
            "related_invoice_id": self.related_invoice_id,
            "credit_memo_id": self.credit_memo_id,
        }


@dataclass
class InvoiceMatchAllocation:
    invoice_id: str
    gross_amount: Decimal
    discount_applied: Decimal
    tds_withheld: Decimal
    short_pay_or_memo: Decimal
    net_settled: Decimal

    def to_dict(self) -> Dict[str, Any]:
        return {
            "invoice_id": self.invoice_id,
            "gross_amount": float(self.gross_amount),
            "discount_applied": float(self.discount_applied),
            "tds_withheld": float(self.tds_withheld),
            "short_pay_or_memo": float(self.short_pay_or_memo),
            "net_settled": float(self.net_settled),
        }


@dataclass
class JournalEntryLine:
    line_number: int
    account_code: str
    account_name: str
    debit: Decimal
    credit: Decimal
    memo: str
    entity_name: str
    invoice_ref: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "line_number": self.line_number,
            "account_code": self.account_code,
            "account_name": self.account_name,
            "debit": float(self.debit),
            "credit": float(self.credit),
            "memo": self.memo,
            "entity_name": self.entity_name,
            "invoice_ref": self.invoice_ref,
        }


@dataclass
class ReconciliationProposal:
    tx_id: str
    status: str  # "AUTO_RECONCILED", "ACTION_REQUIRED_SHORT_PAY", "UNMATCHED_SUSPENSE"
    match_method: str  # "ISO20022_STRUCTURED", "HINT_GUIDED_SOLVER", "BLIND_SUBSET_SUM_SOLVER", "EXACT_SINGLE_MATCH"
    confidence_score: float
    matched_customer_id: str
    matched_customer_name: str
    deposit_amount: Decimal
    total_gross_invoices: Decimal
    total_deductions: Decimal
    residual_unexplained: Decimal
    allocations: List[InvoiceMatchAllocation] = field(default_factory=list)
    deductions: List[DeductionLine] = field(default_factory=list)
    journal_entries: List[JournalEntryLine] = field(default_factory=list)
    explanation_summary: str = ""
    dispute_notice_draft: Optional[str] = None
    booking_date: str = ""
    currency: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tx_id": self.tx_id,
            "status": self.status,
            "match_method": self.match_method,
            "confidence_score": round(self.confidence_score, 1),
            "matched_customer_id": self.matched_customer_id,
            "matched_customer_name": self.matched_customer_name,
            "deposit_amount": float(self.deposit_amount),
            "total_gross_invoices": float(self.total_gross_invoices),
            "total_deductions": float(self.total_deductions),
            "residual_unexplained": float(self.residual_unexplained),
            "allocations": [a.to_dict() for a in self.allocations],
            "deductions": [d.to_dict() for d in self.deductions],
            "journal_entries": [j.to_dict() for j in self.journal_entries],
            "explanation_summary": self.explanation_summary,
            "dispute_notice_draft": self.dispute_notice_draft,
            "booking_date": self.booking_date,
            "currency": self.currency,
        }


@dataclass
class SolverConfig:
    allowed_discount_pcts: List[Decimal] = field(
        default_factory=lambda: [Decimal("0"), Decimal("1.0"), Decimal("2.0"), Decimal("3.0")]
    )
    allowed_tds_pcts: List[Decimal] = field(
        default_factory=lambda: [Decimal("0"), Decimal("1.0"), Decimal("2.0"), Decimal("5.0"), Decimal("10.0")]
    )
    common_wire_fees: List[Decimal] = field(
        default_factory=lambda: [
            Decimal("0.00"),
            Decimal("10.00"),
            Decimal("15.00"),
            Decimal("20.00"),
            Decimal("25.00"),
            Decimal("30.00"),
            Decimal("35.00"),
        ]
    )
    auto_writeoff_tolerance: Decimal = Decimal("5.00")
    max_subset_size: int = 6
    max_candidate_checks: int = 10_000
