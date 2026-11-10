"""Deterministic & Combinatorial Short-Pay Reconciliation Solver."""

from __future__ import annotations
import itertools
import re
from decimal import Decimal, ROUND_HALF_UP
from typing import List, Optional, Tuple, Dict
from engine.models import (
    BankTransaction,
    OpenInvoice,
    CreditMemo,
    DeductionLine,
    InvoiceMatchAllocation,
    JournalEntryLine,
    ReconciliationProposal,
    SolverConfig,
)


def _q2(val: Decimal) -> Decimal:
    return val.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _norm_name(name: str) -> str:
    cleaned = re.sub(r"\b(INC|LLC|LTD|CORP|CORPORATION|PVT|PRIVATE|LIMITED|GMBH|CO)\b", "", name.upper())
    return re.sub(r"[^A-Z0-9]", "", cleaned)


def _match_customer_invoices(
    tx: BankTransaction,
    all_invoices: List[OpenInvoice],
    all_memos: List[CreditMemo],
) -> Tuple[str, str, List[OpenInvoice], List[CreditMemo]]:
    """Finds the customer's open invoices and credit memos via explicit invoice hints or fuzzy payer name."""
    all_invoices = [inv for inv in all_invoices if inv.currency == tx.currency and inv.open_amount > 0]
    all_memos = [memo for memo in all_memos if memo.currency == tx.currency]
    inv_by_id: Dict[str, OpenInvoice] = {inv.invoice_id.upper(): inv for inv in all_invoices}

    hinted = {inv_by_id[ref.upper()].customer_id: inv_by_id[ref.upper()].customer_name
              for ref in tx.hints.referenced_invoices if ref.upper() in inv_by_id}
    if len(hinted) > 1:
        return "UNKNOWN", tx.payer_name, [], []
    if hinted:
        cust_id, cust_name = next(iter(hinted.items()))
        return cust_id, cust_name, [i for i in all_invoices if i.customer_id == cust_id], [
            m for m in all_memos if m.customer_id == cust_id
        ]

    # 2. Match via normalized payer name
    payer_norm = _norm_name(tx.payer_name)
    if payer_norm:
        customers = {}
        for inv in all_invoices:
            cust_norm = _norm_name(inv.customer_name)
            if cust_norm and (payer_norm in cust_norm or cust_norm in payer_norm):
                customers[inv.customer_id] = inv.customer_name
        if len(customers) == 1:
            cust_id, cust_name = next(iter(customers.items()))
            cust_invs = [i for i in all_invoices if i.customer_id == cust_id]
            cust_memos = [m for m in all_memos if m.customer_id == cust_id]
            return cust_id, cust_name, cust_invs, cust_memos

    return "UNKNOWN", tx.payer_name, [], []


