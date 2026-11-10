"""Protocol parsers for ISO 20022 XML (camt.053 / pacs.008), Bank CSV, and Remittance Hints."""

from __future__ import annotations
import csv
import io
import re
import xml.etree.ElementTree as ET
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import List, Optional
from engine.models import (
    BankTransaction,
    OpenInvoice,
    CreditMemo,
    RemittanceHint,
    StructuredDocRef,
)


def _safe_decimal(val: Optional[str], default: str = "0.00") -> Decimal:
    if val is None:
        return Decimal(default)
    cleaned = re.sub(r"[^\d.\-]", "", str(val).strip())
    if not cleaned or cleaned in ("-", "."):
        return Decimal(default)
    try:
        return Decimal(cleaned).quantize(Decimal("0.01"))
    except InvalidOperation:
        return Decimal(default)


def _ledger_amount(value: str | None, label: str) -> Decimal:
    text = (value or "").strip()
    if not re.fullmatch(r"-?(?:\d+|\d{1,3}(?:,\d{3})+)(?:\.\d{1,2}0*)?", text):
        raise ValueError(f"Missing or invalid {label}. Expected a number with at most two decimal places.")
    return Decimal(text.replace(",", ""))


def extract_unstructured_remittance_hints(raw_text: str) -> RemittanceHint:
    """
    Extracts structured hints from messy 140-char ISO 20022 <Ustrd> or ACH/FedNow/SWIFT narrative blocks.
    Examples handled:
      - "PMT INV-2026-001/002/003 LESS 2% EARLY PAY DISC"
      - "SETTLEMENT INV-2026-004, INV-2026-005 APPLY CM-501 LESS DMG 450.00"
      - "INV-2026-006 INV-2026-007 LESS 10% TDS AND 25.00 SWIFT FEE"
    """
    hint = RemittanceHint()
    if not raw_text:
        return hint

    text_upper = raw_text.upper()

    # 1. Extract slash-expanded invoice sequences like INV-2026-001/002/003 or INV101/102
    slash_pattern = re.compile(r"\b(INV[-_]?(?:\d{4}[-_])?)(\d{2,6})((?:/\d{2,6})+)\b")
    for match in slash_pattern.finditer(text_upper):
        prefix, first_num, rest_slash = match.groups()
        first_id = f"{prefix}{first_num}".replace("_", "-")
        if not first_id.startswith("INV-"):
            first_id = "INV-" + first_id[3:]
        if first_id not in hint.referenced_invoices:
            hint.referenced_invoices.append(first_id)
        for sub_num in rest_slash.strip("/").split("/"):
            padded = sub_num.zfill(len(first_num))
            expanded_id = f"{prefix}{padded}".replace("_", "-")
            if not expanded_id.startswith("INV-"):
                expanded_id = "INV-" + expanded_id[3:]
            if expanded_id not in hint.referenced_invoices:
                hint.referenced_invoices.append(expanded_id)

    # 2. Extract standalone invoice tokens like INV-2026-004, INV-1001, INV1004
    inv_pattern = re.compile(r"\bINV[-_]?(\d{4}[-_]\d{2,6}|\d{3,8})\b")
    for match in inv_pattern.finditer(text_upper):
        norm_id = f"INV-{match.group(1).replace('_', '-')}"
        if norm_id not in hint.referenced_invoices:
            hint.referenced_invoices.append(norm_id)

    # 3. Extract Credit Memo references like CM-501, CN-201
    cm_pattern = re.compile(r"\b(?:CM|CN|CR)[- _]?(\d{2,6})\b")
    for match in cm_pattern.finditer(text_upper):
        cm_id = f"CM-{match.group(1)}"
        if cm_id not in hint.referenced_credit_memos:
            hint.referenced_credit_memos.append(cm_id)

    # 4. Extract Early-Pay Discount % (e.g., "2% EARLY PAY", "2PCT DISC", "DISC 2%")
    disc_pct_match = re.search(
        r"(?:(\d+(?:\.\d+)?)\s*(?:%|PCT)\s*(?:EARLY\s*PAY\s*)?(?:DISC|DSCNT)|(?:DISC|DSCNT)\s*(\d+(?:\.\d+)?)\s*(?:%|PCT))",
        text_upper,
    )
    if disc_pct_match:
        pct_str = disc_pct_match.group(1) or disc_pct_match.group(2)
        hint.claimed_discount_pct = _safe_decimal(pct_str)

    # 5. Extract TDS / Withholding Tax % (e.g., "10% TDS", "TDS 2%", "WHT 10PCT", "TDS @ 10%")
    tds_pct_match = re.search(
        r"(?:(\d+(?:\.\d+)?)\s*(?:%|PCT)\s*(?:TDS|WHT|TAX)|(?:TDS|WHT|WITHHOLDING)\s*(?:@|AT)?\s*(\d+(?:\.\d+)?)\s*(?:%|PCT))",
        text_upper,
    )
    if tds_pct_match:
        pct_str = tds_pct_match.group(1) or tds_pct_match.group(2)
        hint.claimed_tds_pct = _safe_decimal(pct_str)

    # 6. Extract Wire / Bank Fee amount (e.g., "25.00 SWIFT FEE", "WIRE FEE $15", "BANK CHG 25")
    fee_match = re.search(
        r"(?:(\d+(?:\.\d{1,2})?)\s*(?:USD|\$)?\s*(?:SWIFT|WIRE|BANK)\s*(?:FEE|CHG|CHARGES)|(?:SWIFT|WIRE|BANK)\s*(?:FEE|CHG|CHARGES)\s*(?:USD|\$)?\s*(\d+(?:\.\d{1,2})?))",
        text_upper,
    )
    if fee_match:
        fee_str = fee_match.group(1) or fee_match.group(2)
        hint.claimed_wire_fee = _safe_decimal(fee_str)

    # 7. Extract Short-Pay / Damage / Shortage Deduction amount (e.g., "DMG 450.00", "SHORTAGE $320", "DEDUCT 450 FOR DAMAGED")
    dmg_match = re.search(
        r"(?:(DMG|DAMAGE|DAMAGED|SHORT|SHORTAGE|DEFECT|CLAIM|DEDUCT)\s*(?:GOODS|CRATES|UNITS)?\s*(?:USD|\$)?\s*(\d+(?:\.\d{1,2})?))",
        text_upper,
    )
    if dmg_match:
        reason_token, amt_str = dmg_match.groups()
        hint.claimed_deduction_amount = _safe_decimal(amt_str)
        hint.claimed_deduction_reason = f"Customer Claim ({reason_token.title()})"

    return hint


