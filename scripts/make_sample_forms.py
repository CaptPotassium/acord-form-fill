#!/usr/bin/env python3
"""
Generate ACORD-style *stand-in* fillable PDFs and sample input artifacts.

Why this exists
---------------
Real ACORD forms are copyrighted by ACORD and licensed to member agencies and
vendors. They cannot be redistributed inside a demo repo. This script builds
structurally faithful stand-ins: real AcroForm text fields and checkboxes, using
ACORD's actual field-naming convention (Section_Attribute_Suffix), so the whole
pipeline can be demonstrated end to end.

To run against a genuine ACORD 125/126, drop the licensed blank PDF into
assets/forms/ and run dump_fields.py against it to regenerate the mapping stub.
The fill engine does not care which it is -- it fills any AcroForm PDF.

By default this generates only the sample input documents. The stand-in blanks
are opt-in via --standin-forms, since the real licensed ACORD packet is present
in assets/forms/ and the mappings target that.

Usage:
    python scripts/make_sample_forms.py --samples samples
    python scripts/make_sample_forms.py --standin-forms   # fallback blanks too
"""
from __future__ import annotations

import argparse
import csv
import os

from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

WIDTH, HEIGHT = letter
INK = HexColor("#111111")
RULE = HexColor("#888888")
BAND = HexColor("#E8E8E8")


class FormBuilder:
    """Thin wrapper over reportlab that lays out labelled AcroForm fields."""

    def __init__(self, path: str, title: str):
        self.c = canvas.Canvas(path, pagesize=letter)
        self.c.setTitle(title)
        self.title = title
        self.y = HEIGHT - 54

    # ---- chrome -------------------------------------------------------
    def header(self, code: str, subtitle: str) -> None:
        c = self.c
        c.setFillColor(INK)
        c.setFont("Helvetica-Bold", 15)
        c.drawString(40, self.y, code)
        c.setFont("Helvetica", 10.5)
        c.drawString(40, self.y - 16, subtitle)
        c.setFont("Helvetica-Oblique", 7.5)
        c.drawRightString(
            WIDTH - 40, self.y,
            "STAND-IN FORM FOR DEMONSTRATION - NOT AN ACORD FORM",
        )
        self.y -= 40

    def band(self, label: str) -> None:
        if self.y < 110:
            self.page_break()
        c = self.c
        c.setFillColor(BAND)
        c.rect(40, self.y - 4, WIDTH - 80, 16, stroke=0, fill=1)
        c.setFillColor(INK)
        c.setFont("Helvetica-Bold", 8.5)
        c.drawString(45, self.y, label.upper())
        self.y -= 24

    def page_break(self) -> None:
        self.c.showPage()
        self.y = HEIGHT - 54
        self.c.setFont("Helvetica", 8)

    # ---- fields -------------------------------------------------------
    def row(self, specs: list[tuple[str, str, float]]) -> None:
        """specs = [(label, field_name, width_fraction), ...] summing to <= 1.0"""
        if self.y < 80:
            self.page_break()
        usable = WIDTH - 80
        x = 40
        for label, name, frac in specs:
            w = usable * frac - 8
            self.c.setFillColor(INK)
            self.c.setFont("Helvetica", 6.8)
            self.c.drawString(x + 2, self.y + 15, label)
            self.c.acroForm.textfield(
                name=name, tooltip=label, x=x, y=self.y, width=w, height=13,
                borderWidth=0.5, borderColor=RULE, fillColor=None,
                fontName="Helvetica", fontSize=8, forceBorder=True,
            )
            x += usable * frac
        self.y -= 30

    def checks(self, label: str, items: list[tuple[str, str]]) -> None:
        """items = [(caption, field_name), ...] rendered as a checkbox strip."""
        if self.y < 80:
            self.page_break()
        self.c.setFillColor(INK)
        self.c.setFont("Helvetica", 6.8)
        self.c.drawString(42, self.y + 15, label)
        x = 42
        for caption, name in items:
            self.c.acroForm.checkbox(
                name=name, tooltip=caption, x=x, y=self.y,
                size=10, borderWidth=0.5, borderColor=RULE,
                fillColor=None, buttonStyle="check", forceBorder=True,
            )
            self.c.setFont("Helvetica", 7)
            self.c.drawString(x + 13, self.y + 2, caption)
            x += 16 + self.c.stringWidth(caption, "Helvetica", 7)
        self.y -= 28

    def save(self) -> None:
        self.c.save()


