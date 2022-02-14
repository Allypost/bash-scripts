import json
import requests

"""
files[].name (optional) The name of the file to upload, must be a string containing no path or left out.
files[].content (required) The content of the files to upload, must be a string containing text to write.
files[].encoding (optional) The encoding scheme used for the file content. One of base64, hex or utf8. Defaults to utf8.
"""


def run_code(language: str, version: str, code: str, *, files: list[dict[str, str]] = None) -> str:
    response = requests.post(
        url="https://emkc.org/api/v2/piston/execute",
        json={
            "language": language,
            "version": version,
            "files": [
                {
                    "content": code,
                },
                *(files or []),
            ],
        },
    )

    resp = response.json()

    if "run" not in resp:
        raise Exception("Something went wrong while running the code")

    return response.json()["run"]


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