def _strip_ns(tag: str) -> str:
    if "}" in tag:
        return tag.split("}", 1)[1]
    return tag


def _find_child_text(elem: ET.Element, path_tags: List[str]) -> Optional[str]:
    curr = [elem]
    for target in path_tags:
        next_level = []
        for node in curr:
            for child in node:
                if _strip_ns(child.tag) == target:
                    next_level.append(child)
        curr = next_level
        if not curr:
            return None
    return (curr[0].text or "").strip() if curr[0].text else None


def _find_children(elem: ET.Element, tag_name: str) -> List[ET.Element]:
    return [c for c in elem.iter() if _strip_ns(c.tag) == tag_name]


def parse_iso20022_xml(xml_content: str) -> List[BankTransaction]:
    """
    Parses ISO 20022 camt.053 (BankToCustomerStatement) or pacs.008 (FIToFICustomerCreditTransfer)
    into normalized BankTransaction objects with full structured (<Strd>) and unstructured (<Ustrd>) hints.
    """
    root = ET.fromstring(xml_content.strip())
    transactions: List[BankTransaction] = []

    # Locate all <Ntry> (camt.053/054) or <CdtTrfTxInf> (pacs.008) nodes
    entry_nodes = [e for e in root.iter() if _strip_ns(e.tag) == "Ntry"]
    if not entry_nodes:
        entry_nodes = [e for e in root.iter() if _strip_ns(e.tag) == "CdtTrfTxInf"]

    for idx, ntry in enumerate(entry_nodes, start=1):
        # Skip Debit entries if CdtDbtInd is DBIT
        cdt_dbt = _find_child_text(ntry, ["CdtDbtInd"])
        if cdt_dbt and cdt_dbt.upper() == "DBIT":
            continue

        # Extract amount and currency
        amt_node = None
        for child in ntry:
            if _strip_ns(child.tag) in ("Amt", "IntrBkSttlmAmt"):
                amt_node = child
                break
        if amt_node is None:
            amt_nodes = _find_children(ntry, "Amt")
            amt_node = amt_nodes[0] if amt_nodes else None

        amount = _ledger_amount(amt_node.text if amt_node is not None else None, "ISO 20022 amount")
        currency = (amt_node.attrib.get("Ccy", "") if amt_node is not None else "").upper()

        # Extract transaction ID / reference
        tx_id = (
            _find_child_text(ntry, ["NtryRef"])
            or _find_child_text(ntry, ["AcctSvcrRef"])
            or _find_child_text(ntry, ["PmtId", "EndToEndId"])
            or _find_child_text(ntry, ["NtryDtls", "TxDtls", "Refs", "EndToEndId"])
            or f"TX-ISO-{idx:03d}"
        )

        bank_ref = (
            _find_child_text(ntry, ["AcctSvcrRef"])
            or _find_child_text(ntry, ["NtryDtls", "TxDtls", "Refs", "TxId"])
            or tx_id
        )

        # Extract booking date
        booking_date = (
            _find_child_text(ntry, ["BookgDt", "Dt"])
            or _find_child_text(ntry, ["BookgDt", "DtTm"])
            or _find_child_text(ntry, ["ValDt", "Dt"])
            or _find_child_text(ntry, ["IntrBkSttlmDt"])
            or ""
        ).split("T", 1)[0]

        # Extract Payer / Debtor Name
        payer_name = (
            _find_child_text(ntry, ["NtryDtls", "TxDtls", "RltdPties", "Dbtr", "Nm"])
            or _find_child_text(ntry, ["NtryDtls", "TxDtls", "RltdPties", "Dbtr", "Pty", "Nm"])
            or _find_child_text(ntry, ["Dbtr", "Nm"])
            or "Unknown Payer"
        )

        # Extract Payment Rail / Proprietary Code
        rail = (
            _find_child_text(ntry, ["BkTxCd", "Prtry", "Cd"])
            or _find_child_text(ntry, ["NtryDtls", "TxDtls", "BkTxCd", "Prtry", "Cd"])
            or "ISO20022_CAMT053"
        )

        # Extract Unstructured (<Ustrd>) strings
        ustrd_nodes = _find_children(ntry, "Ustrd")
        ustrd_text = " | ".join((u.text or "").strip() for u in ustrd_nodes if u.text and u.text.strip())

        hints = extract_unstructured_remittance_hints(ustrd_text)

        # Extract Structured (<Strd>) remittance blocks
        strd_nodes = _find_children(ntry, "Strd")
        for strd in strd_nodes:
            doc_nb = _find_child_text(strd, ["RfrdDocInf", "Nb"])
            doc_cd = _find_child_text(strd, ["RfrdDocInf", "Tp", "CdOrPrtry", "Cd"]) or "CINV"
            due_amt = _find_child_text(strd, ["RfrdDocAmt", "DuePyblAmt"])
            rmtd_amt = _find_child_text(strd, ["RfrdDocAmt", "RmtdAmt"])
            dscnt_amt = _find_child_text(strd, ["RfrdDocAmt", "DscntApldAmt", "Amt"]) or _find_child_text(
                strd, ["RfrdDocAmt", "DscntApldAmt"]
            )
            tax_amt = _find_child_text(strd, ["RfrdDocAmt", "TaxAmt", "Amt"]) or _find_child_text(
                strd, ["RfrdDocAmt", "TaxAmt"]
            )
            adj_amt = _find_child_text(strd, ["RfrdDocAmt", "AdjstmntAmtAndRsn", "Amt"])
            adj_rsn = _find_child_text(strd, ["RfrdDocAmt", "AdjstmntAmtAndRsn", "AddtlInf"]) or _find_child_text(
                strd, ["RfrdDocAmt", "AdjstmntAmtAndRsn", "Rsn"]
            )

            if doc_nb:
                ref = StructuredDocRef(
                    doc_type=doc_cd,
                    doc_number=doc_nb,
                    invoiced_amount=_safe_decimal(due_amt) if due_amt else None,
                    paid_amount=_safe_decimal(rmtd_amt) if rmtd_amt else None,
                    discount_amount=_safe_decimal(dscnt_amt) if dscnt_amt else None,
                    tax_withheld_amount=_safe_decimal(tax_amt) if tax_amt else None,
                    adjustment_amount=_safe_decimal(adj_amt) if adj_amt else None,
                    adjustment_reason=adj_rsn,
                )
                hints.structured_refs.append(ref)
                if doc_cd == "CREN" or doc_nb.upper().startswith("CM-"):
                    if doc_nb not in hints.referenced_credit_memos:
                        hints.referenced_credit_memos.append(doc_nb)
                else:
                    if doc_nb not in hints.referenced_invoices:
                        hints.referenced_invoices.append(doc_nb)

        transactions.append(
            BankTransaction(
                tx_id=tx_id,
                booking_date=booking_date,
                payer_name=payer_name,
                amount=amount,
                currency=currency,
                payment_rail=rail,
                bank_reference=bank_ref,
                raw_remittance_unstructured=ustrd_text,
                hints=hints,
            )
        )

    return transactions