def _build_journal_entries(
    tx: BankTransaction,
    customer_name: str,
    allocations: List[InvoiceMatchAllocation],
    deductions: List[DeductionLine],
    residual_unexplained: Decimal,
) -> List[JournalEntryLine]:
    """
    Produces a strictly balanced Double-Entry General Ledger journal entry (Total Debits == Total Credits).
      - Debit: 1010 Operating Bank Cash (Deposit Amount)
      - Debit: 4090 Sales Early-Pay Discounts (Authorized cash discounts)
      - Debit: 1150 Prepaid Tax / TDS Receivable (Statutory tax withheld at source)
      - Debit: 2140 Customer Credit Memos Applied (Clearing existing credit memo liability/contra-AR)
      - Debit: 6120 Bank & SWIFT Wire Charges (Intermediary wire fees)
      - Debit: 1290 Short-Pay Dispute Receivable / Suspense (Unauthorized deductions for recovery)
      - Credit: 1200 Accounts Receivable (Per matched invoice gross open amount)
    """
    lines: List[JournalEntryLine] = []
    line_no = 1

    # 1. Debit Bank Cash for the actual funds received
    lines.append(
        JournalEntryLine(
            line_number=line_no,
            account_code="1010",
            account_name="Operating Bank Cash",
            debit=_q2(tx.amount),
            credit=Decimal("0.00"),
            memo=f"Bank Deposit via {tx.payment_rail} (Ref: {tx.bank_reference})",
            entity_name=customer_name,
        )
    )
    line_no += 1

    # 2. Debit each Deduction / Adjustment Line to its appropriate GL Account
    for ded in deductions:
        if ded.amount > Decimal("0.00"):
            lines.append(
                JournalEntryLine(
                    line_number=line_no,
                    account_code=ded.gl_account_code,
                    account_name=ded.gl_account_name,
                    debit=_q2(ded.amount),
                    credit=Decimal("0.00"),
                    memo=ded.description,
                    entity_name=customer_name,
                    invoice_ref=ded.related_invoice_id,
                )
            )
            line_no += 1

    # 3. Handle any positive or negative residual unexplained variance
    if residual_unexplained > Decimal("0.00"):
        lines.append(
            JournalEntryLine(
                line_number=line_no,
                account_code="1290",
                account_name="AR Short-Pay Dispute Suspense",
                debit=_q2(residual_unexplained),
                credit=Decimal("0.00"),
                memo=f"Unexplained short-pay variance on {tx.tx_id}",
                entity_name=customer_name,
            )
        )
        line_no += 1
    elif residual_unexplained < Decimal("0.00"):
        lines.append(
            JournalEntryLine(
                line_number=line_no,
                account_code="2190",
                account_name="Unapplied Customer Overpayment Credit",
                debit=Decimal("0.00"),
                credit=_q2(abs(residual_unexplained)),
                memo=f"Unapplied overpayment variance on {tx.tx_id}",
                entity_name=customer_name,
            )
        )
        line_no += 1

    # 4. Credit Accounts Receivable (1200) for each matched invoice
    for alloc in allocations:
        lines.append(
            JournalEntryLine(
                line_number=line_no,
                account_code="1200",
                account_name="Accounts Receivable - Trade",
                debit=Decimal("0.00"),
                credit=_q2(alloc.gross_amount),
                memo=f"Settle Open Invoice {alloc.invoice_id} (Net Cash: {tx.currency} {alloc.net_settled:,.2f})",
                entity_name=customer_name,
                invoice_ref=alloc.invoice_id,
            )
        )
        line_no += 1

    return lines


def _generate_dispute_draft(
    tx: BankTransaction,
    customer_name: str,
    unauthorized_deductions: List[DeductionLine],
    allocations: List[InvoiceMatchAllocation],
) -> Optional[str]:
    if not unauthorized_deductions:
        return None

    total_disputed = sum((d.amount for d in unauthorized_deductions), Decimal("0.00"))
    inv_list = ", ".join(a.invoice_id for a in allocations)
    bullet_lines = "\n".join(
        f"  - {tx.currency} {d.amount:,.2f}: {d.description}"
        + (f" (Invoice {d.related_invoice_id})" if d.related_invoice_id else "")
        for d in unauthorized_deductions
    )

    return (
        f"SUBJECT: Short-pay balance of {tx.currency} {total_disputed:,.2f} on remittance {tx.bank_reference}\n\n"
        f"Dear {customer_name} Accounts Payable Team,\n\n"
        f"Thank you for your payment of {tx.currency} {tx.amount:,.2f} received on {tx.booking_date} via {tx.payment_rail} "
        f"(Ref: {tx.bank_reference}), which we have applied toward invoice(s): {inv_list}.\n\n"
        f"Our reconciliation identified the following unapproved deductions totaling {tx.currency} {total_disputed:,.2f}:\n"
        f"{bullet_lines}\n\n"
        f"Please send supporting documentation or remit the remaining balance of {tx.currency} {total_disputed:,.2f} "
        f"using your existing payment instructions.\n\nSincerely,\nAccounts Receivable"
    )


