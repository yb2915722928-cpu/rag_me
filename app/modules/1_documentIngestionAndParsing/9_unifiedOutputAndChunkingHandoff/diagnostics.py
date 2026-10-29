from .models import Diagnostic


def _upstream_diagnostics(result, document_id, source_id):
    diagnostics = [
        Diagnostic("warning", "upstream_warning", message,
                   document_id=document_id, source_id=source_id)
        for message in result.warnings
    ]
    if result.error is not None:
        diagnostics.append(Diagnostic(
            "error", "upstream_error", result.error,
            document_id=document_id, source_id=source_id,
        ))
    return diagnostics