def parse_bank_csv(csv_content: str) -> List[BankTransaction]:
    """Parses a standard Bank Statement CSV into BankTransaction records."""
    reader = csv.DictReader(io.StringIO(csv_content.strip()))
    transactions: List[BankTransaction] = []
    for idx, row in enumerate(reader, start=1):
        tx_id = (row.get("tx_id") or row.get("Transaction ID") or f"TX-CSV-{idx:03d}").strip()
        booking_date = (row.get("booking_date") or row.get("Date") or "").strip()
        payer_name = (row.get("payer_name") or row.get("Payer") or row.get("Counterparty") or "Unknown").strip()
        amount = _ledger_amount(row.get("amount") or row.get("Amount"), f"bank CSV amount at row {idx}")
        if amount <= 0:
            continue
        currency = (row.get("currency") or row.get("Currency") or "").strip().upper()
        rail = (row.get("payment_rail") or row.get("Rail") or "BANK_CSV").strip()
        bank_ref = (row.get("bank_reference") or row.get("Reference") or tx_id).strip()
        ustrd = (row.get("remittance_info") or row.get("Description") or row.get("Narrative") or "").strip()

        hints = extract_unstructured_remittance_hints(ustrd)
        transactions.append(
            BankTransaction(
                tx_id=tx_id,
                booking_date=booking_date,
                payer_name=payer_name,
                amount=amount,
                currency=currency,
                payment_rail=rail,
                bank_reference=bank_ref,
                raw_remittance_unstructured=ustrd,
                hints=hints,
            )
        )
    return transactions