def _solve_structured_iso20022(
    tx: BankTransaction,
    cust_id: str,
    cust_name: str,
    cust_invoices: List[OpenInvoice],
) -> Optional[ReconciliationProposal]:
    """Solves transactions containing explicit ISO 20022 <Strd> document blocks."""
    if not tx.hints.structured_refs:
        return None

    inv_map = {i.invoice_id.upper(): i for i in cust_invoices}
    ref_ids = [ref.doc_number.upper() for ref in tx.hints.structured_refs]
    if len(set(ref_ids)) != len(ref_ids) or any(ref not in inv_map for ref in ref_ids):
        return None
    allocations: List[InvoiceMatchAllocation] = []
    deductions: List[DeductionLine] = []

    for sref in tx.hints.structured_refs:
        inv = inv_map[sref.doc_number.upper()]
        gross = inv.open_amount
        disc = _q2(sref.discount_amount or Decimal("0.00"))
        tds = _q2(sref.tax_withheld_amount or Decimal("0.00"))
        adj = _q2(sref.adjustment_amount or Decimal("0.00"))
        net_paid = _q2(sref.paid_amount if sref.paid_amount is not None else (gross - disc - tds - adj))

        allocations.append(
            InvoiceMatchAllocation(
                invoice_id=sref.doc_number,
                gross_amount=gross,
                discount_applied=disc,
                tds_withheld=tds,
                short_pay_or_memo=adj,
                net_settled=net_paid,
            )
        )

        if disc > Decimal("0.00"):
            max_allowed_disc = _q2(gross * (inv.eligible_discount_pct / Decimal("100")))
            is_auth = disc <= max_allowed_disc + Decimal("0.05")
            deductions.append(
                DeductionLine(
                    deduction_type="EARLY_PAY_DISCOUNT",
                    description=f"ISO 20022 Structured Discount on {sref.doc_number}",
                    amount=disc,
                    gl_account_code="4090" if is_auth else "1290",
                    gl_account_name="Sales Early-Pay Discounts" if is_auth else "AR Short-Pay Dispute Suspense",
                    is_authorized=is_auth,
                    related_invoice_id=sref.doc_number,
                )
            )

        if tds > Decimal("0.00"):
            deductions.append(
                DeductionLine(
                    deduction_type="TAX_WITHHOLDING_TDS",
                    description=f"Statutory Tax Withheld (TDS/WHT) on {sref.doc_number}",
                    amount=tds,
                    gl_account_code="1150",
                    gl_account_name="Prepaid Tax / TDS Receivable",
                    is_authorized=True,
                    related_invoice_id=sref.doc_number,
                )
            )

        if adj > Decimal("0.00"):
            rsn = sref.adjustment_reason or "Structured Remittance Adjustment"
            deductions.append(
                DeductionLine(
                    deduction_type="SHORT_PAY_DISPUTE",
                    description=f"Unapproved Short-Pay Deduction ({rsn}) on {sref.doc_number}",
                    amount=adj,
                    gl_account_code="1290",
                    gl_account_name="AR Short-Pay Dispute Suspense",
                    is_authorized=False,
                    related_invoice_id=sref.doc_number,
                )
            )

    total_gross = _q2(sum((a.gross_amount for a in allocations), Decimal("0.00")))
    total_ded = _q2(sum((d.amount for d in deductions), Decimal("0.00")))
    residual = _q2(total_gross - total_ded - tx.amount)

    unauthorized = [d for d in deductions if not d.is_authorized]
    status = "ACTION_REQUIRED_SHORT_PAY" if unauthorized or residual != Decimal("0.00") else "AUTO_RECONCILED"

    journals = _build_journal_entries(tx, cust_name, allocations, deductions, residual)
    dispute_draft = _generate_dispute_draft(tx, cust_name, unauthorized, allocations)

    summary_parts = [f"Matched {len(allocations)} structured ISO 20022 invoice block(s) totaling {tx.currency} {total_gross:,.2f}."]
    if total_ded > Decimal("0.00"):
        summary_parts.append(f"Identified {tx.currency} {total_ded:,.2f} in structured deductions or withholding.")
    if unauthorized:
        summary_parts.append(f"Flagged {tx.currency} {sum(d.amount for d in unauthorized):,.2f} in unapproved deductions.")

    return ReconciliationProposal(
        tx_id=tx.tx_id,
        status=status,
        match_method="ISO20022_STRUCTURED",
        confidence_score=99.5 if residual == Decimal("0.00") else 91.0,
        matched_customer_id=cust_id,
        matched_customer_name=cust_name,
        deposit_amount=tx.amount,
        total_gross_invoices=total_gross,
        total_deductions=total_ded,
        residual_unexplained=residual,
        allocations=allocations,
        deductions=deductions,
        journal_entries=journals,
        explanation_summary=" ".join(summary_parts),
        dispute_notice_draft=dispute_draft,
        booking_date=tx.booking_date,
        currency=tx.currency,
    )


