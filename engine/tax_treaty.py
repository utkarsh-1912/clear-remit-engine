"""Cross-Border Bilateral Tax Treaty (DTAA) & Statutory Withholding (TDS/WHT) Validator."""

from __future__ import annotations
from dataclasses import dataclass, asdict
from decimal import Decimal
from typing import Dict, List, Any


@dataclass
class TreatyRule:
    corridor_code: str  # e.g., "IN-US", "DE-US", "GB-US", "SG-US", "CA-US", "BR-US"
    payer_country: str
    payee_country: str
    treaty_article: str
    service_category: str  # "SAAS_CLOUD", "TECHNICAL_SERVICES_FTS", "ROYALTY_IP", "PROFESSIONAL_SERVICES"
    treaty_wht_pct: Decimal
    statutory_default_pct: Decimal  # Rate if W-8BEN-E / TRC / Form 10F is missing
    required_forms: List[str]
    foreign_tax_credit_form: str
    notes: str

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["treaty_wht_pct"] = float(self.treaty_wht_pct)
        d["statutory_default_pct"] = float(self.statutory_default_pct)
        return d


@dataclass
class TaxWithholdingAuditResult:
    corridor_code: str
    service_category: str
    gross_invoice_amount: Decimal
    actual_withheld_amount: Decimal
    actual_withheld_pct: Decimal
    expected_treaty_pct: Decimal
    expected_treaty_amount: Decimal
    excess_overwithheld_amount: Decimal
    status: str  # "COMPLIANT_TREATY_RATE", "OVERWITHHELD_MISSING_DOCS", "UNDERWITHHELD_AUDIT_RISK"
    required_forms: List[str]
    ftc_claim_form: str
    recommendation: str

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        for k, v in d.items():
            if isinstance(v, Decimal):
                d[k] = float(v)
        return d


# Public-Domain Bilateral DTAA Withholding Reference Table (2026)
DTAA_TREATY_TABLE: List[TreatyRule] = [
    TreatyRule(
        corridor_code="IN-US",
        payer_country="India",
        payee_country="United States",
        treaty_article="Article 12 (Royalties & Fees for Included Services)",
        service_category="TECHNICAL_SERVICES_FTS",
        treaty_wht_pct=Decimal("10.00"),
        statutory_default_pct=Decimal("20.00"),
        required_forms=["IRS Form 6166 (US TRC)", "India Form 10F (Electronic)", "No-PE Declaration"],
        foreign_tax_credit_form="IRS Form 1118 / Form 1116 (supported by India Form 16A)",
        notes="Finance Act 10%/20% IT Act Sec 115A vs DTAA 15% cap; 10% Domestic TDS Sec 194J often applied on technical services.",
    ),
    TreatyRule(
        corridor_code="IN-US",
        payer_country="India",
        payee_country="United States",
        treaty_article="Article 7 / Article 12 (Standard B2B SaaS without Make-Available)",
        service_category="SAAS_CLOUD",
        treaty_wht_pct=Decimal("0.00"),
        statutory_default_pct=Decimal("10.00"),
        required_forms=["IRS Form 6166 (US TRC)", "Form 10F", "Non-Make-Available SaaS Certificate"],
        foreign_tax_credit_form="IRS Form 1118 (Note: IRS limits FTC on non-compulsory foreign withholding)",
        notes="Pure copyrighted article / standard SaaS without transfer of underlying IP is 0% under DTAA if TRC + Form 10F provided.",
    ),
    TreatyRule(
        corridor_code="US-IN",
        payer_country="United States",
        payee_country="India",
        treaty_article="IRC Sec 1441/1442 & US-India DTAA Article 7/12",
        service_category="PROFESSIONAL_SERVICES",
        treaty_wht_pct=Decimal("0.00"),
        statutory_default_pct=Decimal("30.00"),
        required_forms=["IRS Form W-8BEN-E (Part III LOB Clause Checked)", "Foreign TIN / PAN"],
        foreign_tax_credit_form="India Form 67 (Rule 128 FTC)",
        notes="Services performed 100% outside the US are foreign-source (0% US WHT) with valid W-8BEN-E; 30% penalty applies if W-8BEN-E is missing.",
    ),
    TreatyRule(
        corridor_code="GB-US",
        payer_country="United Kingdom",
        payee_country="United States",
        treaty_article="US-UK Tax Treaty Article 12 (Royalties) & Article 7 (Business Profits)",
        service_category="ROYALTY_IP",
        treaty_wht_pct=Decimal("0.00"),
        statutory_default_pct=Decimal("20.00"),
        required_forms=["UK HMRC Treaty Passport / US Form 6166"],
        foreign_tax_credit_form="IRS Form 1118",
        notes="US-UK Treaty reduces royalty and software licensing withholding from 20% UK domestic rate to 0%.",
    ),
    TreatyRule(
        corridor_code="DE-US",
        payer_country="Germany",
        payee_country="United States",
        treaty_article="US-Germany Tax Treaty Article 12",
        service_category="ROYALTY_IP",
        treaty_wht_pct=Decimal("0.00"),
        statutory_default_pct=Decimal("15.82"),
        required_forms=["BZSt Freistellungsbescheinigung (Exemption Certificate)", "US Form 6166"],
        foreign_tax_credit_form="IRS Form 1118",
        notes="German Sec 50a EStG imposes 15.825% WHT unless BZSt exemption certificate is active prior to invoice payout.",
    ),
    TreatyRule(
        corridor_code="SG-US",
        payer_country="Singapore",
        payee_country="United States",
        treaty_article="Singapore ITA Sec 45 (No US-SG Comprehensive Treaty)",
        service_category="TECHNICAL_SERVICES_FTS",
        treaty_wht_pct=Decimal("10.00"),
        statutory_default_pct=Decimal("17.00"),
        required_forms=["IRAS S45 E-Filing Confirmation", "Offshore Service Declaration"],
        foreign_tax_credit_form="IRS Form 1118",
        notes="10% on royalties/know-how; 17% prevailing corporate rate on onshore technical services unless performed 100% offshore (0%).",
    ),
    TreatyRule(
        corridor_code="CA-US",
        payer_country="Canada",
        payee_country="United States",
        treaty_article="US-Canada Tax Convention Article XII & Regulation 105",
        service_category="PROFESSIONAL_SERVICES",
        treaty_wht_pct=Decimal("0.00"),
        statutory_default_pct=Decimal("15.00"),
        required_forms=["CRA Form NR301", "Regulation 105 Waiver (if physical presence in Canada)"],
        foreign_tax_credit_form="IRS Form 1118",
        notes="0% on cross-border remote software/royalties under Article XII; 15% Reg 105 applies only to physical services rendered inside Canada.",
    ),
]