def parse_mt940_statement(mt940_content: str) -> List[BankTransaction]:
    """
    Parses SWIFT MT940 Customer Statement Messages (:61: Statement Line + :86: Information to Account Owner).
    """
    transactions: List[BankTransaction] = []
    lines = mt940_content.strip().splitlines()
    current_61: Optional[str] = None
    current_86_lines: List[str] = []
    tx_counter = 1
    currency = ""

    def _flush_entry(line_61: str, lines_86: List[str], idx: int) -> Optional[BankTransaction]:
        # :61:2611101110C28910,00NTRFFEDNOW-9981201//TX-101
        m = re.search(r":61:(\d{6})(?:\d{4})?(C|D|RC|RD)([0-9,\.]+)([A-Z0-9]{4})([^\r\n]*)", line_61)
        if not m:
            return None
        yymmdd, cdt_dbt, amt_str, swift_code, refs = m.groups()
        if cdt_dbt in {"D", "RC"}:
            return None  # Skip debits
        booking_date = datetime.strptime(yymmdd, "%y%m%d").date().isoformat()
        amount = _safe_decimal(amt_str.replace(",", "."))
        ref_parts = refs.split("//")
        bank_ref = ref_parts[0].strip() or f"MT940-{idx:03d}"
        tx_id = ref_parts[1].strip() if len(ref_parts) > 1 and ref_parts[1].strip() else f"TX-MT940-{idx:03d}"

        raw_86 = " ".join(l.strip() for l in lines_86).strip()
        raw_86 = re.sub(r"^:86:", "", raw_86).strip()

        # Extract /ORDP/ or Payer Name if structured, otherwise before first keyword
        payer_match = re.search(r"(?:/ORDP/|/NAME/|FROM\s+)([^/\|]+)", raw_86, re.IGNORECASE)
        payer_name = payer_match.group(1).strip() if payer_match else "MT940 Counterparty"

        hints = extract_unstructured_remittance_hints(raw_86)
        return BankTransaction(
            tx_id=tx_id,
            booking_date=booking_date,
            payer_name=payer_name,
            amount=amount,
            currency=currency,
            payment_rail=f"MT940_{swift_code}",
            bank_reference=bank_ref,
            raw_remittance_unstructured=raw_86,
            hints=hints,
        )

    for line in lines:
        opening = re.match(r":60[FM]:[CD]\d{6}([A-Z]{3})", line)
        if line.startswith((":61:", ":20:", ":62F:", ":62M:")) or opening:
            if current_61 is not None:
                tx = _flush_entry(current_61, current_86_lines, tx_counter)
                if tx:
                    transactions.append(tx)
                    tx_counter += 1
            current_61 = line if line.startswith(":61:") else None
            current_86_lines = []
            if opening:
                currency = opening[1]
            elif line.startswith(":20:"):
                currency = ""
        elif line.startswith(":86:") or (current_86_lines and not line.startswith(":")):
            current_86_lines.append(line)

    if current_61 is not None:
        tx = _flush_entry(current_61, current_86_lines, tx_counter)
        if tx:
            transactions.append(tx)

    return transactions


