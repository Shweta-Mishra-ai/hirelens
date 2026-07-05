"""
HireLens — AI Engine (Gemini 2.5 Flash Primary)
Fixed:
- Gemini model name updated to stable endpoint
- Proper KeyError handling on Gemini response structure
- Timeout per provider (not just total)
- LLMError wraps all provider errors
- _merge handles missing/null fields safely
- JSON extraction handles nested JSON in text
- Max tokens increased to handle large resumes
"""

import asyncio
import json
import re
import time
import logging
from app.core.config import settings
from app.core.exceptions import LLMError, AnalysisTimeout

logger = logging.getLogger("hirelens")


# ── Robust JSON extractor ─────────────────────────────────────────────────────
def extract_json(raw: str) -> dict:
    """
    Robustly extract JSON from LLM response.
    Handles: clean JSON, markdown fences, JSON embedded in prose.
    """
    if not raw or not raw.strip():
        raise ValueError("LLM returned empty response")

    # Strip common LLM wrappers
    cleaned = raw.strip()

    # Try 1: direct parse
    try:
        result = json.loads(cleaned)
        if isinstance(result, dict):
            return result
    except json.JSONDecodeError:
        pass

    # Try 2: strip markdown fences
    no_fences = re.sub(r"```(?:json)?\s*|\s*```", "", cleaned).strip()
    try:
        result = json.loads(no_fences)
        if isinstance(result, dict):
            return result
    except json.JSONDecodeError:
        pass

    # Try 3: find largest JSON object in response
    # Find all { ... } blocks and try the largest
    matches = list(re.finditer(r"\{", cleaned))
    for start_match in reversed(matches):  # Try from end (usually largest block)
        start = start_match.start()
        depth = 0
        for i, ch in enumerate(cleaned[start:], start):
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    candidate = cleaned[start:i+1]
                    try:
                        result = json.loads(candidate)
                        if isinstance(result, dict):
                            return result
                    except json.JSONDecodeError:
                        break

    raise ValueError(f"Cannot parse JSON from response (len={len(raw)}): {raw[:200]!r}")


# ── Gemini 2.5 Flash ──────────────────────────────────────────────────────────
async def _call_gemini(prompt: str, temperature: float = 0.1, max_tokens: int = 4000) -> str:
    import httpx

    # Use stable model name
    model = "gemini-2.5-flash"
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model}:generateContent?key={settings.GEMINI_API_KEY}"
    )

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": temperature,
            "maxOutputTokens": max_tokens,
            "responseMimeType": "application/json",
        },
    }

    async with httpx.AsyncClient(timeout=90.0) as client:
        r = await client.post(url, json=payload)

        if r.status_code == 429:
            raise LLMError("Gemini rate limit hit. Try again in a moment.")
        if r.status_code == 400:
            body = r.json()
            raise LLMError(f"Gemini API error: {body.get('error', {}).get('message', 'Bad request')}")

        r.raise_for_status()
        data = r.json()

        # Safe extraction with helpful error
        try:
            candidates = data.get("candidates", [])
            if not candidates:
                # Check for safety blocks
                if data.get("promptFeedback", {}).get("blockReason"):
                    raise LLMError(f"Gemini blocked the request: {data['promptFeedback']['blockReason']}")
                raise LLMError("Gemini returned no candidates")

            content = candidates[0].get("content", {})
            parts = content.get("parts", [])
            if not parts:
                raise LLMError("Gemini returned empty content parts")

            return parts[0].get("text", "")
        except (KeyError, IndexError) as e:
            raise LLMError(f"Unexpected Gemini response structure: {e}. Raw: {str(data)[:200]}")


# ── Groq fallback ─────────────────────────────────────────────────────────────
async def _call_groq(prompt: str, temperature: float = 0.1, max_tokens: int = 4000) -> str:
    import httpx

    async with httpx.AsyncClient(timeout=45.0) as client:
        r = await client.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {settings.GROQ_API_KEY}"},
            json={
                "model": "llama-3.1-70b-versatile",
                "messages": [
                    {
                        "role": "system",
                        "content": "You are a resume analysis AI. Always respond with valid JSON only. No markdown, no prose outside JSON.",
                    },
                    {"role": "user", "content": prompt},
                ],
                "temperature": temperature,
                "max_tokens": max_tokens,
                "response_format": {"type": "json_object"},
            },
        )

        if r.status_code == 429:
            raise LLMError("Groq rate limit hit.")
        r.raise_for_status()

        try:
            return r.json()["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as e:
            raise LLMError(f"Unexpected Groq response: {e}")


# ── Anthropic fallback ────────────────────────────────────────────────────────
async def _call_anthropic(prompt: str, temperature: float = 0.1, max_tokens: int = 4000) -> str:
    import httpx

    async with httpx.AsyncClient(timeout=90.0) as client:
        r = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": settings.ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            },
            json={
                "model": "claude-sonnet-4-6",
                "max_tokens": max_tokens,
                "temperature": temperature,
                "system": "You are a resume analysis AI. Always respond with valid JSON only. No markdown, no prose.",
                "messages": [{"role": "user", "content": prompt}],
            },
        )

        if r.status_code == 429:
            raise LLMError("Anthropic rate limit hit.")
        r.raise_for_status()

        try:
            return r.json()["content"][0]["text"]
        except (KeyError, IndexError) as e:
            raise LLMError(f"Unexpected Anthropic response: {e}")


