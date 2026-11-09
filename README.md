# ClearRemit v2.0 — ISO 20022 / MT940 / BAI2 B2B Short-Pay & DTAA Tax Reconciliation Suite

**ClearRemit** is a zero-license, non-custodial B2B Accounts Receivable (AR) reconciliation and cross-border tax-withholding validation engine designed for mid-market CFOs, wholesale distributors, cross-border service exporters, and outsourced bookkeeping/CPA firms.

---

## Key Capabilities (v2.0 Upgrade)

1. **Universal Banking Protocol Ingestion (`engine/parsers.py`)**
   * **ISO 20022 XML:** Native support for `camt.053` (Bank-to-Customer Statement) and `pacs.008`, extracting both structured (`<Strd><RfrdDocInf>`) and messy 140-character unstructured (`<Ustrd>`) remittance tags.
   * **SWIFT MT940:** Parses `:61:` statement lines and `:86:` multi-line remittance narratives.
   * **BAI2 Cash Management Files:** Parses `16,` credit detail records and `88,` continuation records.
   * **Bank CSV & Decoupled AP Remittance Emails:** Links external email/OCR remittance advices to "blind" bank wires automatically.

2. **4-Stage Deterministic & Combinatorial Short-Pay Solver (`engine/solver.py`)**
   * **Stage 1:** ISO 20022 `<Strd>` document allocation & deduction verification.
   * **Stage 2:** Hint-guided multi-invoice + discount + TDS + credit-memo + wire-fee solver.
   * **Stage 3:** **Blind Constrained Subset-Sum Solver** — cracks lump-sum deposits with *zero* invoice references down to the exact cent across open customer invoices, early-pay discounts (`2/10 Net 30`), statutory tax withholdings (`TDS/WHT`), credit memos, and intermediary wire fees.
   * **Stage 4:** **Automated Dispute Recovery Drafting** — flags unauthorized short-pays (e.g., unapproved damage claims or SLA penalties) and drafts ready-to-send customer recovery notices.

3. **Embedded Cross-Border DTAA & W-8BEN-E / Form 10F Tax Validator (`engine/tax_treaty.py`)**
   * Audits foreign tax withholdings across major bilateral corridors (`IN-US`, `US-IN`, `GB-US`, `DE-US`, `SG-US`, `CA-US`) for SaaS, Royalties, and Technical Services (FTS).
   * Flags excess penalty over-withholding (e.g., 20% or 30% statutory penalties when `IRS Form 6166`, `W-8BEN-E`, or `Form 10F` is missing) and identifies the required Foreign Tax Credit (`IRS Form 1118` / `India Form 67`) documentation.

4. **Balanced Double-Entry GL Exports (`engine/exporters.py`)**
   * Guarantees `Total Debits == Total Credits` down to the cent on every transaction.
   * 1-click export to **QuickBooks CSV**, **Xero Manual Journal CSV**, **Oracle NetSuite CSV**, and **Tally Prime Voucher XML**.

---

## Quick Start

### 1. Run the Interactive Web Workbench
```powershell
uvicorn app:app --host 127.0.0.1 --port 8000 --reload
```
Then open `http://127.0.0.1:8000` in your browser.

### 2. Run the Automated Test Suite
```powershell
python -m unittest discover -s tests -v
```
