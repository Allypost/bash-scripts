import requests


def run_code(language: str, version: str, code: str) -> str:
    response = requests.post(
        url="https://emkc.org/api/v2/piston/execute",
        json={
            "language": language,
            "version": version,
            "files": [
                {
                    "content": code,
                },
            ],
        },
    ).json()

    return response["run"]["stdout"]


def get_runtimes():
    return requests.get("https://emkc.org/api/v2/piston/runtimes").json()


def get_runtimes_for(language: str):
    runtimes = get_runtimes()

    return (
        runtime_info
        for runtime_info in runtimes
        if (
            ("runtime" in runtime_info and runtime_info["runtime"] == language)
            or
            ("aliases" in runtime_info and language in runtime_info["aliases"])
        )
    )
