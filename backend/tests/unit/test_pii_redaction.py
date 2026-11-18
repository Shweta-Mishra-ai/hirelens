"""
Contact details never reach an AI provider.

On the Gemini API's free tier, submitted content may be used to improve
Google's products and read by reviewers. Resumes are candidates' personal
data, so emails, phone numbers, links and the candidate's name are replaced
with placeholders before any prompt is built, and restored afterwards.
"""

import json
from unittest.mock import patch

import pytest

from app.core.config import settings
from app.services.ai.redaction import redact

RESUME = """Anita Rao
anita.rao@gmail.com | +91 98765 43210 | linkedin.com/in/anitarao | https://github.com/anitarao
Bengaluru, India

EXPERIENCE
Senior Engineer, Acme Corp — 2019 - 2024
Engineer, Beta Ltd — 01.2016 - 03.2019 (3 yrs)
Reduced latency by 40%. References: (415) 555-2671
EDUCATION
B.Tech, IIT Madras 2012-2016
"""

SECRETS = ["anita.rao@gmail.com", "98765 43210", "linkedin.com/in/anitarao", "github.com/anitarao", "555-2671", "Anita Rao"]


class TestRedact:
    def test_contact_details_and_name_are_removed(self):
        text = redact(RESUME).text
        for secret in SECRETS:
            assert secret.lower() not in text.lower(), secret

    def test_dates_numbers_and_content_survive(self):
        text = redact(RESUME).text
        for kept in ("2019 - 2024", "01.2016 - 03.2019", "2012-2016", "40%", "Acme Corp", "IIT Madras", "Bengaluru"):
            assert kept in text, kept

    @pytest.mark.parametrize("dates", [
        "2015-2019 2019-2023",
        "Jan 2018 – Mar 2021",
        "06/2017 - 08/2020",
        "2010 2012 2014 2016",
    ])
    def test_date_ranges_are_never_mistaken_for_phone_numbers(self, dates):
        assert redact(f"Worked there {dates}.").text == f"Worked there {dates}."

    @pytest.mark.parametrize("phone", ["+1 415 555 2671", "+44 20 7946 0958", "9876543210", "080-4123-4567"])
    def test_common_phone_formats_are_redacted(self, phone):
        assert "PHONE_1" in redact(f"Call {phone} now").text

    def test_a_heading_that_is_not_a_name_is_left_alone(self):
        r = redact("Curriculum Vitae\nSenior Data Engineer\n")
        assert "CANDIDATE_NAME" not in r.values

    def test_the_same_value_gets_the_same_placeholder(self):
        r = redact("a@b.co then A@B.co again")
        assert r.text.count("[[EMAIL_1]]") == 2
        assert "EMAIL_2" not in r.values

    def test_restore_handles_nested_json_and_unbracketed_placeholders(self):
        r = redact(RESUME)
        restored = r.restore({
            "candidate": {"name": "[[CANDIDATE_NAME]]", "email": "EMAIL_1", "github": "[[URL_2]]"},
            "notes": ["Reach [[PHONE_1]]"],
            "score": 80,
        })
        assert restored["candidate"] == {
            "name": "Anita Rao", "email": "anita.rao@gmail.com", "github": "https://github.com/anitarao",
        }
        assert restored["notes"] == ["Reach +91 98765 43210"]
        assert restored["score"] == 80

    def test_an_unknown_placeholder_is_left_as_written(self):
        assert redact("no contact details").restore("[[EMAIL_9]]") == "[[EMAIL_9]]"


class TestTheEngineNeverSendsThem:
    @pytest.mark.asyncio
    async def test_no_prompt_contains_contact_details_and_the_report_has_them_back(self, monkeypatch):
        from app.services.ai import engine as engine_module

        prompts = []

        async def fake_llm(prompt, **kwargs):
            prompts.append(prompt)
            if "RESUME_TEXT_START" in prompt:
                return {
                    "candidate": {
                        "name": "[[CANDIDATE_NAME]]", "email": "[[EMAIL_1]]", "phone": "[[PHONE_1]]",
                        "linkedin": "[[URL_1]]", "github": "[[URL_2]]",
                    },
                    "skills": {"all_claimed": ["Python"]},
                    "experience": [{"role": "Senior Engineer", "company": "Acme Corp",
                                    "start_date": "2019", "end_date": "2024"}],
                    "education": [], "projects": [], "certifications": [],
                }
            return {"credibility": {"overall": 80, "recommendation": "recommended"}}

        monkeypatch.setattr(settings, "REDACT_PII_FOR_LLM", True)
        monkeypatch.setattr(engine_module, "llm_call", fake_llm)
        report = await engine_module.engine.run(raw_text=RESUME)

        sent = "\n".join(prompts).lower()
        for secret in SECRETS:
            assert secret.lower() not in sent, f"{secret!r} reached a provider"

        candidate = report["candidate"]
        assert candidate["name"] == "Anita Rao"
        assert candidate["email"] == "anita.rao@gmail.com"
        assert candidate["github"] == "https://github.com/anitarao"

    @pytest.mark.asyncio
    async def test_jd_matching_sends_no_contact_fields(self, monkeypatch):
        from app.services.ai import engine as engine_module

        prompts = []

        async def fake_llm(prompt, **kwargs):
            prompts.append(prompt)
            return {"match_percent": 70}

        monkeypatch.setattr(engine_module, "llm_call", fake_llm)
        await engine_module.engine.match_jd(
            {"candidate": {"name": "Anita Rao", "email": "anita.rao@gmail.com", "phone": "+91 98765 43210",
                           "current_role": "Engineer"}, "skills": {"all_claimed": ["Python"]}},
            "We need a Python engineer for payments infrastructure work.",
        )
        sent = prompts[0]
        assert "anita.rao@gmail.com" not in sent and "Anita Rao" not in sent and "98765" not in sent
        assert "Engineer" in sent

    @pytest.mark.asyncio
    async def test_redaction_can_be_switched_off(self, monkeypatch):
        from app.services.ai import engine as engine_module

        prompts = []

        async def fake_llm(prompt, **kwargs):
            prompts.append(prompt)
            return {"candidate": {}} if "RESUME_TEXT_START" in prompt else {"credibility": {}}

        monkeypatch.setattr(settings, "REDACT_PII_FOR_LLM", False)
        monkeypatch.setattr(engine_module, "llm_call", fake_llm)
        await engine_module.engine.run(raw_text=RESUME)
        assert "anita.rao@gmail.com" in prompts[0]
