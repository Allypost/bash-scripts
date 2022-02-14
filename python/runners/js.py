from .runner import get_runtimes_for, run_code


def run_js(payload: str, *, files: list[dict[str, str]] = None) -> str:
    return run_js_full(payload, files=files)["stdout"]


def run_js_full(payload: str, *, files: list[dict[str, str]] = None) -> dict:
    language = 'js'
    runtime = next(
        get_runtimes_for(language),
        None,
    )

    return run_code(
        language=runtime["language"],
        version=runtime["version"],
        code=payload,
        files=files,
    )
