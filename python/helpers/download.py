import traceback
from dataclasses import dataclass, field
import datetime
from enum import StrEnum, auto
from itertools import chain
import re
import subprocess
from typing import Callable, TypeVar
from urllib.parse import urlparse
from python.downloaders import get_download_info
from python.helpers.list import flatten
from python.helpers.size import human_byte_size
from python.log.console import Chalk, Console


def download_by_sites(
    *,
    download_sites: dict[str, str],
    episode_url: str,
    output_file: str,
    episode_number: int | float,
    forbidden_cdn_hostnames: list[str] | set[str] = [],
):
    Console.log_dim("Trying to find download link...", return_line=True)

    processed = 0
    for site in download_sites:
        processed += 1
        download_url = download_sites[site]
        try:
            download_info = get_download_info(download_url, episode_url)
            if download_info is None:
                raise NoHandlerException("No handler")

            url = download_info.url
            referer = download_info.referer or url

            parsed_url = urlparse(url)

            if parsed_url.hostname in forbidden_cdn_hostnames:
                Console.log(
                    f"{Chalk.colour(Chalk.italic)}Skipping {site}: {url}{Chalk.colour('23m')}"
                )
                continue

            Console.log(
                f"{Chalk.colour(Chalk.italic)}Downloading from {site}: {url}{Chalk.colour('23m')}"
            )

            Console.log_dim("Starting download...", return_line=True)
            download_cmd = [
                "yt-dlp",
                "--ignore-config",
                "--no-warnings",
                "--no-check-certificate",
                "--abort-on-unavailable-fragments",
                "--retries",
                "infinite",
                "--downloader",
                "ffmpeg",
                "--downloader-args",
                "-hide_banner -loglevel error -progress - -nostats",
                "--referer",
                referer,
                *list(
                    chain(
                        *[["--add-header", header] for header in download_info.headers]
                    )
                ),
                "--output",
                output_file,
                url,
            ]
            _download_line_native = re.compile(r"\[download\]\s+(\d+\.\d+%.*)")

            with subprocess.Popen(
                download_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=1,
                text=True,
            ) as proc:
                Console.log_dim("Waiting for download progress...", return_line=True)
                for line in proc.stdout or []:
                    # if download_line_native.search(line):
                    #     status = line.split(" ", maxsplit=1)[1].strip()
                    #     Console.log_dim(status, return_line=True)
                    #     continue

                    # Read lines until status stuff comes along
                    if line[0] == "[":
                        continue
                    break

                time_last_size_change = datetime.datetime.now()
                prev_size: str | None = None
                time_last_speed_gt_1 = datetime.datetime.now()
                prev_speed: str | None = None
                download_progress = DownloadProgressInfo()
                while proc.poll() is None:
                    try:
                        # Read status block
                        for line in proc.stdout or []:
                            if line.startswith("progress="):
                                break
                            key, value = line.strip().split("=", maxsplit=1)
                            download_progress.set(key, value)
                    except Exception:
                        pass

                    cur_speed = download_progress.get("speed", None)
                    cur_size = download_progress.get("total_size", None)

                    if cur_size != prev_size:
                        time_last_size_change = datetime.datetime.now()

                    if cur_speed is not None and float(cur_speed[:-1]) > 1:
                        time_last_speed_gt_1 = datetime.datetime.now()

                    size_same_for_s = (
                        datetime.datetime.now() - time_last_size_change
                    ).total_seconds()

                    if prev_size is not None and cur_size == prev_size:
                        is_processing = prev_speed == cur_speed
                        if not is_processing and size_same_for_s >= 30:
                            proc.kill()
                            raise DownloadStalledException("Stalled for too long")

                    if (
                        prev_speed is not None
                        and cur_speed is not None
                        and float(cur_speed[:-1]) < 1
                    ):
                        time_speed_lt_1 = (
                            datetime.datetime.now() - time_last_speed_gt_1
                        ).total_seconds()
                        if time_speed_lt_1 >= 60:
                            proc.kill()
                            raise DownloadStalledException("Speed too low")

                    prev_size = cur_size
                    prev_speed = cur_speed

                    Console.log_dim(
                        str(download_progress),
                        return_line=True,
                    )

                ecode = proc.wait()
                if ecode != 0:
                    if not proc.stderr:
                        raise Exception(f"Something broke ({ecode})")

                    proc_stderr = "\n  ".join(proc.stderr.readlines())

                    if "'Connection aborted.'" in proc_stderr:
                        Console.log_dim("Connection aborted. Discarding URL")
                        continue

                    print(subprocess.list2cmdline(download_cmd))
                    raise Exception(
                        f"Something broke ({ecode}):\nSTDERR:\n  {proc_stderr}"
                    )

            download_info.after_dl(output_file, download_info)
        except KeyboardInterrupt:
            continue
        except Exception as e:
            if isinstance(e, NoHandlerException):
                Console.log_dim(f"No handler for {download_url} on {site}")
                continue

            if isinstance(e, DownloadRecoverableException):
                Console.log_dim(f"Got recoverable error: {e}, skipping source")
                continue

            print(("\n" + "=" * 32) * 2)
            print(e, traceback.format_exc())
            print(("=" * 32 + "\n") * 2)

        for _ in range(processed):
            Console.clear_line()
            Console.move_up(1)
        Console.log_success(f"Episode {episode_number} downloaded")
        exit()

    Console.clear_line()
    Console.move_up(processed)
    Console.log_error(f"Failed to download episode {episode_number}")
    exit(1)