def evaluate_withholding_compliance(
    corridor_code: str,
    service_category: str,
    gross_amount: Decimal,
    withheld_amount: Decimal,
) -> TaxWithholdingAuditResult:
    """
    Validates whether a cross-border tax deduction matches statutory DTAA rules or represents
    excess penalty withholding that can be recovered/avoided.
    """
    rule = next((candidate for candidate in DTAA_TREATY_TABLE
                 if candidate.corridor_code == corridor_code.upper()
                 and candidate.service_category == service_category.upper()), None)
    if rule is None:
        raise ValueError("Unsupported corridor and service category combination.")

    actual_pct = (
        ((withheld_amount / gross_amount) * Decimal("100")).quantize(Decimal("0.01"))
        if gross_amount > 0
        else Decimal("0.00")
    )
    expected_amt = (gross_amount * (rule.treaty_wht_pct / Decimal("100"))).quantize(Decimal("0.01"))
    excess_amt = max(Decimal("0.00"), (withheld_amount - expected_amt).quantize(Decimal("0.01")))

    if abs(actual_pct - rule.treaty_wht_pct) <= Decimal("0.25"):
        status = "COMPLIANT_TREATY_RATE"
        rec = (
            f"Withheld rate ({actual_pct:g}%) matches {rule.corridor_code} treaty rate ({rule.treaty_wht_pct:g}%). "
            f"Review the applicable documentation, including {rule.foreign_tax_credit_form}."
        )
    elif actual_pct > rule.treaty_wht_pct:
        status = "OVERWITHHELD_MISSING_DOCS"
        rec = (
            f"Withholding of {actual_pct:g}% exceeds the configured reference of {rule.treaty_wht_pct:g}%. "
            f"Review the transaction and supporting documents: {', '.join(rule.required_forms)}."
        )
    else:
        status = "UNDERWITHHELD_AUDIT_RISK"
        rec = (
            f"Withholding of {actual_pct:g}% is below the configured reference of {rule.treaty_wht_pct:g}%. "
            f"Review the transaction and supporting documents: {', '.join(rule.required_forms)}."
        )

    return TaxWithholdingAuditResult(
        corridor_code=rule.corridor_code,
        service_category=rule.service_category,
        gross_invoice_amount=gross_amount,
        actual_withheld_amount=withheld_amount,
        actual_withheld_pct=actual_pct,
        expected_treaty_pct=rule.treaty_wht_pct,
        expected_treaty_amount=expected_amt,
        excess_overwithheld_amount=excess_amt,
        status=status,
        required_forms=rule.required_forms,
        ftc_claim_form=rule.foreign_tax_credit_form,
        recommendation=rec,
    )