def _evaluate_subset_candidate(
    tx: BankTransaction,
    cust_id: str,
    cust_name: str,
    subset: Tuple[OpenInvoice, ...],
    applied_memos: List[CreditMemo],
    disc_pct: Decimal,
    tds_pct: Decimal,
    wire_fee: Decimal,
    claimed_short_pay: Decimal,
    match_method: str,
) -> Optional[ReconciliationProposal]:
    """
    Checks if a specific combination of (Invoices, Credit Memos, Discount %, TDS %, Wire Fee, Short-Pay)
    equals the exact bank deposit amount down to the penny.
    """
    gross_sum = _q2(sum((inv.open_amount for inv in subset), Decimal("0.00")))
    memo_sum = _q2(sum((m.amount for m in applied_memos), Decimal("0.00")))

    # Calculate per-invoice discount and TDS so rounding matches corporate AR standards
    allocations: List[InvoiceMatchAllocation] = []
    total_disc = Decimal("0.00")
    total_tds = Decimal("0.00")

    for idx, inv in enumerate(subset):
        inv_disc = _q2(inv.open_amount * (disc_pct / Decimal("100")))
        inv_tds = _q2(inv.open_amount * (tds_pct / Decimal("100")))
        # Attach credit memos + short-pay to the last invoice in subset for clean allocation tracking
        inv_short_or_memo = (memo_sum + claimed_short_pay) if idx == len(subset) - 1 else Decimal("0.00")
        inv_net = _q2(inv.open_amount - inv_disc - inv_tds - inv_short_or_memo)
        total_disc += inv_disc
        total_tds += inv_tds
        allocations.append(
            InvoiceMatchAllocation(
                invoice_id=inv.invoice_id,
                gross_amount=inv.open_amount,
                discount_applied=inv_disc,
                tds_withheld=inv_tds,
                short_pay_or_memo=inv_short_or_memo,
                net_settled=inv_net,
            )
        )

    expected_deposit = _q2(gross_sum - total_disc - total_tds - memo_sum - claimed_short_pay - wire_fee)
    variance = abs(expected_deposit - tx.amount)

    # Require exact cent match (or <= $0.02 rounding tolerance across multi-invoice splits)
    if variance > Decimal("0.02"):
        return None

    deductions: List[DeductionLine] = []

    if total_disc > Decimal("0.00"):
        # Check if all invoices in subset actually allow this early-pay discount
        all_eligible = all(inv.eligible_discount_pct >= disc_pct for inv in subset)
        deductions.append(
            DeductionLine(
                deduction_type="EARLY_PAY_DISCOUNT",
                description=f"{disc_pct:g}% Early-Payment Cash Discount across {len(subset)} invoice(s)",
                amount=total_disc,
                gl_account_code="4090" if all_eligible else "1290",
                gl_account_name="Sales Early-Pay Discounts" if all_eligible else "AR Short-Pay Dispute Suspense",
                is_authorized=all_eligible,
            )
        )

    if total_tds > Decimal("0.00"):
        deductions.append(
            DeductionLine(
                deduction_type="TAX_WITHHOLDING_TDS",
                description=f"{tds_pct:g}% Statutory Tax Withholding (TDS/WHT) at source",
                amount=total_tds,
                gl_account_code="1150",
                gl_account_name="Prepaid Tax / TDS Receivable",
                is_authorized=True,
            )
        )

    for m in applied_memos:
        deductions.append(
            DeductionLine(
                deduction_type="CREDIT_MEMO",
                description=f"Applied Approved Credit Memo {m.memo_id} ({m.reason})",
                amount=m.amount,
                gl_account_code="2140",
                gl_account_name="Customer Credit Memos Applied",
                is_authorized=True,
                related_invoice_id=m.related_invoice_id,
                credit_memo_id=m.memo_id,
            )
        )

    if wire_fee > Decimal("0.00"):
        deductions.append(
            DeductionLine(
                deduction_type="BANK_WIRE_FEE",
                description=f"Intermediary Bank / Wire Settlement Fee ({tx.currency} {wire_fee:,.2f})",
                amount=wire_fee,
                gl_account_code="6120",
                gl_account_name="Bank & Wire Transfer Charges",
                is_authorized=True,
            )
        )

    if claimed_short_pay > Decimal("0.00"):
        rsn = tx.hints.claimed_deduction_reason or "Unapproved Short-Pay Deduction"
        deductions.append(
            DeductionLine(
                deduction_type="SHORT_PAY_DISPUTE",
                description=f"{rsn} — Flagged for Dispute Recovery",
                amount=claimed_short_pay,
                gl_account_code="1290",
                gl_account_name="AR Short-Pay Dispute Suspense",
                is_authorized=False,
                related_invoice_id=subset[-1].invoice_id,
            )
        )

    total_ded = _q2(sum((d.amount for d in deductions), Decimal("0.00")))
    residual = _q2(gross_sum - total_ded - tx.amount)

    unauthorized = [d for d in deductions if not d.is_authorized]
    status = "ACTION_REQUIRED_SHORT_PAY" if unauthorized else "AUTO_RECONCILED"

    # Compute confidence score based on evidence strength
    confidence = 99.0 if match_method in ("EXACT_SINGLE_MATCH", "HINT_GUIDED_SOLVER") else 94.5
    if wire_fee > Decimal("0.00") and tx.hints.claimed_wire_fee is None:
        confidence -= 1.5

    inv_ids_str = " + ".join(f"{i.invoice_id} ({tx.currency} {i.open_amount:,.2f})" for i in subset)
    expl = [f"Proposed {inv_ids_str}, totaling {tx.currency} {gross_sum:,.2f} before deductions."]
    if total_disc > Decimal("0.00"):
        expl.append(f"Less {disc_pct:g}% early-pay discount ({tx.currency} {total_disc:,.2f}).")
    if total_tds > Decimal("0.00"):
        expl.append(f"Less {tds_pct:g}% withholding ({tx.currency} {total_tds:,.2f}).")
    if memo_sum > Decimal("0.00"):
        expl.append(f"Less credit memo {', '.join(m.memo_id for m in applied_memos)} ({tx.currency} {memo_sum:,.2f}).")
    if claimed_short_pay > Decimal("0.00"):
        expl.append(f"Less unapproved short-pay claim ({tx.currency} {claimed_short_pay:,.2f}).")
    if wire_fee > Decimal("0.00"):
        expl.append(f"Less intermediary wire fee ({tx.currency} {wire_fee:,.2f}).")
    expl.append(f"Deposit received: {tx.currency} {tx.amount:,.2f}.")

    journals = _build_journal_entries(tx, cust_name, allocations, deductions, residual)
    dispute_draft = _generate_dispute_draft(tx, cust_name, unauthorized, allocations)

    return ReconciliationProposal(
        tx_id=tx.tx_id,
        status=status,
        match_method=match_method,
        confidence_score=confidence,
        matched_customer_id=cust_id,
        matched_customer_name=cust_name,
        deposit_amount=tx.amount,
        total_gross_invoices=gross_sum,
        total_deductions=total_ded,
        residual_unexplained=residual,
        allocations=allocations,
        deductions=deductions,
        journal_entries=journals,
        explanation_summary=" ".join(expl),
        dispute_notice_draft=dispute_draft,
        booking_date=tx.booking_date,
        currency=tx.currency,
    )