# ── Provider dispatcher with fallback ─────────────────────────────────────────
async def llm_call(prompt: str, temperature: float = 0.1, max_tokens: int = 4000) -> dict:
    """
    Call LLM with automatic provider fallback.
    Priority: Gemini 2.5 Flash → Groq → Anthropic
    Each provider: 2 attempts with 2s backoff.
    """
    providers = []
    if settings.GEMINI_API_KEY:
        providers.append(("gemini-2.5-flash", _call_gemini))
    if settings.GROQ_API_KEY:
        providers.append(("groq-llama3.1", _call_groq))
    if settings.ANTHROPIC_API_KEY:
        providers.append(("claude-sonnet", _call_anthropic))

    if not providers:
        raise LLMError(
            "No LLM API key configured. "
            "Set GEMINI_API_KEY (free at aistudio.google.com) in your .env file."
        )

    last_error = None
    for provider_name, caller in providers:
        for attempt in range(2):
            try:
                t0 = time.monotonic()
                raw = await caller(prompt, temperature=temperature, max_tokens=max_tokens)
                elapsed_ms = (time.monotonic() - t0) * 1000

                result = extract_json(raw)
                logger.info(f"LLM OK | provider={provider_name} attempt={attempt+1} time={elapsed_ms:.0f}ms")
                return result

            except LLMError as e:
                last_error = e
                logger.warning(f"LLM error | provider={provider_name} attempt={attempt+1}: {e}")
                if attempt == 0:
                    await asyncio.sleep(2)
                # Don't retry on rate limit — move to next provider
                if "rate limit" in str(e).lower():
                    break

            except ValueError as e:
                # JSON parse error — try next provider
                last_error = LLMError(f"JSON parse error from {provider_name}: {e}")
                logger.warning(str(last_error))
                break

            except Exception as e:
                last_error = LLMError(f"Unexpected error from {provider_name}: {e}")
                logger.warning(str(last_error))
                if attempt == 0:
                    await asyncio.sleep(2)

        logger.warning(f"Provider {provider_name} exhausted, trying next")

    raise LLMError(
        f"All LLM providers failed. "
        f"Last error: {last_error}. "
        "Check your API keys and network connectivity."
    )


# ── Prompts ───────────────────────────────────────────────────────────────────
EXTRACT_PROMPT = """You are a precise resume parser. Extract ALL structured information from this resume.

RESUME TEXT:
---
{text}
---

Return ONLY valid JSON — no markdown, no explanation, no text before or after the JSON:

{{
  "candidate": {{
    "name": "full name or null",
    "email": "email or null",
    "phone": "phone number or null",
    "location": "city/country or null",
    "linkedin": "linkedin URL or null",
    "github": "github URL or null",
    "current_role": "most recent job title or null",
    "total_experience_years": null
  }},
  "skills": {{
    "all_claimed": ["every skill listed anywhere in the resume"],
    "from_experience": ["skills mentioned in job description bullets"],
    "from_projects": ["skills mentioned in project descriptions"],
    "keyword_stuffing_risk": "none",
    "primary_domain": "candidate's main area of expertise"
  }},
  "experience": [
    {{
      "role": "job title",
      "company": "company name",
      "period": "date range as written in resume",
      "start_date": "YYYY-MM or YYYY or null",
      "end_date": "YYYY-MM or YYYY or present or null",
      "duration_months": null,
      "responsibilities": ["up to 4 bullet points exactly as written"],
      "technologies": ["tech/tools mentioned"],
      "is_verifiable": true
    }}
  ],
  "education": [
    {{
      "degree": "degree name",
      "institution": "institution name",
      "period": "years as written",
      "duration_years": null,
      "field": "field of study or null",
      "grade": "GPA or grade or null",
      "is_recognized_institution": true,
      "concern": null
    }}
  ],
  "projects": [
    {{
      "name": "project name",
      "description": "description as written",
      "technologies": ["technologies used"],
      "metrics": ["any metrics mentioned — EXACTLY as written"],
      "has_link": false
    }}
  ],
  "certifications": ["list of certs as written"]
}}

RULES:
- Extract information EXACTLY as written — do not interpret, summarize, or add
- If a field is missing from the resume, use null (not empty string)
- Include ALL experience entries, even if sparse
- Metrics must be exact quotes — critical for authenticity check later"""