def build_acord_125(path: str) -> None:
    f = FormBuilder(path, "ACORD 125-style Commercial Insurance Application")
    f.header("ACORD 125 (stand-in)", "Commercial Insurance Application - Applicant Information Section")

    f.band("Agency / Producer")
    f.row([("AGENCY", "Producer_FullName_A", 0.5), ("DATE (MM/DD/YYYY)", "Form_CompletionDate_A", 0.25),
           ("PRODUCER CODE", "Producer_ProducerCode_A", 0.25)])
    f.row([("CONTACT NAME", "Producer_ContactName_A", 0.34), ("PHONE", "Producer_PhoneNumber_A", 0.33),
           ("E-MAIL", "Producer_EmailAddress_A", 0.33)])

    f.band("Policy Information")
    f.row([("PROPOSED EFF DATE", "Policy_EffectiveDate_A", 0.25), ("PROPOSED EXP DATE", "Policy_ExpirationDate_A", 0.25),
           ("BILLING PLAN", "Policy_BillingPlanCode_A", 0.25), ("PAYMENT PLAN", "Policy_PaymentPlanCode_A", 0.25)])
    f.checks("LINES OF BUSINESS REQUESTED", [
        ("General Liability", "LineOfBusiness_GeneralLiability_A"),
        ("Property", "LineOfBusiness_Property_A"),
        ("Business Auto", "LineOfBusiness_BusinessAuto_A"),
        ("Workers Comp", "LineOfBusiness_WorkersCompensation_A"),
        ("Umbrella", "LineOfBusiness_Umbrella_A"),
    ])

    f.band("Applicant Information")
    f.row([("NAMED INSURED", "NamedInsured_FullName_A", 0.6), ("FEIN OR SOC SEC #", "NamedInsured_FEINOrSocSecNumber_A", 0.4)])
    f.row([("DBA / TRADE NAME", "NamedInsured_DBAName_A", 0.6), ("WEBSITE", "NamedInsured_WebsiteAddress_A", 0.4)])
    f.row([("MAILING ADDRESS", "NamedInsured_MailingAddress_LineOne_A", 1.0)])
    f.row([("CITY", "NamedInsured_MailingAddress_CityName_A", 0.4), ("STATE", "NamedInsured_MailingAddress_StateOrProvinceCode_A", 0.2),
           ("ZIP", "NamedInsured_MailingAddress_PostalCode_A", 0.2), ("COUNTY", "NamedInsured_MailingAddress_CountyName_A", 0.2)])
    f.row([("BUSINESS PHONE", "NamedInsured_PhoneNumber_A", 0.34), ("SIC", "BusinessInformation_SICCode_A", 0.33),
           ("NAICS", "BusinessInformation_NAICSCode_A", 0.33)])
    f.checks("LEGAL ENTITY", [
        ("Corporation", "NamedInsured_LegalEntity_Corporation_A"),
        ("LLC", "NamedInsured_LegalEntity_LimitedLiabilityCompany_A"),
        ("Partnership", "NamedInsured_LegalEntity_Partnership_A"),
        ("Individual", "NamedInsured_LegalEntity_Individual_A"),
        ("S-Corp", "NamedInsured_LegalEntity_SubchapterSCorporation_A"),
    ])
    f.row([("YEARS IN BUSINESS", "BusinessInformation_YearsInBusiness_A", 0.25),
           ("ANNUAL REVENUE", "BusinessInformation_AnnualRevenueAmount_A", 0.25),
           ("# FULL TIME EMPL", "BusinessInformation_FullTimeEmployeeCount_A", 0.25),
           ("# PART TIME EMPL", "BusinessInformation_PartTimeEmployeeCount_A", 0.25)])
    f.row([("DESCRIPTION OF PRIMARY OPERATIONS", "BusinessInformation_OperationsDescription_A", 1.0)])

    f.band("Premises Information")
    for i in (1, 2, 3):
        f.row([(f"LOC {i} - STREET", f"Premises_MailingAddress_LineOne_{i}", 0.46),
               ("CITY", f"Premises_MailingAddress_CityName_{i}", 0.22),
               ("ST", f"Premises_MailingAddress_StateOrProvinceCode_{i}", 0.1),
               ("ZIP", f"Premises_MailingAddress_PostalCode_{i}", 0.22)])
        f.row([("INTEREST (OWNER/TENANT)", f"Premises_InterestCode_{i}", 0.3),
               ("TOTAL BLDG AREA (SQ FT)", f"Premises_TotalBuildingArea_{i}", 0.35),
               ("ANNUAL REVENUE AT LOC", f"Premises_AnnualRevenueAmount_{i}", 0.35)])

    f.band("Prior Carrier Information")
    for i in (1, 2):
        f.row([(f"YEAR {i} - CARRIER", f"PriorCarrier_CarrierName_{i}", 0.34),
               ("POLICY NUMBER", f"PriorCarrier_PolicyNumberIdentifier_{i}", 0.33),
               ("ANNUAL PREMIUM", f"PriorCarrier_AnnualPremiumAmount_{i}", 0.33)])

    f.band("General Information")
    f.checks("ANY PRIOR COVERAGE DECLINED, CANCELLED OR NON-RENEWED IN LAST 3 YEARS?",
             [("Yes", "GeneralInformation_PriorCancellation_YesIndicator_A"),
              ("No", "GeneralInformation_PriorCancellation_NoIndicator_A")])
    f.checks("ANY BANKRUPTCY, LIEN OR JUDGEMENT IN LAST 5 YEARS?",
             [("Yes", "GeneralInformation_Bankruptcy_YesIndicator_A"),
              ("No", "GeneralInformation_Bankruptcy_NoIndicator_A")])
    f.checks("IS A FORMAL SAFETY PROGRAM IN OPERATION?",
             [("Yes", "GeneralInformation_SafetyProgram_YesIndicator_A"),
              ("No", "GeneralInformation_SafetyProgram_NoIndicator_A")])
    f.save()


