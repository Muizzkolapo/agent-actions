"""UDF discovery/import error formatter."""

import re
from typing import Any

from agent_actions.errors import UDFLoadError

from ..user_error import UserError
from .base import ErrorFormatter

_MISSING_MODULE_RE = re.compile(r"No module named ['\"]([^'\"]+)['\"]")


def _first_non_none(*values: Any) -> Any:
    """Return the first non-None value; unlike ``or``, empty strings / 0 / False are kept."""
    for v in values:
        if v is not None:
            return v
    return None


class UDFLoadErrorFormatter(ErrorFormatter):
    """Render UDF import failures with the module, file, and how to fix it.

    UDF discovery imports every Python file under the user-code directory; a
    single broken file blocks every command that loads the workflow. The
    generic configuration formatter loses the module + file context that
    ``UDFLoadError`` already carries, so this formatter claims those errors
    before the configuration chain sees them.
    """

    def can_handle(self, exc: Exception, root: Exception, message: str) -> bool:
        return isinstance(exc, UDFLoadError) or isinstance(root, UDFLoadError)

    def format(
        self, exc: Exception, root: Exception, message: str, context: dict[str, Any]
    ) -> UserError:
        # Read identity fields from the UDFLoadError directly: an outer wrapper
        # that re-enriches these keys would otherwise clobber them via
        # merge_exception_context (outer wins).
        udf_exc = exc if isinstance(exc, UDFLoadError) else root
        udf_context = getattr(udf_exc, "context", None) or {}

        module = _first_non_none(udf_context.get("module"), context.get("module"), "<unknown>")
        file = _first_non_none(udf_context.get("file"), context.get("file"))
        error = _first_non_none(udf_context.get("error"), context.get("error"), message)
        search_path = context.get("search_path")
        requested_path = context.get("requested_path")

        if module == UDFLoadError.DISCOVERY_SENTINEL:
            return self._format_discovery_failure(file, error, search_path, requested_path)

        return self._format_import_failure(module, file, error, exc, search_path, requested_path)

    def _format_discovery_failure(
        self,
        path: str | None,
        error: str,
        search_path: str | None,
        requested_path: str | None,
    ) -> UserError:
        ctx: dict[str, Any] = {}
        if path:
            ctx["file_path"] = path
        if search_path:
            ctx["search_path"] = search_path
        if requested_path:
            ctx["requested_path"] = requested_path
        return UserError(
            category="Configuration Error",
            title="UDF discovery failed",
            details=error,
            fix=(
                "Pass a valid user-code directory via `-u <path>`, or set "
                "`tool_path` in your workflow config to a directory that exists."
            ),
            context=ctx or None,
            docs_url="https://docs.runagac.com/user-defined-functions",
        )

    def _format_import_failure(
        self,
        module: str,
        file: str | None,
        error: str,
        exc: Exception,
        search_path: str | None,
        requested_path: str | None,
    ) -> UserError:
        details = f"Python could not import the UDF module: {error}"
        missing = self._extract_missing_module(error, exc)

        where = "the UDF file shown above" if file else "the UDF file that triggered this"
        if missing:
            fix = (
                f"Python could not find the module '{missing}'.\n"
                f"  If it is a third-party dependency, install it "
                f"(e.g. `uv add <package>` or `pip install <package>`) — "
                f"note the PyPI package name may differ from the import name "
                f"(yaml→PyYAML, cv2→opencv-python, bs4→beautifulsoup4).\n"
                f"  If '{missing}' is a local module, fix the import path in "
                f"{where}."
            )
        else:
            fix = (
                f"Fix the import error in {where}, then re-run.\n"
                "  The exact failure is included in the Problem line."
            )

        fix += (
            "\n\nThis file was found by the recursive scan of the -u tree. Fix its "
            "module-load code, or — if it is not a UDF — move it outside the -u "
            "directory so discovery skips it. A single broken file blocks every "
            "command that loads the workflow."
        )

        ctx: dict[str, Any] = {}
        if file:
            ctx["file_path"] = file
        if search_path:
            ctx["search_path"] = search_path
        if requested_path:
            ctx["requested_path"] = requested_path

        # Name the file, not the dotted module: discovery imported it from the
        # -u tree, so "Failed to load UDF module 'X'" read as if the user chose
        # it. Fall back to the module when no file path is available.
        if file:
            title = f"Auto-discovered UDF file failed to import: {file}"
        else:
            title = f"Auto-discovered UDF module failed to import: '{module}'"

        return UserError(
            category="Configuration Error",
            title=title,
            details=details,
            fix=fix,
            context=ctx or None,
            docs_url="https://docs.runagac.com/user-defined-functions",
        )

    @staticmethod
    def _extract_missing_module(error_text: str, exc: Exception) -> str | None:
        # Walk exc's __cause__ chain only — never __context__, and never
        # extract_root_cause's `root` (which transitively walks __context__
        # and could pick up an unrelated ModuleNotFoundError from the stack).
        current: BaseException | None = exc
        seen: set[int] = set()
        while current is not None and id(current) not in seen:
            seen.add(id(current))
            if isinstance(current, ModuleNotFoundError):
                name = getattr(current, "name", None)
                if isinstance(name, str) and name:
                    return name
            current = current.__cause__
        match = _MISSING_MODULE_RE.search(error_text or "")
        if not match:
            return None
        return match.group(1)