ANALYSIS_PROMPT = """You are a senior HR consultant with 15 years recruiting for tech companies globally.
Analyze this extracted resume data and produce a complete credibility assessment.

EXTRACTED RESUME DATA:
{extracted}

Return ONLY valid JSON — no markdown, no explanation outside the JSON:

{{
  "credibility": {{
    "overall": 75,
    "recommendation": "recommended",
    "confidence": "high",
    "sub_scores": {{
      "timeline": 80,
      "skills_consistency": 75,
      "education": 85,
      "project_authenticity": 70,
      "resume_quality": 80
    }},
    "score_rationale": {{
      "timeline": "Employment dates are consistent with no unexplained gaps",
      "skills_consistency": "Most skills appear in job descriptions",
      "education": "Degree from recognized institution with normal duration",
      "project_authenticity": "Projects have specific technical details",
      "resume_quality": "Well-structured with relevant content"
    }}
  }},
  "skills_verification": {{
    "verified_by_evidence": ["skills that appear in job/project descriptions"],
    "unverified": ["skills listed only in skills section, not evidenced in work"],
    "domain_spread_concern": false,
    "domain_spread_note": null
  }},
  "timeline_gaps": [],
  "flags": [
    {{
      "severity": "medium",
      "category": "skills",
      "title": "Flag title in 6 words max",
      "description": "2-3 sentence explanation of the specific concern found",
      "evidence": "Quote the exact text from the resume that triggered this flag",
      "action": "Specific question or step recruiter should take to verify"
    }}
  ],
  "positive_signals": [
    {{
      "title": "Positive signal title",
      "description": "One sentence describing the strength"
    }}
  ],
  "interview_questions": [
    {{
      "question": "Full interview question text?",
      "rationale": "Why this question specifically for this candidate",
      "targets_flag": "exact flag title this addresses, or null",
      "category": "technical"
    }}
  ],
  "summary": "4-5 sentence professional briefing: career trajectory, key verified strengths, main concerns, recommended next step.",
  "one_liner": "Single sentence verdict under 15 words"
}}

SCORING GUIDE (be realistic — don't default to 70 for everything):
- 85-100: Consistent, verifiable, specific evidence for all major claims
- 70-84: Solid candidate, minor unverified items or 1-2 small concerns
- 55-69: Notable inconsistencies warranting investigation  
- 40-54: Multiple red flags needing structured verification
- 0-39: Serious credibility concerns

FLAG RULES:
- Only flag genuine concerns, not normal career patterns
- Do NOT flag gaps under 3 months without other issues
- DO flag: claiming 4+ unrelated technical domains (ML + Blockchain + AR/VR + Quantum)
- DO flag: companies with no online presence  
- DO flag: degrees completed in impossibly short time
- DO flag: round-number metrics with no baseline ("improved by 300%")
- DO flag: job titles that jumped too fast (Junior → CTO in 2 years)
- Every flag MUST quote actual text from the resume in 'evidence' field

QUESTIONS: Generate exactly 7-9 interview questions mixing:
- 3-4 technical depth (test claimed skills)
- 2-3 clarification (address specific flags)
- 1-2 behavioral

POSITIVE SIGNALS: Include 2-4 genuine strengths with evidence"""


