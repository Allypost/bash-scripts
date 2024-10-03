import argparse
import atexit
from dataclasses import dataclass, field
import json
import os
import signal
import sys
from typing import Callable, Any

from python.downloaders import sort_download_links
from python.helpers.download import download_by_sites
from python.helpers.list import flatten
from python.log.console import Chalk, Console


ParseArgumentsExtend = Callable[[argparse.ArgumentParser], Any]


@dataclass
class DownloadSite:
    name: str
    type: str
    url: str
    other: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict:
        return self.__dict__


def parse_arguments(
    *,
    site_name: str,
    extend: ParseArgumentsExtend | None = None,
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

    parser.add_argument(
        "-t --type",
        action="append",
        help="Whether to download the sub or dub",
        type=str,
        nargs="?",
        dest="series_types",
    )

    parser.add_argument(
        "--dump-download-sites",
        help="Dump the list of download sites and exit",
        required=False,
        dest="dump_download_sites",
        action="store_true",
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


def parse_series_types(*, series_types: list[str], allowed: list[str] | set[str]):
    series_types_raw = flatten([str(x).split(",") for x in list(series_types)])
    series_types_raw = [str(x).strip() for x in series_types_raw]
    series_types = [x for x in series_types_raw if x in allowed]

    if not series_types:
        raise Exception(
            f"No known series type provided. Got: {", ".join(series_types_raw)}. Allowed: {", ".join(allowed)}"
        )

    return series_types


def hide_cursor_until_exit():
    def handle_exit(_signum, _frame):
        Console.show_cursor()
        Console.clear_line()
        Console.log("Hard cancelling download.")
        sys.exit(2)

    Console.hide_cursor()
    atexit.register(Console.show_cursor)
    # signal.signal(signal.SIGINT, handle_exit)
    signal.signal(signal.SIGTERM, handle_exit)
    signal.signal(signal.SIGHUP, handle_exit)
    signal.signal(signal.SIGQUIT, handle_exit)


@dataclass
class DownloadSitesCtx:
    series_name: str
    episode_number: float
    series_types: list[str] | set[str]


class EpisodeNumberNotFoundException(Exception):
    pass


def downloader_main(
    *,
    site_name: str,
    episode_page_url_fn: Callable[[str], str],
    download_sites_fn: Callable[[DownloadSitesCtx], list[DownloadSite] | None],
    allowed_series_types: list[str] | set[str],
    with_additional_args: ParseArgumentsExtend | None = None,
    forbidden_cdn_hostnames: list[str] | set[str] = [],
):
    hide_cursor_until_exit()

    argv = parse_arguments(site_name=site_name, extend=with_additional_args)

    series_name = argv.series_name or argv.series
    number_format = argv.number_format
    series_types = parse_series_types(
        series_types=argv.series_types,
        allowed=allowed_series_types,
    )

    if series_name is None:
        raise Exception("No series name")

    episode_number_offset = float(argv.offset)
    episode_number = get_episode_number_to_download(argv) - episode_number_offset

    offset_str = (
        f" (offset episode {episode_number + episode_number_offset})"
        if episode_number_offset
        else ""
    )

    Console.log(
        f"Downloading {Chalk.badge(series_name, Chalk.black, Chalk.bg_yellow_bright)} episode {Chalk.badge(str(episode_number) + offset_str, Chalk.black, Chalk.bg_blue_bright)}"
    )

    try:
        download_sites = download_sites_fn(
            DownloadSitesCtx(
                series_name=series_name,
                episode_number=episode_number,
                series_types=series_types,
            )
        )
    except EpisodeNumberNotFoundException:
        Console.log_error(f"Episode {episode_number}{offset_str} can't be found")
        exit(1)

    if not download_sites:
        Console.log_error(
            f"Couldn't download {episode_number}: No download servers found"
        )
        exit(1)

    sorted_download_site_urls = sort_download_links(
        download_sites,
        to_url=lambda x: x.url,
    )
    series_types_order = {t: i for i, t in enumerate(series_types)}
    sorted_download_site_urls = list(
        sorted(
            sorted_download_site_urls,
            key=lambda x: series_types_order.get(x.type, 9999),
        )
    )

    if argv.dump_download_sites:
        Console.clear_line()
        Console.log(
            json.dumps(
                sorted_download_site_urls, default=lambda o: o.__dict__, indent=2
            )
        )
        Console.log(json.dumps(download_sites, default=lambda o: o.__dict__, indent=2))
        exit(0)

    download_by_sites(
        download_sites={
            f"{item.name} {item.type}": item.url for item in sorted_download_site_urls
        },
        episode_number=episode_number,
        episode_url=episode_page_url_fn(series_name),
        output_file=f"{number_format % (episode_number + episode_number_offset)}.mp4",
        forbidden_cdn_hostnames=forbidden_cdn_hostnames,
    )