def reconcile_transaction(
    tx: BankTransaction,
    all_invoices: List[OpenInvoice],
    all_memos: List[CreditMemo],
    config: Optional[SolverConfig] = None,
) -> ReconciliationProposal:
    """
    Runs the 4-stage deterministic & combinatorial reconciliation pipeline on a single BankTransaction.
    """
    if config is None:
        config = SolverConfig()

    cust_id, cust_name, cust_invoices, cust_memos = _match_customer_invoices(tx, all_invoices, all_memos)

    # Stage 1: Check ISO 20022 <Strd> Structured Remittance blocks first
    strd_proposal = _solve_structured_iso20022(tx, cust_id, cust_name, cust_invoices)
    if strd_proposal is not None:
        return strd_proposal

    # Stage 2: Hint-Guided Solver (when <Ustrd> references specific Invoice IDs)
    if tx.hints.referenced_invoices and cust_invoices:
        inv_map = {i.invoice_id.upper(): i for i in cust_invoices}
        hinted_subset = tuple(inv_map[ref] for ref in dict.fromkeys(
            ref.upper() for ref in tx.hints.referenced_invoices
        ) if ref in inv_map)
        if hinted_subset:
            memo_map = {m.memo_id.upper(): m for m in cust_memos}
            hinted_memos = [
                memo_map[cm.upper()] for cm in tx.hints.referenced_credit_memos if cm.upper() in memo_map
            ]

            disc_candidates = (
                [tx.hints.claimed_discount_pct]
                if tx.hints.claimed_discount_pct is not None
                else config.allowed_discount_pcts
            )
            tds_candidates = (
                [tx.hints.claimed_tds_pct]
                if tx.hints.claimed_tds_pct is not None
                else config.allowed_tds_pcts
            )
            fee_candidates = (
                [tx.hints.claimed_wire_fee]
                if tx.hints.claimed_wire_fee is not None
                else config.common_wire_fees
            )
            short_pay_amt = tx.hints.claimed_deduction_amount or Decimal("0.00")

            for d_pct, t_pct, w_fee in itertools.product(disc_candidates, tds_candidates, fee_candidates):
                method = (
                    "EXACT_SINGLE_MATCH"
                    if len(hinted_subset) == 1
                    and d_pct == 0
                    and t_pct == 0
                    and w_fee == 0
                    and short_pay_amt == 0
                    and not hinted_memos
                    else "HINT_GUIDED_SOLVER"
                )
                prop = _evaluate_subset_candidate(
                    tx=tx,
                    cust_id=cust_id,
                    cust_name=cust_name,
                    subset=hinted_subset,
                    applied_memos=hinted_memos,
                    disc_pct=d_pct,
                    tds_pct=t_pct,
                    wire_fee=w_fee,
                    claimed_short_pay=short_pay_amt,
                    match_method=method,
                )
                if prop is not None:
                    return prop

    # Stage 3: Blind Constrained Subset-Sum & Deduction Solver
    # Even when the payer sends ZERO invoice numbers in the remittance text, test combinations of open invoices
    checks = 0
    if cust_invoices:
        max_k = min(len(cust_invoices), config.max_subset_size)
        memo_options = [[]] + [[m] for m in cust_memos]
        short_pay_amt = tx.hints.claimed_deduction_amount or Decimal("0.00")

        for k in range(1, max_k + 1):
            for subset in itertools.combinations(cust_invoices, k):
                # Prioritize testing customer-specific discount & TDS rates before generic tolerances
                cust_disc_options = list(
                    dict.fromkeys(
                        [Decimal("0")]
                        + [inv.eligible_discount_pct for inv in subset if inv.eligible_discount_pct > 0]
                        + config.allowed_discount_pcts
                    )
                )
                cust_tds_options = list(
                    dict.fromkeys(
                        [Decimal("0")]
                        + [inv.expected_tds_pct for inv in subset if inv.expected_tds_pct > 0]
                        + config.allowed_tds_pcts
                    )
                )

                for memos in memo_options:
                    for d_pct, t_pct, w_fee in itertools.product(
                        cust_disc_options, cust_tds_options, config.common_wire_fees
                    ):
                        if checks >= config.max_candidate_checks:
                            return _unmatched(tx, cust_id, cust_name, "Candidate search limit reached. Supply remittance references to narrow the match.")
                        checks += 1
                        prop = _evaluate_subset_candidate(
                            tx=tx,
                            cust_id=cust_id,
                            cust_name=cust_name,
                            subset=subset,
                            applied_memos=memos,
                            disc_pct=d_pct,
                            tds_pct=t_pct,
                            wire_fee=w_fee,
                            claimed_short_pay=short_pay_amt,
                            match_method="BLIND_SUBSET_SUM_SOLVER",
                        )
                        if prop is not None:
                            return prop

    return _unmatched(tx, cust_id, cust_name, "No deterministic match found within the configured policies.")


