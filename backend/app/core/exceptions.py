class HireLensException(Exception):
    http_status: int = 500
    code: str = "internal_error"
    message: str = "Unexpected error."
    def __init__(self, message: str | None = None):
        self.message = message or self.__class__.message
        super().__init__(self.message)

class AuthError(HireLensException):
    http_status = 401; code = "unauthorized"; message = "Authentication required."

class ForbiddenError(HireLensException):
    http_status = 403; code = "forbidden"; message = "Access denied."

class NotFoundError(HireLensException):
    http_status = 404; code = "not_found"; message = "Resource not found."

class FileTooLarge(HireLensException):
    http_status = 413; code = "file_too_large"
    def __init__(self, max_mb: int = 10):
        self.max_mb = max_mb
        super().__init__(f"File exceeds {max_mb}MB limit.")

class UnsupportedFileType(HireLensException):
    http_status = 415; code = "unsupported_file_type"
    def __init__(self, file_type: str = ""):
        self.file_type = file_type
        super().__init__(f"Unsupported type: {file_type}")

class ParseError(HireLensException):
    http_status = 422; code = "parse_error"
    message = "Could not extract text. Use a text-selectable PDF or DOCX."

class AnalysisError(HireLensException):
    http_status = 500; code = "analysis_error"
    message = "AI analysis failed. Please try again."

class AnalysisTimeout(HireLensException):
    http_status = 504; code = "analysis_timeout"
    message = "Analysis timed out. Please try again."

class LLMError(HireLensException):
    http_status = 503; code = "llm_unavailable"
    message = "AI service temporarily unavailable."

class PersistenceError(HireLensException):
    """A write was accepted for processing but reached no durable store.

    Deliberately a 503 rather than a 500: nothing is wrong with the request
    itself, and the correct client behaviour is to retry. Raised instead of
    returning a success shape when a save silently persisted nothing — see
    save_copilot_data() in api/v1/endpoints/copilot.py.
    """
    http_status = 503; code = "persistence_failed"
    message = "Could not save. Please retry."


class RateLimitExceeded(HireLensException):
    http_status = 429; code = "rate_limit_exceeded"
    def __init__(self, retry_after: int = 60):
        self.retry_after = retry_after
        super().__init__(f"Rate limit exceeded. Retry after {retry_after}s.")

class TooManyFiles(HireLensException):
    http_status = 413; code = "too_many_files"
    def __init__(self, max_files: int = 50):
        self.max_files = max_files
        super().__init__(f"Too many files in one batch. Max is {max_files}.")

class EmptyBatch(HireLensException):
    http_status = 422; code = "empty_batch"
    message = "No valid files were provided."

class TooManyBatches(HireLensException):
    http_status = 429; code = "too_many_batches"
    def __init__(self, max_batches: int = 2):
        self.max_batches = max_batches
        super().__init__(
            f"You already have {max_batches} bulk uploads in progress. "
            "Wait for one to finish before starting another."
        )

class InvalidJobDescription(HireLensException):
    http_status = 422; code = "invalid_job_description"
    message = "Provide a job description as text (min 30 characters) or as a PDF/DOCX/TXT file."

class AllResumesUnreachable(HireLensException):
    http_status = 422; code = "all_resumes_unreachable"
    message = "None of the resume URLs in this CSV could be downloaded. Check the file and try again."

class DBRequiredError(HireLensException):
    http_status = 503; code = "database_required"
    message = "This feature requires a configured database. Ask your admin to set SUPABASE_URL/SUPABASE_SERVICE_KEY."

class ValidationError(HireLensException):
    http_status = 422; code = "validation_error"
    message = "Invalid request data."

class CapacityLimitExceeded(HireLensException):
    """Registration is temporarily closed at the configured active-recruiter
    ceiling (settings.MAX_ACTIVE_RECRUITERS — see app/core/config.py).

    The limit used to be a hardcoded 5,000 baked directly into this
    exception's message, in app/api/v1/endpoints/auth.py, and repeated again
    in health.py's diagnostics — three copies of the same magic number, none
    of them changeable without a code deploy. Worse, a message reading
    "Registration capacity limit of 5,000 active recruiters reached" is
    exactly the kind of specific, round, impressive-sounding number that
    reads as a growth metric for a demo rather than a real operational
    limit — and a genuine launch that actually reached 5,000 signups would
    have hit a hard, unconfigurable wall for no infrastructure reason.

    Now a single operator-tunable setting, with a default high enough that
    it is a safety valve against runaway signups rather than a growth cap.
    """
    http_status = 429; code = "capacity_limit_exceeded"
    def __init__(self, limit: int | None = None):
        self.limit = limit
        if limit is not None:
            message = f"Registration capacity limit of {limit:,} active recruiters reached."
        else:
            message = "Registration capacity limit reached."
        super().__init__(message)