def parse_bai2_statement(bai2_content: str) -> List[BankTransaction]:
    """
    Parses BAI2 Cash Management files:
      16,<code>,<amount_in_cents>,... (Transaction Detail)
      88,<remittance continuation text>
    """
    transactions: List[BankTransaction] = []
    lines = [l.strip() for l in bai2_content.strip().splitlines() if l.strip()]
    current_16: Optional[List[str]] = None
    current_88: List[str] = []
    tx_counter = 1
    booking_date = ""
    group_currency = ""
    currency = ""

    def _flush_bai2(fields_16: List[str], lines_88: List[str], idx: int) -> Optional[BankTransaction]:
        # Example: 16,165,2891000,Z,FEDNOW-9981201,TX-101/
        if len(fields_16) < 3:
            return None
        type_code = fields_16[1].strip()
        if not type_code.isdigit() or not 100 <= int(type_code) < 400:
            return None
        cents_str = fields_16[2].strip()
        if not cents_str.isascii() or not cents_str.isdigit():
            raise ValueError(f"Invalid BAI2 credit amount at transaction {idx}.")
        amount = Decimal(cents_str).scaleb(-2)
        bank_ref = fields_16[4].strip().rstrip("/") if len(fields_16) > 4 else f"BAI2-{idx:03d}"
        tx_id = fields_16[5].strip().rstrip("/") if len(fields_16) > 5 else ""
        tx_id = tx_id or f"TX-BAI2-{idx:03d}"

        remit_text = " ".join(lines_88).strip()
        payer_match = re.search(r"PAYER[:=]\s*([^\|;]+)", remit_text, re.IGNORECASE)
        payer_name = payer_match.group(1).strip() if payer_match else "BAI2 Commercial Payer"
        hints = extract_unstructured_remittance_hints(remit_text)

        return BankTransaction(
            tx_id=tx_id,
            booking_date=booking_date,
            payer_name=payer_name,
            amount=amount,
            currency=currency,
            payment_rail=f"BAI2_CODE_{type_code}",
            bank_reference=bank_ref,
            raw_remittance_unstructured=remit_text,
            hints=hints,
        )

    for line in lines:
        if line.startswith(("02,", "03,", "16,", "49,", "98,")):
            if current_16 is not None:
                tx = _flush_bai2(current_16, current_88, tx_counter)
                if tx:
                    transactions.append(tx)
                    tx_counter += 1
            fields = line.rstrip("/").split(",")
            current_16 = fields if fields[0] == "16" else None
            current_88 = []
            if fields[0] == "02":
                as_of = fields[4] if len(fields) > 4 else ""
                booking_date = datetime.strptime(as_of, "%y%m%d").date().isoformat() if as_of else ""
                group_currency = fields[6] if len(fields) > 6 else ""
                currency = group_currency
            elif fields[0] == "03":
                currency = (fields[2] if len(fields) > 2 else "") or group_currency
        elif line.startswith("88,") and current_16 is not None:
            current_88.append(line[3:].rstrip("/").strip())

    if current_16 is not None:
        tx = _flush_bai2(current_16, current_88, tx_counter)
        if tx:
            transactions.append(tx)

    return transactions