def _unmatched(tx: BankTransaction, cust_id: str, cust_name: str, explanation: str) -> ReconciliationProposal:
    suspense_journals = [
        JournalEntryLine(
            line_number=1,
            account_code="1010",
            account_name="Operating Bank Cash",
            debit=_q2(tx.amount),
            credit=Decimal("0.00"),
            memo=f"Unmatched Deposit via {tx.payment_rail}",
            entity_name=cust_name,
        ),
        JournalEntryLine(
            line_number=2,
            account_code="2199",
            account_name="Unreconciled AR Suspense Clearing",
            debit=Decimal("0.00"),
            credit=_q2(tx.amount),
            memo=f"Pending remittance clarification for {tx.tx_id}",
            entity_name=cust_name,
        ),
    ]

    return ReconciliationProposal(
        tx_id=tx.tx_id,
        status="UNMATCHED_SUSPENSE",
        match_method="UNMATCHED",
        confidence_score=0.0,
        matched_customer_id=cust_id,
        matched_customer_name=cust_name,
        deposit_amount=tx.amount,
        total_gross_invoices=Decimal("0.00"),
        total_deductions=Decimal("0.00"),
        residual_unexplained=tx.amount,
        allocations=[],
        deductions=[],
        journal_entries=suspense_journals,
        explanation_summary=explanation,
        dispute_notice_draft=None,
        booking_date=tx.booking_date,
        currency=tx.currency,
    )


def reconcile_batch(
    transactions: List[BankTransaction],
    invoices: List[OpenInvoice],
    credit_memos: List[CreditMemo],
    config: Optional[SolverConfig] = None,
) -> List[ReconciliationProposal]:
    """
    Reconciles a batch of bank transactions sequentially, removing settled invoices from the open pool
    as they are matched so duplicate allocations cannot occur.
    """
    remaining_invoices = list(invoices)
    remaining_memos = list(credit_memos)
    proposals: List[ReconciliationProposal] = []

    for tx in transactions:
        prop = reconcile_transaction(tx, remaining_invoices, remaining_memos, config=config)
        proposals.append(prop)
        if prop.status in ("AUTO_RECONCILED", "ACTION_REQUIRED_SHORT_PAY"):
            settled_ids = {a.invoice_id.upper() for a in prop.allocations}
            remaining_invoices = [i for i in remaining_invoices if i.invoice_id.upper() not in settled_ids]
            used_memo_ids = {d.credit_memo_id for d in prop.deductions if d.credit_memo_id}
            remaining_memos = [m for m in remaining_memos if m.memo_id not in used_memo_ids]

    return proposals
