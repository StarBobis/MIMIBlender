"""Use one expected-error type across workspace and exporter validation."""

# A separate Fatal class bypassed the export operator's error reporting.
# Re-export the shared class so existing imports keep working unchanged.
# Missing extraction data is a user-facing validation error, not a traceback.
from .format_utils import Fatal


class MMTErrorUtils:

    @staticmethod
    def raise_fatal(error_message:str):
        raise Fatal(error_message)