def detect_and_parse_statement(content: str, format_hint: str = "AUTO") -> List[BankTransaction]:
    """Auto-detects and parses ISO 20022 XML, SWIFT MT940, BAI2, or Bank CSV."""
    stripped = content.lstrip("\ufeff \r\n\t")
    fmt = format_hint.upper()
    if fmt == "ISO20022_XML" or (fmt == "AUTO" and stripped.startswith("<")):
        return parse_iso20022_xml(stripped)
    if fmt == "MT940" or (fmt == "AUTO" and (":61:" in stripped or stripped.startswith(":20:"))):
        return parse_mt940_statement(stripped)
    if fmt == "BAI2" or (fmt == "AUTO" and (stripped.startswith(("01,", "16,")) or "\n16," in stripped)):
        return parse_bai2_statement(stripped)
    return parse_bank_csv(stripped)


def add_ledger_references(hint: RemittanceHint, text: str, invoice_ids: set[str], memo_ids: set[str]) -> None:
    """Recognize organization-specific IDs in addition to the common INV and CM patterns."""
    tokens = list(dict.fromkeys(re.findall(r"[\w]+(?:[.-][\w]+)*", text.upper())))
    for token in tokens:
        if not (any(c.isalpha() for c in token) and any(c.isdigit() for c in token)):
            continue
        if token in invoice_ids and token not in hint.referenced_invoices:
            hint.referenced_invoices.append(token)
        if token in memo_ids and token not in hint.referenced_credit_memos:
            hint.referenced_credit_memos.append(token)


