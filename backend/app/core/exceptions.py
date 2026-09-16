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

class AccountStoreUnavailable(HireLensException):
    http_status = 503; code = "account_store_unavailable"
    message = (
        "We couldn't create your account right now. This is on our side — "
        "please try again in a moment."
    )


class CopilotUnavailable(HireLensException):
    http_status = 503; code = "copilot_unavailable"
    message = (
        "We couldn't reach the database to open this candidate's interview "
        "notes. Please try again in a moment — nothing has been lost."
    )


class ConflictError(HireLensException):
    """
    The request is well-formed and authenticated, but conflicts with existing
    state — e.g. signing up with an email that already has an account.

    Signup previously raised AuthError (401) for that case. 401 is wrong
    twice over: the caller is not being asked to authenticate, and clients
    that treat any 401 as "session expired" (this app's own API client
    among them) would log the user out in response to a duplicate signup.
    """
    http_status = 409; code = "conflict"; message = "This conflicts with existing data."

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

class AnalysisUnavailable(HireLensException):
    """
    Raised at upload time when no AI provider is configured at all.

    This is distinct from LLMError, which means a configured provider failed.
    Uploads used to be accepted and queued in this state, so the user waited
    through the whole progress animation before being shown a raw internal
    message about setting GEMINI_API_KEY in a .env file — advice that means
    nothing to a recruiter and everything to the operator.
    """
    http_status = 503; code = "analysis_unavailable"
    message = (
        "Resume analysis is not available right now because no AI provider is "
        "configured on the server. Your file was not uploaded. Contact your "
        "administrator to finish setting up HireLens."
    )

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
    http_status = 429; code = "capacity_limit_exceeded"
    message = "Registration capacity limit of 5,000 active recruiters reached."

