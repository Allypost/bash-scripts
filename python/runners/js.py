from .runner import get_runtimes_for, run_code


def run_js(payload: str, *, files: list[dict[str, str]] | None = None) -> str | None:
    res = run_js_full(payload, files=files)
    if not res:
        return None
    return res["stdout"]


def run_js_full(
    payload: str, *, files: list[dict[str, str]] | None = None
) -> dict | None:
    language = "js"
    runtime = next(
        get_runtimes_for(language),
        None,
    )

    if not runtime:
        return None

    return run_code(
        language=runtime["language"],
        version=runtime["version"],
        code=payload,
        files=files,
    )
