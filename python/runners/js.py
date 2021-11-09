from .runner import get_runtimes_for, run_code


def run_js(payload: str) -> str:
    language = 'js'
    runtime = next(
        get_runtimes_for(language),
        None,
    )

    return run_code(
        language=language,
        version=runtime["version"],
        code=payload,
    )