def build_acord_126(path: str) -> None:
    f = FormBuilder(path, "ACORD 126-style Commercial General Liability Section")
    f.header("ACORD 126 (stand-in)", "Commercial General Liability Section")

    f.band("Agency / Applicant")
    f.row([("AGENCY", "Producer_FullName_A", 0.5), ("DATE (MM/DD/YYYY)", "Form_CompletionDate_A", 0.25),
           ("EFFECTIVE DATE", "Policy_EffectiveDate_A", 0.25)])
    f.row([("NAMED INSURED", "NamedInsured_FullName_A", 0.6), ("FEIN", "NamedInsured_FEINOrSocSecNumber_A", 0.4)])

    f.band("Coverage / Limits")
    f.checks("COVERAGE TRIGGER", [("Occurrence", "GeneralLiability_CoverageTrigger_OccurrenceIndicator_A"),
                                  ("Claims Made", "GeneralLiability_CoverageTrigger_ClaimsMadeIndicator_A")])
    f.row([("EACH OCCURRENCE", "GeneralLiability_EachOccurrenceLimitAmount_A", 0.34),
           ("GENERAL AGGREGATE", "GeneralLiability_GeneralAggregateLimitAmount_A", 0.33),
           ("PRODUCTS/COMPLETED OPS AGG", "GeneralLiability_ProductsCompletedOperationsAggregateLimitAmount_A", 0.33)])
    f.row([("DAMAGE TO RENTED PREMISES", "GeneralLiability_FireDamageLimitAmount_A", 0.34),
           ("MEDICAL EXPENSE", "GeneralLiability_MedicalExpenseLimitAmount_A", 0.33),
           ("PERSONAL & ADV INJURY", "GeneralLiability_PersonalAndAdvertisingInjuryLimitAmount_A", 0.33)])
    f.checks("GENERAL AGGREGATE APPLIES PER", [
        ("Policy", "GeneralLiability_AggregateLimitAppliesPer_PolicyIndicator_A"),
        ("Project", "GeneralLiability_AggregateLimitAppliesPer_ProjectIndicator_A"),
        ("Location", "GeneralLiability_AggregateLimitAppliesPer_LocationIndicator_A"),
    ])
    f.row([("DEDUCTIBLE AMOUNT", "GeneralLiability_DeductibleAmount_A", 0.5),
           ("DEDUCTIBLE BASIS (OCC/CLAIM)", "GeneralLiability_DeductibleBasisCode_A", 0.5)])

    f.band("Classification / Rating Schedule")
    for i in (1, 2, 3, 4):
        f.row([(f"LOC {i}", f"GeneralLiabilityClassification_LocationNumber_{i}", 0.08),
               ("CLASSIFICATION DESCRIPTION", f"GeneralLiabilityClassification_ClassificationDescription_{i}", 0.44),
               ("CLASS CODE", f"GeneralLiabilityClassification_ClassCode_{i}", 0.16),
               ("PREMIUM BASIS", f"GeneralLiabilityClassification_PremiumBasisCode_{i}", 0.16),
               ("EXPOSURE", f"GeneralLiabilityClassification_ExposureAmount_{i}", 0.16)])

    f.band("Contractors Supplemental")
    f.row([("% OF WORK SUBCONTRACTED", "Contractor_SubcontractedWorkPercent_A", 0.34),
           ("ANNUAL COST OF SUBCONTRACTORS", "Contractor_SubcontractorAnnualCostAmount_A", 0.33),
           ("DO YOU REQUIRE CERTIFICATES?", "Contractor_CertificateRequiredIndicator_A", 0.33)])

    f.band("Claims / Loss History")
    for i in (1, 2, 3):
        f.row([(f"DATE OF OCCURRENCE {i}", f"Loss_OccurrenceDate_{i}", 0.2),
               ("DESCRIPTION", f"Loss_Description_{i}", 0.42),
               ("AMOUNT PAID", f"Loss_PaidAmount_{i}", 0.19),
               ("RESERVED", f"Loss_ReserveAmount_{i}", 0.19)])
    f.save()


