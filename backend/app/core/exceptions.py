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

class RateLimitExceeded(HireLensException):
    http_status = 429; code = "rate_limit_exceeded"
    def __init__(self, retry_after: int = 60):
        self.retry_after = retry_after
        super().__init__(f"Rate limit exceeded. Retry after {retry_after}s.")
