import argparse
import os
from typing import Callable, Any


def parse_arguments(
    *,
    site_name: str,
    extend: Callable[[argparse.ArgumentParser], Any] | None = None,
):
    parser = argparse.ArgumentParser(
        description=f"Download videos from {site_name}",
        usage="%(prog)s -n 'series-name-here' [options]",
    )

    parser.add_argument(
        "series",
        help="Name (from the site URL) of the series you want to download (eg. 'shingeki-no-kyojin')",
        type=str,
        nargs="?",
    )

    parser.add_argument(
        "-n, --series-name",
        help="Name (from the site URL) of the series you want to download (eg. 'shingeki-no-kyojin')",
        type=str,
        nargs="?",
        dest="series_name",
    )

    parser.add_argument(
        "-e, --episode",
        help="Explicitly set which episode to download. Otherwise, latest non-downloaded episode is selected.",
        type=float,
        nargs="?",
        required=False,
        default=None,
        dest="episode",
    )

    parser.add_argument(
        "-f, --number-format",
        help="String format on how to name files. Defaults to: %02d",
        type=str,
        required=False,
        default="%02d",
        dest="number_format",
    )

    if extend:
        extend(parser)

    return parser.parse_args()


def get_episode_number_to_download(argv) -> float:
    if argv.episode:
        return argv.episode

    last_episode_number = os.popen(
        "ls | sort -h | grep -E '^[0-9]+\\.' | grep -Ev '\\.part$' | tail -n1 | cut -d'.' -f1"
    ).read()

    return float(last_episode_number or 0) + 1