def build_dec_page(path: str) -> None:
    """A text-extractable carrier declarations page used as an unstructured input."""
    c = canvas.Canvas(path, pagesize=letter)
    c.setTitle("Declarations Page - Meridian Casualty Insurance Company")
    y = HEIGHT - 60
    c.setFont("Helvetica-Bold", 13)
    c.drawString(40, y, "MERIDIAN CASUALTY INSURANCE COMPANY")
    c.setFont("Helvetica", 10)
    c.drawString(40, y - 15, "COMMERCIAL GENERAL LIABILITY DECLARATIONS")
    y -= 45
    lines = [
        ("Policy Number:", "CGL-4471902-03"),
        ("Policy Period:", "07/01/2025 to 07/01/2026, 12:01 A.M. Standard Time"),
        ("Named Insured:", "Brightwater Mechanical Contractors, Inc."),
        ("DBA:", "Brightwater Mechanical"),
        ("Mailing Address:", "1420 Harbor Point Blvd, Suite 300"),
        ("", "Stamford, CT 06902  (Fairfield County)"),
        ("Federal Employer ID:", "06-1583427"),
        ("Form of Business:", "Corporation"),
        ("Business Description:", "Plumbing and HVAC contractor - commercial service and installation"),
        ("NAICS:", "238220"),
        ("SIC:", "1711"),
        ("Total Annual Premium:", "$47,850"),
    ]
    c.setFont("Helvetica", 9.5)
    for label, val in lines:
        c.setFont("Helvetica-Bold", 9.5)
        c.drawString(40, y, label)
        c.setFont("Helvetica", 9.5)
        c.drawString(175, y, val)
        y -= 15

    y -= 12
    c.setFont("Helvetica-Bold", 10)
    c.drawString(40, y, "LIMITS OF INSURANCE")
    y -= 17
    c.setFont("Helvetica", 9.5)
    for label, val in [
        ("Each Occurrence Limit", "$1,000,000"),
        ("Damage To Rented Premises (each occurrence)", "$100,000"),
        ("Medical Expense Limit (any one person)", "$10,000"),
        ("Personal & Advertising Injury Limit", "$1,000,000"),
        ("General Aggregate Limit", "$2,000,000"),
        ("Products/Completed Operations Aggregate Limit", "$2,000,000"),
        ("General Aggregate Limit applies per", "Project"),
        ("Deductible - Bodily Injury / Property Damage", "$5,000 per occurrence"),
    ]:
        c.drawString(52, y, label)
        c.drawRightString(WIDTH - 52, y, val)
        y -= 14

    y -= 12
    c.setFont("Helvetica-Bold", 10)
    c.drawString(40, y, "SCHEDULE OF COVERED LOCATIONS")
    y -= 17
    c.setFont("Helvetica", 9)
    for loc in [
        "Loc 1: 1420 Harbor Point Blvd, Suite 300, Stamford, CT 06902 - Tenant - 12,000 sq ft",
        "Loc 2: 88 Ironworks Road, Bridgeport, CT 06605 - Owner - 26,500 sq ft",
    ]:
        c.drawString(52, y, loc)
        y -= 14

    y -= 12
    c.setFont("Helvetica-Bold", 10)
    c.drawString(40, y, "CLASSIFICATION SCHEDULE")
    y -= 17
    c.setFont("Helvetica", 9)
    for row in [
        "98482 - Plumbing - commercial/industrial - Premium Basis: Payroll - Exposure: $2,850,000",
        "98677 - Heating/AC systems - installation, service, repair - Premium Basis: Payroll - Exposure: $1,240,000",
    ]:
        c.drawString(52, y, row)
        y -= 14
    c.showPage()
    c.save()


