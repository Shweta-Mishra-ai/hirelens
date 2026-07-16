"""
HireLens — Resume-Likeness Heuristic Unit Tests
Run: cd backend && python -m pytest tests/unit/test_resume_heuristic.py -v
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from app.services.parser.resume_heuristic import looks_like_resume


REAL_RESUME = """
John Doe
john.doe@example.com | +1 555-123-4567

SUMMARY
Backend engineer with 5 years of experience building distributed systems.

EXPERIENCE
Senior Software Engineer — Acme Corp (2019 - 2023)
- Built microservices in Python and Go
- Led migration to Kubernetes

EDUCATION
B.Tech Computer Science, IIT Delhi (2015 - 2019)

SKILLS
Python, FastAPI, PostgreSQL, Docker, Kubernetes, AWS
"""

RANDOM_INVOICE = """
INVOICE #4521

Bill To: XYZ Traders
Date: 03/14/2024
Due Date: 04/14/2024

Item                Qty    Price    Total
Office Chairs        10    $120     $1200
Desks                 5    $300     $1500

Subtotal: $2700
Tax: $270
Total Due: $2970

Please remit payment within 30 days. Thank you for your business.
"""

BOOK_EXCERPT = """
Chapter One

It was the best of times, it was the worst of times, it was the age of
wisdom, it was the age of foolishness, it was the epoch of belief, it
was the epoch of incredulity, it was the season of Light, it was the
season of Darkness, it was the spring of hope, it was the winter of
despair, we had everything before us, we had nothing before us.
"""


class TestLooksLikeResume:
    def test_real_resume_passes(self):
        ok, reason = looks_like_resume(REAL_RESUME)
        assert ok is True
        assert reason == ""

    def test_random_invoice_rejected(self):
        ok, reason = looks_like_resume(RANDOM_INVOICE)
        assert ok is False
        assert reason != ""

    def test_book_excerpt_rejected(self):
        ok, reason = looks_like_resume(BOOK_EXCERPT)
        assert ok is False

    def test_empty_text_rejected(self):
        ok, reason = looks_like_resume("")
        assert ok is False
        assert "readable text" in reason

    def test_too_short_text_rejected(self):
        ok, reason = looks_like_resume("Hi there, short note.")
        assert ok is False

    def test_none_input_rejected(self):
        ok, reason = looks_like_resume(None)
        assert ok is False

    def test_resume_with_only_contact_and_headers_no_dates_passes(self):
        text = (
            "Jane Smith jane@example.com\n"
            "SKILLS: Python, React, SQL\n"
            "EXPERIENCE: Software developer at various startups.\n"
            "EDUCATION: Computer Science degree.\n"
        ) * 2
        ok, _ = looks_like_resume(text)
        assert ok is True

    def test_resume_like_text_but_no_contact_still_passes_on_headers_and_dates(self):
        text = """
        EXPERIENCE
        Software Engineer, TechCorp (2018-2022)
        Worked on backend systems.

        EDUCATION
        BSc Computer Science (2014-2018)

        SKILLS
        Java, Spring Boot, MySQL
        """
        ok, _ = looks_like_resume(text)
        assert ok is True

    def test_data_analysis_report_rejected(self):
        text = """
        DataForge AI · Data Health & Business Insights
        HR-Employee-Attrition-All.csv
        July 16, 2026
        CONFIDENTIAL
        DATA HEALTH & BUSINESS INSIGHTS REPORT
        Overall Data Health Score: 95/100
        Dataset Summary:
        Total Rows: 1,470
        Total Columns: 32
        Grade: A+ — Excellent
        Meaningful Business Insights:
        Attrition rate is 16.1% (planning threshold: <10%)
        Employees seek better career opportunities with higher education profile.
        """
        ok, reason = looks_like_resume(text)
        assert ok is False
        assert "doesn't look like a resume" in reason