def enrich_transactions_with_remittance_emails(
    transactions: List[BankTransaction],
    remittance_email_text: str,
    *,
    invoice_ids: set[str] | None = None,
    memo_ids: set[str] | None = None,
) -> None:
    """
    Parses decoupled email / PDF OCR remittance advice blocks (separated by '---') and merges
    their extracted invoice/discount/deduction hints into matching bank transactions.
    """
    if not remittance_email_text or not remittance_email_text.strip():
        return

    blocks = [b.strip() for b in re.split(r"-{3,}", remittance_email_text) if b.strip()]
    for block in blocks:
        block_hints = extract_unstructured_remittance_hints(block)
        block_upper = block.upper()
        add_ledger_references(block_hints, block, invoice_ids or set(), memo_ids or set())
        references = set(re.findall(r"[\w]+(?:[.-][\w]+)*", block_upper))
        matched = [tx for tx in transactions if tx.tx_id.upper() in references
                   or (tx.bank_reference and tx.bank_reference.upper() in references)]
        if not matched:
            matched = [tx for tx in transactions if len(tx.payer_name) >= 4 and tx.payer_name.upper() in block_upper]
        if len(matched) != 1:
            continue
        tx = matched[0]
        for inv_id in block_hints.referenced_invoices:
            if inv_id not in tx.hints.referenced_invoices:
                tx.hints.referenced_invoices.append(inv_id)
        for cm_id in block_hints.referenced_credit_memos:
            if cm_id not in tx.hints.referenced_credit_memos:
                tx.hints.referenced_credit_memos.append(cm_id)
        if block_hints.claimed_discount_pct is not None and tx.hints.claimed_discount_pct is None:
            tx.hints.claimed_discount_pct = block_hints.claimed_discount_pct
        if block_hints.claimed_tds_pct is not None and tx.hints.claimed_tds_pct is None:
            tx.hints.claimed_tds_pct = block_hints.claimed_tds_pct
        if block_hints.claimed_wire_fee is not None and tx.hints.claimed_wire_fee is None:
            tx.hints.claimed_wire_fee = block_hints.claimed_wire_fee
        if block_hints.claimed_deduction_amount is not None and tx.hints.claimed_deduction_amount is None:
            tx.hints.claimed_deduction_amount = block_hints.claimed_deduction_amount
            tx.hints.claimed_deduction_reason = block_hints.claimed_deduction_reason
        tx.raw_remittance_unstructured = (
            f"{tx.raw_remittance_unstructured} [EMAIL-ENRICHED: {block[:90]}...]"
        ).strip()


def parse_invoices_csv(csv_content: str) -> List[OpenInvoice]:
    """Parses Open Accounts Receivable (AR) Invoice Ledger CSV."""
    reader = csv.DictReader(io.StringIO(csv_content.strip().lstrip("\ufeff")))
    invoices: List[OpenInvoice] = []
    for index, row in enumerate(reader, 1):
        gross = _ledger_amount(row.get("gross_amount") or row.get("Amount"), f"invoice gross amount at row {index}")
        open_amt = _ledger_amount(row.get("open_amount") or row.get("Open Balance") or str(gross), f"open balance at row {index}")
        invoices.append(
            OpenInvoice(
                invoice_id=(row.get("invoice_id") or row.get("Invoice ID") or "").strip(),
                customer_id=(row.get("customer_id") or row.get("Customer ID") or "").strip(),
                customer_name=(row.get("customer_name") or row.get("Customer Name") or "").strip(),
                issue_date=(row.get("issue_date") or "").strip(),
                due_date=(row.get("due_date") or "").strip(),
                gross_amount=gross,
                open_amount=open_amt,
                currency=(row.get("currency") or "").strip().upper(),
                payment_terms=(row.get("payment_terms") or "").strip(),
                eligible_discount_pct=_ledger_amount(row.get("eligible_discount_pct") or "0", f"discount rate at invoice row {index}"),
                expected_tds_pct=_ledger_amount(row.get("expected_tds_pct") or "0", f"withholding rate at invoice row {index}"),
                po_number=(row.get("po_number") or "").strip() or None,
            )
        )
    return invoices


def parse_credit_memos_csv(csv_content: str) -> List[CreditMemo]:
    """Parses Open Credit Memos CSV."""
    reader = csv.DictReader(io.StringIO(csv_content.strip().lstrip("\ufeff")))
    memos: List[CreditMemo] = []
    for index, row in enumerate(reader, 1):
        memos.append(
            CreditMemo(
                memo_id=(row.get("memo_id") or "").strip(),
                customer_id=(row.get("customer_id") or "").strip(),
                customer_name=(row.get("customer_name") or "").strip(),
                amount=_ledger_amount(row.get("amount"), f"credit memo amount at row {index}"),
                reason=(row.get("reason") or "Credit Note").strip(),
                related_invoice_id=(row.get("related_invoice_id") or "").strip() or None,
                currency=(row.get("currency") or "").strip().upper(),
            )
        )
    return memos