def build_ams_csv(path: str) -> None:
    rows = [{
        "account_name": "Brightwater Mechanical Contractors",
        "named_insured": "Brightwater Mechanical Contractors, Inc.",
        "dba": "Brightwater Mechanical",
        "mailing_address": "1420 Harbor Point Blvd, Suite 300",
        "city": "Stamford", "state": "CT", "zip": "06902", "county": "Fairfield",
        "fein": "06-1583427", "naics": "238220", "sic": "1711",
        "entity_type": "Corporation", "years_in_business": "18",
        "annual_revenue": "14750000",
        "full_time_employees": "62", "part_time_employees": "8",
        "business_phone": "(203) 555-0148",
        "website": "www.brightwatermech.com",
        "contact_name": "Dana Whitfield", "contact_email": "dwhitfield@brightwatermech.com",
        "producer_name": "Kestrel Risk Partners", "producer_code": "KRP-0042",
        "producer_contact": "Marcus Alvarado", "producer_phone": "(203) 555-0900",
        "producer_email": "malvarado@kestrelrisk.com",
        "prior_carrier": "Meridian Casualty Insurance Company",
        "prior_policy_number": "CGL-4471902-03",
        "prior_premium": "47850",
        "effective_date": "07/01/2026", "expiration_date": "07/01/2027",
    }]
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def build_loss_runs(path: str) -> None:
    c = canvas.Canvas(path, pagesize=letter)
    c.setTitle("Loss Run - Brightwater Mechanical Contractors, Inc.")
    y = HEIGHT - 60
    c.setFont("Helvetica-Bold", 12)
    c.drawString(40, y, "MERIDIAN CASUALTY - LOSS RUN REPORT")
    c.setFont("Helvetica", 9)
    c.drawString(40, y - 14, "Insured: Brightwater Mechanical Contractors, Inc.   Policy: CGL-4471902-03")
    c.drawString(40, y - 26, "Valued as of: 05/31/2026     Line: General Liability")
    y -= 52
    c.setFont("Helvetica-Bold", 8.5)
    for x, h in [(40, "DATE OF LOSS"), (120, "CLAIM NUMBER"), (215, "DESCRIPTION"), (450, "PAID"), (515, "RESERVE")]:
        c.drawString(x, y, h)
    y -= 13
    c.setFont("Helvetica", 8.5)
    for d, n, desc, paid, res in [
        ("03/14/2024", "GL-224-9911", "Water damage to tenant space during pipe replacement", "18,400", "0"),
        ("11/02/2024", "GL-224-1327", "Slip and fall, jobsite visitor, contusion", "6,250", "2,500"),
        ("08/19/2025", "GL-225-4402", "Property damage - HVAC unit fell during install", "31,900", "15,000"),
    ]:
        c.drawString(40, y, d); c.drawString(120, y, n); c.drawString(215, y, desc[:52])
        c.drawRightString(500, y, paid); c.drawRightString(WIDTH - 40, y, res)
        y -= 14
    c.showPage()
    c.save()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--outdir", default="assets/forms",
                    help="where --standin-forms writes its output")
    ap.add_argument("--samples", default="samples")
    ap.add_argument("--standin-forms", action="store_true",
                    help="also generate ACORD-style stand-in blanks (only needed "
                         "when no licensed blank is available)")
    a = ap.parse_args()
    os.makedirs(a.samples, exist_ok=True)

    build_dec_page(os.path.join(a.samples, "dec_page.pdf"))
    build_loss_runs(os.path.join(a.samples, "loss_runs.pdf"))
    build_ams_csv(os.path.join(a.samples, "ams_export.csv"))
    print(f"Sample inputs -> {a.samples}")

    if a.standin_forms:
        os.makedirs(a.outdir, exist_ok=True)
        build_acord_125(os.path.join(a.outdir, "acord_125_standin.pdf"))
        build_acord_126(os.path.join(a.outdir, "acord_126_standin.pdf"))
        print(f"Stand-in blanks -> {a.outdir}")


if __name__ == "__main__":
    main()