# ── Analysis Engine ───────────────────────────────────────────────────────────
class AnalysisEngine:
    """
    Two-stage analysis pipeline:
    Stage 1: Extract structured data from raw text (low temperature = deterministic)
    Stage 2: Full credibility analysis (slightly higher temperature for nuanced assessment)
    """

    async def run(self, raw_text: str, on_progress=None) -> dict:
        """
        Run complete analysis. Total time: 10-30 seconds.
        
        Args:
            raw_text: Extracted text from resume file
            on_progress: async callback(stage: str, percent: int)
        
        Returns:
            Complete report dict ready for storage
        
        Raises:
            AnalysisTimeout: If analysis exceeds 120 seconds
            LLMError: If all providers fail
        """

        async def progress(stage: str, pct: int):
            logger.info(f"Progress: {stage} {pct}%")
            if on_progress:
                await on_progress(stage, pct)

        try:
            async with asyncio.timeout(settings.ANALYSIS_TIMEOUT_SECONDS):

                # Stage 1: Extract
                await progress("extracting", 15)
                extract_prompt = EXTRACT_PROMPT.format(text=raw_text[:9000])
                extracted = await llm_call(extract_prompt, temperature=0.05, max_tokens=3000)
                logger.info(
                    f"Extracted: "
                    f"{len((extracted.get('skills') or {}).get('all_claimed') or [])} skills, "
                    f"{len(extracted.get('experience') or [])} roles, "
                    f"{len(extracted.get('education') or [])} education"
                )

                await progress("analyzing", 45)

                # Stage 2: Full analysis
                analysis_prompt = ANALYSIS_PROMPT.format(
                    extracted=json.dumps(extracted, indent=2)[:6000]
                )
                analysis = await llm_call(analysis_prompt, temperature=0.1, max_tokens=4000)

                await progress("complete", 100)
                return self._merge(extracted, analysis)

        except asyncio.TimeoutError:
            logger.error(f"Analysis timed out after {settings.ANALYSIS_TIMEOUT_SECONDS}s")
            raise AnalysisTimeout()

    def _merge(self, extracted: dict, analysis: dict) -> dict:
        """
        Merge extraction + analysis into final report.
        All field accesses are safe (handles missing/null from LLM).
        """
        # Safe getters
        def safe_get(d, *keys, default=None):
            for k in keys:
                if not isinstance(d, dict):
                    return default
                d = d.get(k, default)
            return d if d is not None else default

        skills_raw    = extracted.get("skills") or {}
        skills_ver    = analysis.get("skills_verification") or {}
        cred_raw      = analysis.get("credibility") or {}
        sub_scores    = cred_raw.get("sub_scores") or {}

        # Compute overall if missing or 0
        overall = int(cred_raw.get("overall") or 0)
        if overall == 0 and sub_scores:
            weights = {
                "timeline": 0.30, "skills_consistency": 0.25,
                "education": 0.20, "project_authenticity": 0.15,
                "resume_quality": 0.10,
            }
            overall = round(sum(
                int(sub_scores.get(k) or 70) * w
                for k, w in weights.items()
            ))

        overall = max(0, min(100, overall))

        # Determine recommendation from score if missing
        recommendation = cred_raw.get("recommendation") or ""
        if recommendation not in ("recommended", "manual_review", "high_risk"):
            if overall >= 75:
                recommendation = "recommended"
            elif overall >= 55:
                recommendation = "manual_review"
            else:
                recommendation = "high_risk"

        return {
            "candidate": extracted.get("candidate") or {},
            "skills": {
                "all_claimed":           list(skills_raw.get("all_claimed") or []),
                "verified_by_evidence":  list(skills_ver.get("verified_by_evidence") or []),
                "unverified":            list(skills_ver.get("unverified") or []),
                "keyword_stuffing_risk": skills_raw.get("keyword_stuffing_risk") or "none",
                "primary_domain":        skills_raw.get("primary_domain") or "",
                "domain_spread_concern": bool(skills_ver.get("domain_spread_concern")),
                "domain_spread_note":    skills_ver.get("domain_spread_note"),
            },
            "experience":    list(extracted.get("experience") or []),
            "education":     list(extracted.get("education") or []),
            "projects":      list(extracted.get("projects") or []),
            "certifications": list(extracted.get("certifications") or []),
            "credibility": {
                "overall":        overall,
                "recommendation": recommendation,
                "confidence":     cred_raw.get("confidence") or "medium",
                "sub_scores": {
                    "timeline":             int(sub_scores.get("timeline") or 70),
                    "skills_consistency":   int(sub_scores.get("skills_consistency") or 70),
                    "education":            int(sub_scores.get("education") or 70),
                    "project_authenticity": int(sub_scores.get("project_authenticity") or 70),
                    "resume_quality":       int(sub_scores.get("resume_quality") or 70),
                },
                "score_rationale": cred_raw.get("score_rationale") or {},
            },
            "timeline_gaps":        list(analysis.get("timeline_gaps") or []),
            "flags":                list(analysis.get("flags") or []),
            "positive_signals":     list(analysis.get("positive_signals") or []),
            "interview_questions":  list(analysis.get("interview_questions") or []),
            "summary":              str(analysis.get("summary") or "Analysis complete."),
            "one_liner":            str(analysis.get("one_liner") or ""),
            "recruiter_decision":   None,
        }


engine = AnalysisEngine()
