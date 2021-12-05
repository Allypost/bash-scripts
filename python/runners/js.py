from .runner import get_runtimes_for, run_code


def run_js(payload: str) -> str:
    return run_js_full(payload)["stdout"]


def run_js_full(payload: str) -> dict:
    language = 'js'
    runtime = next(
        get_runtimes_for(language),
        None,
    )

    return run_code(
        language=runtime["language"],
        version=runtime["version"],
        code=payload,
    )