T = TypeVar("T")


@dataclass
class DownloadProgressInfo:
    _state: dict[str, str] = field(default_factory=dict)

    def set(self, key: str, value: str):
        self._state[key.strip()] = value.strip()

    def get(self, key: str, default):
        return self._state.get(key, default)

    def _s(self, key, pad=0, *, default="???") -> str:
        return self._state.get(key, default).rjust(pad, " ")

    def _s_if(self, key, pad=0, *, default="???"):
        if key in self._state:
            return self._s(key=key, pad=pad, default=default)
        return None

    @staticmethod
    def _chain_if(initial: T | None, *processors: Callable[[T], T]) -> T | None:
        fns = flatten(processors)
        for fn in fns:
            if initial is None:
                break
            initial = fn(initial)
        return initial

    def _get_output_layout(self):
        return [
            {"time": lambda: self._s_if("out_time")},
            "|",
            {
                "fps": lambda: self._s_if("fps", 6),
                "speed": lambda: self._s_if("speed", 5),
                "bitrate": lambda: self._s_if("bitrate", 6),
            },
            "|",
            {
                "size": lambda: self._chain_if(
                    self._s_if("total_size"),
                    lambda x: str(x).strip(),
                    lambda x: human_byte_size(x),
                )
            },
        ]

    def to_str(self):
        out: list[str] = []
        for item in self._get_output_layout():
            match item:
                case dict():
                    for name, value in item.items():
                        match value:
                            case gen if callable(gen):
                                res = gen()
                                if res is not None:
                                    out.append(f"{name}={res}")
                            case None:
                                out.append(f"{name}")
                            case value:
                                out.append(f"{name}={value}")
                case gen if callable(gen):
                    res = gen()
                    if res is not None:
                        out.append(res)
                case value:
                    out.append(str(value))
        return " ".join(out)

    def __str__(self) -> str:
        return self.to_str()


class DownloadRecoverableException(Exception):
    pass


class ConnectionAbortedException(DownloadRecoverableException):
    pass


class NoHandlerException(DownloadRecoverableException):
    pass


class DownloadStalledException(DownloadRecoverableException):
    pass


class DownloadByInfoEvent(StrEnum):
    WAITING_FOR_PROGRESS = auto()
    DOWNLOAD_PROGRESS = auto()
    ERROR = auto()
