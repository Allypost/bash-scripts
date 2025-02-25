import json
import os
import re
import subprocess
import tempfile
import urllib.parse
from dataclasses import dataclass, field
from fractions import Fraction
from itertools import chain
from typing import Callable, Dict, List, TypeVar, Union, cast
from urllib.parse import (
    quote_plus as encode_url_component,
)
from urllib.parse import (
    urljoin,
    urlparse,
    urlunparse,
)

import cloudscraper
import requests
from bs4 import BeautifulSoup, Tag

from python.helpers.deobfuscator import DefaultPlayerDeobfuscator
from python.helpers.retried_download import retried_download
from python.log.console import Console

try:
    import playwright.sync_api
except ImportError as err:
    print("Installing playwright...")
    assert os.system("pip install playwright") == 0
    assert os.system("playwright install firefox") == 0
import playwright.sync_api
from playwright.sync_api import sync_playwright

from .runners.js import run_js

REQUEST_TIMEOUT_SECONDS = 10.0
REQUEST_TIMEOUT_DEOBFUSCATE_SECONDS = 60.0
DEFAULT_USER_AGENT = os.getenv(
    "DOWNLOADERS_USER_AGENT",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.6613.127 Safari/537.36",
)


@dataclass
class DownloadInfo:
    url: str
    referer: Union[str, None] = None
    headers: list[str] = field(default_factory=list)
    after_dl: Callable[[str, "DownloadInfo"], None] = lambda x, y: None


HandlerFuncReturn = Union[None, DownloadInfo]


def handle__instagram_com(url: str) -> Union[List[str], None]:
    SESSION_ID_FILE = os.path.join(
        os.path.expanduser("~"),
        "./.config/.secrets/instagram",
    )

    def parse_url(raw_url: str) -> dict:
        url = raw_url.strip()

        if url.find("://") == -1 and not url.startswith("//"):
            parsed_url = urllib.parse.urlparse("//" + url, "http")
        else:
            parsed_url = urllib.parse.urlparse(url)

        res = parsed_url._asdict()
        if res["query"]:
            res["query"] = urllib.parse.parse_qs(res["query"])

        return res

    def session_cookie() -> str:
        if not os.path.isfile(SESSION_ID_FILE):
            return ""

        with open(SESSION_ID_FILE) as f:
            return f"sessionid={f.readline()}".strip()

    def get_api_response(id: str) -> requests.Response:
        query_hash = "2efa04f61586458cef44441f474eee7c"
        query_args = {
            "shortcode": id,
            "child_comment_count": 0,
            "fetch_comment_count": 0,
            "parent_comment_count": 0,
            "has_threaded_comments": True,
        }

        api_url = f"https://www.instagram.com/graphql/query/?query_hash={query_hash}&variables={urllib.parse.quote(json.dumps(query_args))}"

        return requests.get(
            api_url,
            headers={
                "Cookie": session_cookie(),
                "User-Agent": DEFAULT_USER_AGENT,
            },
            timeout=REQUEST_TIMEOUT_SECONDS,
        )

    url_info = parse_url(raw_url=url)

    # `url_info["path"]` should be of format `/p/$POST_ID/`
    post_id = url_info["path"].split("/")[-2]

    r = get_api_response(id=post_id)

    try:
        json_response = r.json()
        edges = json_response["data"]["shortcode_media"]

        if "edge_sidecar_to_children" not in edges:
            return [edges["display_url"]]
        else:
            edges = edges["edge_sidecar_to_children"]["edges"]

        media_urls = [
            entry["node"].get("video_url", entry["node"]["display_url"])
            for entry in edges
        ]

        return media_urls
    except ValueError:
        return None


def handle__streamani_net(url: str) -> HandlerFuncReturn:
    return None


def handle__sbplay_one(url: str) -> HandlerFuncReturn:
    download_page = url.replace("/e/", "/d/")
    page_html = (
        cloudscraper.create_scraper()
        .get(
            download_page,
            headers={"User-Agent": DEFAULT_USER_AGENT},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        .text
    )

    download_links = (
        BeautifulSoup(page_html, "html.parser")
        .find(class_="contentbox")
        .find("table")
        .find_all("td")
    )

    @dataclass
    class Info:
        id: str
        mode: str
        hash: str

    def fix_pair(pair):
        link_, info_ = pair

        file_id, mode, file_hash = (
            link_.find("a")["onclick"]
            .replace("download_video", "")[1:-1]
            .replace("'", "")
            .split(",")
        )

        w, h = info_.text.strip().split(",")[0].split("x")

        return (
            Info(
                id=file_id,
                mode=mode,
                hash=file_hash,
            ),
            (
                int(w),
                int(h),
            ),
        )

    info = sorted(
        [fix_pair(download_links[i : i + 2]) for i in range(0, len(download_links), 2)],
        key=lambda x: x[1],
        reverse=True,
    )[0][0]

    download_generator_url = f"https://sbplay.one/dl?op=download_orig&id={info.id}&mode={info.mode}&hash={info.hash}"

    page_html = (
        cloudscraper.create_scraper()
        .get(
            download_generator_url,
            headers={"User-Agent": DEFAULT_USER_AGENT},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        .text
    )

    download_link = (
        BeautifulSoup(page_html, "html.parser")
        .find(class_="contentbox")
        .find("a")["href"]
    )

    return DownloadInfo(url=download_link, referer=download_generator_url)


def handle__mixdrop_co(url: str) -> HandlerFuncReturn:
    page_html = (
        cloudscraper.create_scraper()
        .get(
            url,
            headers={"User-Agent": DEFAULT_USER_AGENT},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        .text
    )

    script_data = (
        BeautifulSoup(page_html, "html.parser")
        .find(lambda tag: tag.name == "script" and "MDCore.ref" in str(tag.string))
        .string.strip()
    )

    payload = f"const MDCore = {{}}; {script_data}; process.stdout.write(`https:${{MDCore.wurl}}`);"

    download_url = run_js(payload)

    if download_url == "https:undefined":
        return None

    return DownloadInfo(url=download_url, referer=url)


def handle__vidplay_xyz(url: str) -> HandlerFuncReturn:
    parsed_url = urllib.parse.urlparse(url)
    base_url = f"{parsed_url.scheme}://{parsed_url.netloc}"
    scraper = cloudscraper.create_scraper()

    page_url_id = parsed_url.path.split("/")[-1]

    Console.log_dim("Got encrypted response. Breaking...", return_line=True)

    item_id_resp = DefaultPlayerDeobfuscator.get(
        f"/vrf/vidplay?vrf_data={encode_url_component(page_url_id)}",
    )
    if not item_id_resp:
        return None

    Console.log_dim("Got decrypted response. Fetching sources...", return_line=True)

    try:
        item_id_vrf = item_id_resp["vrf"]
    except Exception:
        return None

    resp = scraper.get(
        f"{base_url}/mediainfo/{item_id_vrf}?{parsed_url.query}",
        headers={
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Accept-Language": "en-US,en;q=0.5",
            "Cache-Control": "no-cache",
            "Referer": url,
            "X-Requested-With": "XMLHttpRequest",
        },
        timeout=REQUEST_TIMEOUT_SECONDS,
    )

    if not resp.ok:
        return None

    try:
        resp_json = resp.json()
        resp_json_vrf = resp_json["result"]

        resp_json_resp = DefaultPlayerDeobfuscator.post(
            "/vrf/vidplay/devrf",
            json={
                "vrf": resp_json_vrf,
            },
        )

        if not resp_json_resp:
            return None

        resp_json = resp_json_resp["vrf_data"]
        resp_json = json.loads(resp_json)

        sources = list(resp_json["sources"])

        if len(sources) > 1:
            print("Found multiple sources, using the first one", sources)

        Console.log_dim("Got sources.", return_line=True)

        source = dict(sources[0])

        if len(dict(source).keys()) > 1:
            print("Found multiple formats, using the first one", source)

        tracks = resp_json.get("tracks")

        def after_dl(output_file: str, download_info: DownloadInfo):
            Console.log_dim("Donwnload done. Embedding metadata...", return_line=True)
            if not tracks:
                return None

            @dataclass
            class Metadata:
                title: Union[str, None] = None
                chapters: list["Chapter"] = field(default_factory=list)

                def has_data(self) -> bool:
                    return self.title is not None or len(self.chapters) > 0

                def __str__(self) -> str:
                    parts = []

                    if self.title:
                        parts.append(f"title={self.title}")

                    if self.chapters:
                        parts.extend(self.chapters)

                    ret = ";FFMETADATA1\n"
                    ret += "\n\n".join(map(lambda x: str(x).strip(), parts))
                    return ret.strip()

            @dataclass
            class Chapter:
                timebase: Fraction
                start: int
                end: int
                title: Union[str, None] = None

                def __post_init__(self):
                    if self.start > self.end:
                        raise ValueError("Start must be less than end")

                    if self.start < 0:
                        raise ValueError("Start must be greater than 0")

                    if self.end < 0:
                        raise ValueError("End must be greater than 0")

                    if self.timebase > 1:
                        raise ValueError("Timebase must be a fraction less than 1")

                def __str__(self) -> str:
                    parts = []
                    if self.timebase:
                        (num, den) = self.timebase.as_integer_ratio()
                        parts.append(f"TIMEBASE={num}/{den}")
                    if self.start:
                        parts.append(f"START={str(self.start)}")
                    if self.end:
                        parts.append(f"END={str(self.end)}")
                    if self.title:
                        parts.append(f"title={self.title}")

                    ret = "[CHAPTER]\n"
                    ret += "\n".join(map(lambda x: x.strip(), parts))
                    return ret.strip()

            metadata = Metadata()
            keep_characters = (" ", ".", "_", "-")

            def safe_char(c):
                if c.isalnum() or c in keep_characters:
                    return c
                return "_"

            subtitles = [
                {
                    "lang": track["label"],
                    "file_name": (
                        "".join([safe_char(c) for c in track["label"]]).rstrip()
                        + ".vtt"
                    ).replace(r"_+", "_"),
                    "url": track["file"],
                }
                for track in tracks
                if "captions" == track.get("kind")
            ]

            cleanup_files = []

            cmd_inputs = [
                (output_file, cast(bool, True)),
            ]

            metadata_cmd = []
            if metadata.has_data():
                f = tempfile.NamedTemporaryFile(
                    prefix=f"vidplay_xyz_metadata.{item_id_vrf}.",
                    suffix=".txt",
                    mode="w+",
                    encoding="utf-8",
                )
                f.write(str(metadata))
                f.flush()
                cleanup_files.append(f)
                cmd_inputs.append((f.name, False))
                metadata_cmd.extend(
                    [
                        "-map_metadata",
                        len(cmd_inputs) - 1,
                    ]
                )

            for sub in subtitles:
                cmd_inputs.append((sub["url"], True))

            cmd = [
                "ffmpeg",
                *list(
                    chain(
                        *[["-i", cmd_input] for (cmd_input, _should_map) in cmd_inputs]
                    )
                ),
                *list(
                    chain(
                        *[
                            [
                                "-map",
                                str(i),
                            ]
                            for (i, (_cmd_input, should_map)) in enumerate(cmd_inputs)
                            if should_map
                        ]
                    )
                ),
                *metadata_cmd,
                "-c",
                "copy",
                *list(
                    chain(
                        *[
                            [
                                f"-metadata:s:s:{i}",
                                f'language="{sub["lang"]}"',
                            ]
                            for i, sub in enumerate(subtitles)
                        ]
                    )
                ),
                os.path.splitext(output_file)[0] + ".mkv",
            ]
            cmd = list(map(str, cmd))
            Console.log_dim("Embedding subtitles...", return_line=True)
            with subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                bufsize=1,
                text=True,
            ) as proc:
                res = proc.wait()

                for f in cleanup_files:
                    f.close()

                if res != 0:
                    return None

            os.remove(output_file)

        return DownloadInfo(
            url=source["file"],
            referer=url,
            after_dl=after_dl,
        )
    except Exception:
        return None


def handle__embedsito_com(url: str) -> HandlerFuncReturn:
    api_id = url.split("/")[-1]
    resp = (
        cloudscraper.create_scraper()
        .post(
            f"https://embedsito.com/api/source/{api_id}",
            headers={
                "accept": "*/*",
                "accept-language": "en-GB,en;q=0.9,hr;q=0.8,de;q=0.7",
                "content-type": "application/x-www-form-urlencoded; charset=UTF-8",
                "x-requested-with": "XMLHttpRequest",
                "referer": url,
            },
            data="r=&d=embedsito.com",
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        .json()["data"]
    )

    return DownloadInfo(
        url=sorted(
            resp,
            key=lambda k: int(k["label"][:-1]),
            reverse=True,
        )[0]["file"],
        referer=url,
    )


def handle__filemoon_sx(url: str) -> HandlerFuncReturn:
    page_html = (
        cloudscraper.create_scraper()
        .get(
            url,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        .text
    )
    packed_script = BeautifulSoup(page_html, "html.parser").find(
        lambda tag: tag.name == "script" and "function(p,a,c,k,e,d)" in str(tag.string)
    )

    if isinstance(packed_script, Tag):
        packed_script = packed_script.string
    else:
        return None

    if not packed_script:
        return None

    payload_regex = r"/\.setup\((\{.*?\})\);/"
    payload = f"""
    const fn = {packed_script[4:]};
    const fnStr = fn.toString();
    const fnDataMatch = {payload_regex}.exec(fnStr);
    const fnData = fnDataMatch[1];
    eval(`var fnFinalData = ${"{fnData}"};`);
    console.log(JSON.stringify(fnFinalData["sources"]));
    """
    r = run_js(payload)

    if not r:
        return None

    try:
        video_info = json.loads(r)
        sources = video_info
        if len(sources) == 0:
            return None

        source = sources[0]

        video_url = source["file"]
    except Exception:
        return None

    return DownloadInfo(url=video_url, referer=url)


def handle__pahe_win(url: str, referer: str) -> HandlerFuncReturn:
    response = retried_download(
        "pahe.win page",
        lambda: cloudscraper.create_scraper().get(
            url,
            timeout=REQUEST_TIMEOUT_SECONDS,
            headers={
                "referer": referer,
            },
        ),
    )

    if not response:
        return None

    page_html = response.text
    script_tag = BeautifulSoup(page_html, "html.parser").find(
        lambda tag: tag.name == "script" and "a.redirect" in str(tag.string)
    )

    if not isinstance(script_tag, Tag):
        return None

    script_tag = script_tag.string

    if not script_tag:
        return None

    redirect_url = re.search(
        r'\$\("a.redirect"\).attr\("href","([^"]+)"\).html\("Continue"\);', script_tag
    )
    if not redirect_url:
        return None
    redirect_url = redirect_url.group(1)

    return get_download_info(redirect_url, url)


def handle__kwik_si(url: str, referer: str) -> HandlerFuncReturn:
    scraper = cloudscraper.create_scraper()

    def handle_embed(url: str):
        response = retried_download(
            "kwik.si embed page",
            lambda: scraper.get(
                url,
                timeout=REQUEST_TIMEOUT_SECONDS,
                headers={
                    "referer": referer,
                },
            ),
            max_tries=20,
        )

        if not response:
            return None

        page_html = response.text

        script_with_src = BeautifulSoup(page_html, "html.parser").find(
            lambda tag: tag.name == "script"
            and "eval(" in str(tag.string)
            and ";eval(" in str(tag.string)
        )
        script_with_src = (
            script_with_src.string if isinstance(script_with_src, Tag) else None
        )

        if not script_with_src:
            return None

        interesting_code = script_with_src.split(";eval(")[1][:-1]
        code_to_run = f"console.log(String({interesting_code}.substring(0, 1500))"
        run_js_result = run_js(code_to_run)
        if not run_js_result:
            Console.log_dim("Couldn't run js for kwik.si embed page")
            return None

        source_match = re.search(r"source\s*=\s*'([^']+)'\s*;", run_js_result)
        source = source_match.group(1) if source_match else None
        if not source:
            Console.log_dim("Couldn't find source for kwik.si embed page")
            return None

        return source

    def handle_info(url: str):
        response = retried_download(
            "kwik.si info page",
            lambda: scraper.get(
                url,
                timeout=REQUEST_TIMEOUT_SECONDS,
                headers={
                    "referer": referer,
                },
            ),
            max_tries=20,
        )

        if not response:
            return None

        page_html = response.text
        script_with_src = BeautifulSoup(page_html, "html.parser").find(
            lambda tag: tag.name == "script"
            and "decodeURIComponent(escape(" in str(tag.string)
        )
        if isinstance(script_with_src, Tag):
            script_with_src = script_with_src.string
        else:
            Console.log_dim("Couldn't find script with src for kwik.si embed page")
            script_with_src = None

        if not script_with_src:
            return None

        src_without_eval = (
            r'var _ENCODE_URI_TO_ESCAPE_LUT = [["!","%21"],["\'","%27"],["(","%28"],[")","%29"],["+","+"],["/","/"],["@","@"],["~","%7E"],["%C2%80","%80"],["%C2%81","%81"],["%C2%82","%82"],["%C2%83","%83"],["%C2%84","%84"],["%C2%85","%85"],["%C2%86","%86"],["%C2%87","%87"],["%C2%88","%88"],["%C2%89","%89"],["%C2%8A","%8A"],["%C2%8B","%8B"],["%C2%8C","%8C"],["%C2%8D","%8D"],["%C2%8E","%8E"],["%C2%8F","%8F"],["%C2%90","%90"],["%C2%91","%91"],["%C2%92","%92"],["%C2%93","%93"],["%C2%94","%94"],["%C2%95","%95"],["%C2%96","%96"],["%C2%97","%97"],["%C2%98","%98"],["%C2%99","%99"],["%C2%9A","%9A"],["%C2%9B","%9B"],["%C2%9C","%9C"],["%C2%9D","%9D"],["%C2%9E","%9E"],["%C2%9F","%9F"],["%C2%A0","%A0"],["%C2%A1","%A1"],["%C2%A2","%A2"],["%C2%A3","%A3"],["%C2%A4","%A4"],["%C2%A5","%A5"],["%C2%A6","%A6"],["%C2%A7","%A7"],["%C2%A8","%A8"],["%C2%A9","%A9"],["%C2%AA","%AA"],["%C2%AB","%AB"],["%C2%AC","%AC"],["%C2%AD","%AD"],["%C2%AE","%AE"],["%C2%AF","%AF"],["%C2%B0","%B0"],["%C2%B1","%B1"],["%C2%B2","%B2"],["%C2%B3","%B3"],["%C2%B4","%B4"],["%C2%B5","%B5"],["%C2%B6","%B6"],["%C2%B7","%B7"],["%C2%B8","%B8"],["%C2%B9","%B9"],["%C2%BA","%BA"],["%C2%BB","%BB"],["%C2%BC","%BC"],["%C2%BD","%BD"],["%C2%BE","%BE"],["%C2%BF","%BF"],["%C3%80","%C0"],["%C3%81","%C1"],["%C3%82","%C2"],["%C3%83","%C3"],["%C3%84","%C4"],["%C3%85","%C5"],["%C3%86","%C6"],["%C3%87","%C7"],["%C3%88","%C8"],["%C3%89","%C9"],["%C3%8A","%CA"],["%C3%8B","%CB"],["%C3%8C","%CC"],["%C3%8D","%CD"],["%C3%8E","%CE"],["%C3%8F","%CF"],["%C3%90","%D0"],["%C3%91","%D1"],["%C3%92","%D2"],["%C3%93","%D3"],["%C3%94","%D4"],["%C3%95","%D5"],["%C3%96","%D6"],["%C3%97","%D7"],["%C3%98","%D8"],["%C3%99","%D9"],["%C3%9A","%DA"],["%C3%9B","%DB"],["%C3%9C","%DC"],["%C3%9D","%DD"],["%C3%9E","%DE"],["%C3%9F","%DF"],["%C3%A0","%E0"],["%C3%A1","%E1"],["%C3%A2","%E2"],["%C3%A3","%E3"],["%C3%A4","%E4"],["%C3%A5","%E5"],["%C3%A6","%E6"],["%C3%A7","%E7"],["%C3%A8","%E8"],["%C3%A9","%E9"],["%C3%AA","%EA"],["%C3%AB","%EB"],["%C3%AC","%EC"],["%C3%AD","%ED"],["%C3%AE","%EE"],["%C3%AF","%EF"],["%C3%B0","%F0"],["%C3%B1","%F1"],["%C3%B2","%F2"],["%C3%B3","%F3"],["%C3%B4","%F4"],["%C3%B5","%F5"],["%C3%B6","%F6"],["%C3%B7","%F7"],["%C3%B8","%F8"],["%C3%B9","%F9"],["%C3%BA","%FA"],["%C3%BB","%FB"],["%C3%BC","%FC"],["%C3%BD","%FD"],["%C3%BE","%FE"],["%C3%BF","%FF"]];'
            + """
            ;
            function escape(string) {
                let str = encodeURI(string);
                for (const [encodeUriChar, escapeChar] of _ENCODE_URI_TO_ESCAPE_LUT) {
                    str = str.replaceAll(encodeUriChar, escapeChar);
                }
                return str;
            }
            function __HANDLE_RESULT(result) {
                result = String(result);
                var resultLen = result.length;
                var last1500Chars = String(result).substr(resultLen - 1500, 1500);
                console.log(last1500Chars);
            }
            ;
            """
            + script_with_src.replace("eval(", "__HANDLE_RESULT(")
        )
        run_js_result = run_js(src_without_eval)
        if not run_js_result:
            Console.log_dim("kwik.si info page js eval failed")
            return None

        form_match = re.search(
            r'(<form action="https://kwik.si/d/[^"]+" method="POST">[^\']+</form>)',
            run_js_result,
        )
        form_match = form_match.group(1) if form_match else None
        if not form_match:
            Console.log_dim("Couldn't find form in kwik.si eval result")
            return None

        form_match = BeautifulSoup(form_match, "html.parser").find("form")
        if not isinstance(form_match, Tag):
            Console.log_dim("Couldn't find form in kwik.si eval result")
            return None
        download_url = form_match.attrs["action"]
        download_token = form_match.select_one('input[type=hidden][name="_token"]')
        if not isinstance(download_token, Tag):
            Console.log_dim("Couldn't find download token in kwik.si eval result")
            return None
        download_token = download_token.attrs["value"]

        try:
            download_resp = scraper.post(
                download_url,
                data=f"_token={download_token}",
                headers={
                    "content-type": "application/x-www-form-urlencoded",
                    "referer": url,
                    "origin": f"{parsed_url.scheme}://{parsed_url.netloc}",
                },
                allow_redirects=False,
            )
        except Exception as e:
            Console.log_dim(f"Got exception while downloading: {e}")
            return None

        redirect_url = download_resp.headers.get("location")
        if not redirect_url:
            Console.log_dim("Couldn't find redirect url for kwik.si download thing")
            return None

        return redirect_url

    parsed_url = urlparse(url)
    url_path_parts = parsed_url.path.split("/")
    url_type = url_path_parts[-2]

    m3u8_url: None | str = None
    match url_type:
        case "e":
            m3u8_url = handle_embed(url)
        case "f":
            m3u8_url = handle_info(url)

    if not m3u8_url:
        return None

    user_agent_headers = scraper.user_agent.headers
    user_agent = user_agent_headers["User-Agent"] if user_agent_headers else None

    return DownloadInfo(
        url=m3u8_url,
        referer=url,
        headers=[
            f"user-agent: {user_agent}",
        ],
    )


def handle__www_mp4upload_com(url: str) -> HandlerFuncReturn:
    page_html = (
        cloudscraper.create_scraper()
        .get(
            url,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        .text
    )
    script_with_src = BeautifulSoup(page_html, "html.parser").find(
        lambda tag: tag.name == "script" and " src: " in str(tag.string)
    )

    if isinstance(script_with_src, Tag):
        script_with_src = script_with_src.string
    else:
        script_with_src = None

    if not script_with_src:
        return None

    src_match = re.search(r'\s*src:\s*"([^"]+)"', script_with_src)
    if not src_match:
        return None
    src_match = src_match.group(1)
    if not src_match:
        return None

    src_match = src_match.replace('\\"', '"')

    return DownloadInfo(url=src_match, referer=url)


def handle__ani_googledrive_stream(url: str) -> HandlerFuncReturn:
    download_url = os.popen(f"yt-dlp --get-url '{url}'").read().strip()

    return DownloadInfo(url=download_url, referer=url)


def handle__play_api_web_site(url: str) -> HandlerFuncReturn:
    url_info = urllib.parse.urlparse(url)
    request = cloudscraper.create_scraper().post(
        "https://play.api-web.site/src.php",
        data={
            "id": urllib.parse.parse_qs(url_info.query)["id"],
        },
        timeout=REQUEST_TIMEOUT_SECONDS,
    )

    if not request.status_code:
        return None

    urls = request.json()["url"]
    sorted_urls = sorted(urls, key=lambda x: x["size"], reverse=True)

    return DownloadInfo(
        url=sorted_urls[0]["src"],
        referer=url,
    )


def handle__gogoplay1_com(url: str) -> HandlerFuncReturn:
    def get_embedplus_data(url: str) -> HandlerFuncReturn:
        response = cloudscraper.create_scraper().get(
            url,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        if not response:
            return None
        page_html = response.text

        page = BeautifulSoup(page_html, "html.parser")

        attr_script_crypto_a = page.find("body")["class"][0].split("-")[1]
        attr_script_crypto_b = page.find(
            lambda tag: tag.name == "div"
            and "class" in tag.attrs
            and "wrapper" in tag.attrs["class"]
            and [x for x in tag.attrs["class"] if x.startswith("container-")]
        )["class"]
        attr_script_crypto_b = [
            x for x in attr_script_crypto_b if x.startswith("container-")
        ][0].split("-")[1]
        attr_script_crypto_c = page.find(
            lambda tag: tag.name == "div"
            and "class" in tag.attrs
            and [x for x in tag.attrs["class"] if x.startswith("videocontent-")]
        )["class"]
        attr_script_crypto_c = [
            x for x in attr_script_crypto_c if x.startswith("videocontent-")
        ][0].split("-")[1]
        attr_script_crypto = page.find("script", attrs={"data-name": "episode"}).attrs[
            "data-value"
        ]

        current_file_path = os.path.dirname(os.path.realpath(__file__))
        lib_path = os.path.join(
            current_file_path,
            "runners",
            "libraries",
            "js",
            "crypto-js.min.js",
        )

        with open(lib_path) as f:
            lib_contents = f.read()

        result = run_js(
            f"""
                const CryptoJS = require('./crypto');

                const attr_script_crypto_a = {json.dumps(attr_script_crypto_a)};
                const attr_script_crypto_b = {json.dumps(attr_script_crypto_b)};
                const attr_script_crypto = {json.dumps(attr_script_crypto)};

                const candon = 
                    CryptoJS['AES']['decrypt'](attr_script_crypto, CryptoJS['enc']['Utf8'].parse(attr_script_crypto_a), {{
                        iv: CryptoJS.enc['Utf8']['parse'](attr_script_crypto_b)
                    }})
                ;
                const elver = CryptoJS['enc']['Utf8']['stringify'](candon);
                const dandrell = elver.substr(0, elver.indexOf("&"));

                process.stdout.write(
                    '/encrypt-ajax.php?id=' + CryptoJS.AES['encrypt'](
                        dandrell,
                        CryptoJS.enc.Utf8['parse'](attr_script_crypto_a),
                        {{
                            iv: CryptoJS['enc']['Utf8'].parse(attr_script_crypto_b)
                        }}
                    )['toString']() + elver.substr(elver['indexOf']("&")) + '&alias=' + dandrell
                );
            """,
            files=[
                {
                    "name": "crypto.js",
                    "content": lib_contents,
                },
            ],
        )

        parsed = urllib.parse.urlparse(url)
        api_url = f"{parsed.scheme}://{parsed.netloc}{result}"

        response = cloudscraper.create_scraper().get(
            api_url,
            headers={
                "User-Agent": DEFAULT_USER_AGENT,
                "Referer": url,
                "x-requested-with": "XMLHttpRequest",
            },
            timeout=REQUEST_TIMEOUT_DEOBFUSCATE_SECONDS,
        )

        if not response:
            return None

        api_response = response.json()

        result = run_js(
            f"""
                const CryptoJS = require('./crypto');

                const attr_script_crypto_b = {json.dumps(attr_script_crypto_b)};
                const attr_script_crypto_c = {json.dumps(attr_script_crypto_c)};

                const resp = {json.dumps(api_response)};

                process.stdout.write(
                    CryptoJS.enc.Utf8.stringify(
                        CryptoJS['AES'].decrypt(
                            resp['data'],
                            CryptoJS['enc'].Utf8['parse'](attr_script_crypto_c),
                            {{
                                iv: CryptoJS['enc']['Utf8']['parse'](attr_script_crypto_b)
                            }},
                        ),
                    ),
                );
            """,
            files=[
                {
                    "name": "crypto.js",
                    "content": lib_contents,
                },
            ],
        )

        if not result:
            return None

        api_response = json.loads(result)

        sources = sorted(
            [
                [
                    int(source["label"][:-2]) if source["label"][:-2].isdigit() else 0,
                    source["file"],
                ]
                for source in api_response["source"]
                if source["label"][-1] == "P"
            ],
            key=lambda x: x[0],
        )

        return DownloadInfo(
            url=sources[-1][1],
            referer=url,
        )

    parsed = urllib.parse.urlparse(url)
    url_path = parsed.path

    if url_path == "/embedplus" or url_path == "/streaming.php":
        return get_embedplus_data(url)
    else:
        return None


def handle__dood_ws(url: str) -> HandlerFuncReturn:
    response = cloudscraper.create_scraper().get(
        url,
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    if not response:
        return None
    page_html = response.text

    something_url = re.search(r"\$.get\('/pass_md5/([^']+)", page_html, re.IGNORECASE)
    if not something_url:
        return None
    parsed_url = urlparse(url)
    something_url = parsed_url._replace(path=f"/pass_md5/{something_url.group(1)}")
    something_url = urlunparse(something_url)

    response = cloudscraper.create_scraper().get(
        something_url,
        headers={
            "User-Agent": DEFAULT_USER_AGENT,
            "Referer": url,
        },
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    if not response:
        return None

    return DownloadInfo(
        url=response.text,
        referer=url,
    )


def handle__fembed_hd_com(url: str) -> HandlerFuncReturn:
    file_id = url.split("/")[-1]
    response = cloudscraper.create_scraper().post(
        f"https://fembed-hd.com/api/source/{file_id}",
        data={
            "r": "",
            "d": "fembed-hd.com",
        },
        headers={
            "User-Agent": DEFAULT_USER_AGENT,
            "Referer": url,
            "x-requested-with": "XMLHttpRequest",
        },
        timeout=REQUEST_TIMEOUT_SECONDS,
    )

    if not response:
        return None

    data = response.json()
    files = sorted(
        [
            [
                int(x["label"][:-1]),
                x["file"],
            ]
            for x in data["data"]
        ],
        key=lambda x: x[0],
    )

    best_file = files[-1][1]

    return DownloadInfo(
        url=best_file,
        referer=url,
    )


def handle__streamtape_net(url: str) -> HandlerFuncReturn:
    response = cloudscraper.create_scraper().get(
        url,
        headers={
            "User-Agent": DEFAULT_USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9",
            "Referer": url,
        },
        timeout=REQUEST_TIMEOUT_SECONDS,
    )

    if not response:
        return None

    page_html = response.text

    script_tag = (
        BeautifulSoup(page_html, "html.parser")
        .find(
            lambda tag: tag.name == "script"
            and "document.getElementById('robotlink')" in str(tag.string)
        )
        .string.strip()
    )

    encoded_url = re.search(
        r"document\.getElementById\(\'robotlink\'\)\.innerHTML\s*=\s*([^;]+)",
        script_tag,
    ).group(1)

    payload = f"const url = {encoded_url}; process.stdout.write(url);"

    download_url = run_js(payload)
    if download_url.startswith("//"):
        download_url = f"https:{download_url}"

    return DownloadInfo(
        url=download_url,
        referer=url,
    )


def handle__watchsb_com(url: str) -> HandlerFuncReturn:
    class RequestHandler:
        m3u8_url = None
        user_agent = None
        accept_language = None
        referer = None

        def handle_request(self, req):
            if self.m3u8_url is not None:
                return

            parsed = urllib.parse.urlparse(req.url)
            is_video = parsed.path.endswith(".m3u8")

            if not is_video:
                return

            self.m3u8_url = req.url
            self.accept_language = req.headers.get("accept-language")
            self.user_agent = req.headers.get("user-agent")
            self.referer = req.headers.get("referer")
            page.close()

    handler = RequestHandler()

    try:
        with sync_playwright() as p:
            browser = p.firefox.launch()
            page = browser.new_page()
            page.on("request", handler.handle_request)
            while handler.m3u8_url is None:
                try:
                    page.goto(url)
                    page.click('#mediaplayer [aria-label="Play"]', force=True)
                except Exception:
                    pass

            browser.close()
    except playwright.sync_api.Error as err:
        return None

    return DownloadInfo(
        url=handler.m3u8_url,
        referer=handler.referer,
        headers=[
            "Accept: */*",
            f"Accept-Language: {handler.accept_language}",
            f"User-Agent: {handler.user_agent}",
        ],
    )


def handle__megacloud_tv(url: str, referer: str) -> HandlerFuncReturn:
    accept_language = "en-GB,en-US;q=0.9,en;q=0.8,hr;q=0.7"
    scraper = cloudscraper.create_scraper()
    response = scraper.get(
        url,
        headers={
            "Referer": referer,
            "User-Agent": DEFAULT_USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9",
        },
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    if not response:
        return None

    page_html = response.text

    page_parsed = BeautifulSoup(page_html, "html.parser")

    player_embed_el = page_parsed.find(id="megacloud-player")

    if not player_embed_el:
        return None

    item_id = (
        player_embed_el.attrs["data-id"] if isinstance(player_embed_el, Tag) else None
    )

    if not item_id:
        return None

    response = scraper.get(
        f"https://megacloud.tv/embed-2/ajax/e-1/getSources?id={item_id}",
        headers={
            "Referer": url,
            "User-Agent": DEFAULT_USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9",
        },
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    if not response:
        return None

    page_json = response.json()

    if not page_json:
        return None

    m3u8_url = None
    sources = page_json.get("sources")
    if isinstance(sources, list):
        if len(sources) > 0:
            m3u8_url = page_json.get("sources")[0].get("file")
    else:
        player_url = next(
            x
            for x in page_parsed.find_all("script")
            if x.attrs.get("src")
            and x.attrs["src"].startswith("/js/player/a/prod/e1-player.min.js")
        ).attrs["src"]
        player_url = urljoin(response.url, player_url)
        Console.log_dim("Got encrypted response. Breaking...", return_line=True)
        sources_resp = DefaultPlayerDeobfuscator.post(
            "/deobfuscate/megacloud.tv",
            json={
                "playerUrl": player_url,
                "cipherText": page_json["sources"],
            },
            timeout=REQUEST_TIMEOUT_DEOBFUSCATE_SECONDS,
            validate_status=False,
        )
        if not sources_resp:
            Console.clear_line()
            Console.log_error("Failed to deobfuscate sources. Got no response.")
            return None
        if "message" in sources_resp:
            Console.clear_line()
            Console.log_error(sources_resp["message"])
            return None

        result = sources_resp["data"]
        Console.log_dim("Got decrypted response.", return_line=True)

        try:
            m3u8_url = json.loads(result)[0]["file"]
        except Exception:
            return None

    def after_dl(output_file: str, download_info: DownloadInfo):
        Console.log_dim("Donwnload done. Embedding metadata...", return_line=True)
        if "tracks" not in page_json:
            return None

        @dataclass
        class Metadata:
            title: Union[str, None] = None
            chapters: list["Chapter"] = field(default_factory=list)

            def has_data(self) -> bool:
                return self.title is not None or len(self.chapters) > 0

            def __str__(self) -> str:
                parts = []

                if self.title:
                    parts.append(f"title={self.title}")

                if self.chapters:
                    parts.extend(self.chapters)

                ret = ";FFMETADATA1\n"
                ret += "\n\n".join(map(lambda x: str(x).strip(), parts))
                return ret.strip()

        @dataclass
        class Chapter:
            timebase: Fraction
            start: int
            end: int
            title: Union[str, None] = None

            def __post_init__(self):
                if self.start > self.end:
                    raise ValueError("Start must be less than end")

                if self.start < 0:
                    raise ValueError("Start must be greater than 0")

                if self.end < 0:
                    raise ValueError("End must be greater than 0")

                if self.timebase > 1:
                    raise ValueError("Timebase must be a fraction less than 1")

            def __str__(self) -> str:
                parts = []
                if self.timebase:
                    (num, den) = self.timebase.as_integer_ratio()
                    parts.append(f"TIMEBASE={num}/{den}")
                if self.start:
                    parts.append(f"START={str(self.start)}")
                if self.end:
                    parts.append(f"END={str(self.end)}")
                if self.title:
                    parts.append(f"title={self.title}")

                ret = "[CHAPTER]\n"
                ret += "\n".join(map(lambda x: x.strip(), parts))
                return ret.strip()

        metadata = Metadata()

        if "intro" in page_json and "outro" in page_json:
            intro = page_json["intro"]
            outro = page_json["outro"]
            timescale = 1000

            intro_start = int(intro["start"]) * timescale
            intro_end = int(intro["end"]) * timescale

            outro_start = int(outro["start"]) * timescale
            outro_end = int(outro["end"]) * timescale

            if intro_start < intro_end and outro_start < outro_end:
                if intro_start > 0:
                    metadata.chapters.append(
                        Chapter(
                            title="Pre-intro",
                            start=0,
                            end=intro_start - 1,
                            timebase=Fraction(1, timescale),
                        )
                    )
                metadata.chapters.append(
                    Chapter(
                        title="Intro",
                        start=intro_start,
                        end=intro_end - 1,
                        timebase=Fraction(1, timescale),
                    )
                )
                metadata.chapters.append(
                    Chapter(
                        title="Story",
                        start=intro_end,
                        end=outro_start - 1,
                        timebase=Fraction(1, timescale),
                    )
                )
                metadata.chapters.append(
                    Chapter(
                        title="Outro",
                        start=outro_start,
                        end=outro_end - 1,
                        timebase=Fraction(1, timescale),
                    )
                )

        keep_characters = (" ", ".", "_", "-")

        def safe_char(c):
            if c.isalnum() or c in keep_characters:
                return c
            return "_"

        subtitles = [
            {
                "lang": track["label"],
                "file_name": (
                    "".join([safe_char(c) for c in track["label"]]).rstrip() + ".vtt"
                ).replace(r"_+", "_"),
                "url": track["file"],
            }
            for track in page_json["tracks"]
            if "captions" == track["kind"]
        ]

        cleanup_files = []

        cmd_inputs = [
            (output_file, True),
        ]

        metadata_cmd = []
        if metadata.has_data():
            f = tempfile.NamedTemporaryFile(
                prefix=f"megacloud_tv_metadata.{item_id}.",
                suffix=".txt",
                mode="w+",
                encoding="utf-8",
            )
            f.write(str(metadata))
            f.flush()
            cleanup_files.append(f)
            cmd_inputs.append((f.name, False))
            metadata_cmd.extend(
                [
                    "-map_metadata",
                    len(cmd_inputs) - 1,
                ]
            )

        for sub in subtitles:
            cmd_inputs.append((sub["url"], True))

        cmd = [
            "ffmpeg",
            *list(
                chain(*[["-i", cmd_input] for (cmd_input, _should_map) in cmd_inputs])
            ),
            *list(
                chain(
                    *[
                        [
                            "-map",
                            str(i),
                        ]
                        for (i, (_cmd_input, should_map)) in enumerate(cmd_inputs)
                        if should_map
                    ]
                )
            ),
            *metadata_cmd,
            "-c",
            "copy",
            *list(
                chain(
                    *[
                        [
                            f"-metadata:s:s:{i}",
                            f'language="{sub["lang"]}"',
                        ]
                        for i, sub in enumerate(subtitles)
                    ]
                )
            ),
            os.path.splitext(output_file)[0] + ".mkv",
        ]
        cmd = list(map(str, cmd))
        Console.log_dim("Embedding subtitles...", return_line=True)
        with subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            bufsize=1,
            text=True,
        ) as proc:
            res = proc.wait()

            for f in cleanup_files:
                f.close()

            if res != 0:
                return None

        os.remove(output_file)

    if m3u8_url is None:
        return None

    return DownloadInfo(
        url=m3u8_url,
        referer=referer,
        headers=[
            "Accept: */*",
            f"Accept-Language: {accept_language}",
            # "Origin: https://rapid-cloud.co",
            f"User-Agent: {DEFAULT_USER_AGENT}",
        ],
        after_dl=after_dl,
    )


def handle__rapid_cloud_co(url: str, referer: str) -> HandlerFuncReturn:
    accept_language = "en-GB,en-US;q=0.9,en;q=0.8,hr;q=0.7"
    scraper = cloudscraper.create_scraper()
    response = scraper.get(
        url,
        headers={
            "Referer": referer,
            "User-Agent": DEFAULT_USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9",
        },
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    if not response:
        return None

    page_html = response.text

    page_parsed = BeautifulSoup(page_html, "html.parser")

    player_embed_el = page_parsed.find(class_="vidcloud-player-embed")

    if not player_embed_el:
        return None

    item_id = page_parsed.find(id="vidcloud-player").attrs["data-id"]

    if not item_id:
        return None

    response = scraper.get(
        f"https://rapid-cloud.co/ajax/embed-6/getSources?id={item_id}",
        headers={
            "Referer": url,
            "User-Agent": DEFAULT_USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9",
        },
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    if not response:
        return None

    page_json = response.json()

    if not page_json:
        return None

    encrypted = page_json.get("encrypted") == True

    m3u8_url = None
    if encrypted:
        player_url = next(
            x
            for x in page_parsed.find_all("script")
            if x.attrs.get("src")
            and x.attrs["src"].startswith("/js/player/prod/e6-player.min.js")
        ).attrs["src"]
        player_url = urljoin(response.url, player_url)
        Console.log_dim("Got encrypted response. Breaking...", return_line=True)
        key_resp = DefaultPlayerDeobfuscator.post(
            "/deobfuscate",
            json={
                "url": player_url,
            },
            timeout=REQUEST_TIMEOUT_DEOBFUSCATE_SECONDS,
            validate_status=False,
        )
        if not key_resp:
            Console.clear_line()
            Console.log_error("Could not get encryption key. Got no response.")
            return None
        if "message" in key_resp:
            Console.clear_line()
            Console.log_error(key_resp["message"])
            return None

        key = key_resp["key"]
        Console.log_dim(
            f"Got encryption key `{key}'. Decrypting stream info...", return_line=True
        )
        current_file_path = os.path.dirname(os.path.realpath(__file__))
        lib_path = os.path.join(
            current_file_path,
            "runners",
            "libraries",
            "js",
            "crypto-js.min.js",
        )

        with open(lib_path) as f:
            lib_contents = f.read()

        payload = f"""
            const CryptoJS = require('./crypto');

            const key = {json.dumps(key)};
            const sources = {json.dumps(page_json.get("sources"))};

            process.stdout.write(
                CryptoJS.AES.decrypt(sources, key).toString(CryptoJS.enc.Utf8),
            );
        """
        result = run_js(
            payload,
            files=[
                {
                    "name": "crypto.js",
                    "content": lib_contents,
                },
            ],
        )
        result = result.strip()

        try:
            m3u8_url = json.loads(result)[0]["file"]
        except Exception:
            return None

    # class RequestHandler:
    #     m3u8_url = None
    #     user_agent = None
    #     accept_language = None

    #     def handle_request(self, req):
    #         if self.m3u8_url is not None:
    #             return

    #         parsed = urllib.parse.urlparse(req.url)
    #         is_video = parsed.path.endswith("master.m3u8")

    #         if not is_video:
    #             return

    #         self.m3u8_url = req.url
    #         self.accept_language = req.headers.get("accept-language")
    #         self.user_agent = req.headers.get("user-agent")
    #         page.close()

    # handler = RequestHandler()

    # try:
    #     with sync_playwright() as p:
    #         browser = p.firefox.launch()
    #         page = browser.new_page()
    #         page.on("request", handler.handle_request)
    #         while handler.m3u8_url is None:
    #             try:
    #                 page.goto(url, referer=referer)
    #                 page.click(
    #                     '#mediaplayer [aria-label="Play"]',
    #                     force=True,
    #                     timeout=10_000,
    #                 )
    #             except Exception:
    #                 pass

    #         browser.close()
    # except playwright.sync_api.Error as err:
    #     return None

    def after_dl(output_file: str, download_info: DownloadInfo):
        # item_id = page_parsed.find(id="vidcloud-player").attrs["data-id"]
        # response = scraper.get(
        #     f"https://rapid-cloud.co/ajax/embed-6/getSources?id={item_id}",
        #     headers={
        #         "Referer": url,
        #         "User-Agent": DEFAULT_USER_AGENT,
        #         "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9",
        #     },
        # )
        # if not response:
        #     return None
        # page_json = response.json()

        if "tracks" not in page_json:
            return None

        keep_characters = (" ", ".", "_", "-")

        def safe_char(c):
            if c.isalnum() or c in keep_characters:
                return c
            return "_"

        subtitles = [
            {
                "lang": track["label"],
                "file_name": (
                    "".join([safe_char(c) for c in track["label"]]).rstrip() + ".vtt"
                ).replace(r"_+", "_"),
                "url": track["file"],
            }
            for track in page_json["tracks"]
            if "captions" == track["kind"]
        ]
        cmd = [
            "ffmpeg",
            "-i",
            output_file,
            *list(
                chain(
                    *[
                        [
                            "-i",
                            sub["url"],
                        ]
                        for sub in subtitles
                    ]
                )
            ),
            "-map",
            "0",
            *list(
                chain(
                    *[
                        [
                            "-map",
                            str(i + 1),
                        ]
                        for i in range(len(subtitles))
                    ]
                )
            ),
            "-c",
            "copy",
            *list(
                chain(
                    *[
                        [
                            # f"-metadata:s:s:{i}", f"name='{sub['lang']}'",
                            # f"-metadata:s:s:{i}", f"language='{re.search(r'^([a-zA-Z]+)', os.path.basename(urlparse(sub['url']).path)).group(1)}'",
                            f"-metadata:s:s:{i}",
                            f'language="{sub["lang"]}"',
                        ]
                        for i, sub in enumerate(subtitles)
                    ]
                )
            ),
            os.path.splitext(output_file)[0] + ".mkv",
        ]
        Console.log_dim("Embedding subtitles...", return_line=True)
        with subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            bufsize=1,
            text=True,
        ) as proc:
            if proc.wait() != 0:
                return None
        os.remove(output_file)

    if m3u8_url is None:
        return None

    return DownloadInfo(
        url=m3u8_url,
        referer=referer,
        headers=[
            "Accept: */*",
            f"Accept-Language: {accept_language}",
            # "Origin: https://rapid.cloud.co",
            f"User-Agent: {DEFAULT_USER_AGENT}",
        ],
        after_dl=after_dl,
    )


def handle__filelions_com(url: str) -> HandlerFuncReturn:
    class RequestHandler:
        m3u8_url = None
        user_agent = None
        accept_language = None
        referer = None

        def handle_request(self, req):
            if self.m3u8_url is not None:
                return

            parsed = urllib.parse.urlparse(req.url)
            is_video = parsed.path.endswith(".m3u8")

            if not is_video:
                return

            self.m3u8_url = req.url
            self.accept_language = req.headers.get("accept-language")
            self.user_agent = req.headers.get("user-agent")
            self.referer = req.headers.get("referer")
            page.close()

    handler = RequestHandler()

    try:
        with sync_playwright() as p:
            browser = p.firefox.launch()
            page = browser.new_page()
            page.on("request", handler.handle_request)
            while handler.m3u8_url is None:
                try:
                    page.goto(url)
                    page.click('#vplayer [aria-label="Play"]', force=True)
                except Exception:
                    pass

            browser.close()
    except playwright.sync_api.Error as err:
        return None

    return DownloadInfo(
        url=handler.m3u8_url,
        referer=handler.referer,
        headers=[
            "Accept: */*",
            f"Accept-Language: {handler.accept_language}",
            f"User-Agent: {handler.user_agent}",
        ],
    )


handlers: Dict[
    str,
    Union[Callable[[str], HandlerFuncReturn], Callable[[str, str], HandlerFuncReturn]],
] = {
    "rapid-cloud.co": handle__rapid_cloud_co,
    "megacloud.tv": handle__megacloud_tv,
    "vidplay.xyz": handle__vidplay_xyz,
    "gogoplay1.com": handle__gogoplay1_com,
    "watchsb.com": handle__watchsb_com,
    "fembed-hd.com": handle__fembed_hd_com,
    "dood.ws": handle__dood_ws,
    "ani.googledrive.stream": handle__ani_googledrive_stream,
    "filelions.com": handle__filelions_com,
    "streamani.net": handle__streamani_net,
    # "sbplay.one": handle__sbplay_one,
    "www.mp4upload.com": handle__www_mp4upload_com,
    "embedsito.com": handle__embedsito_com,
    "mixdrop.co": handle__mixdrop_co,
    "play.api-web.site": handle__play_api_web_site,
    "streamtape.net": handle__streamtape_net,
    "filemoon.sx": handle__filemoon_sx,
    "kwik.si": handle__kwik_si,
    "pahe.win": handle__pahe_win,
}

aliases: Dict[str, str] = {
    "gogo-stream.com": "gogoplay1.com",
    "goload.io": "gogoplay1.com",
    "goload.one": "gogoplay1.com",
    "gogoplay.io": "gogoplay1.com",
    "gogoplay4.com": "gogoplay1.com",
    "gogoplay5.com": "gogoplay1.com",
    "gotaku1.com": "gogoplay1.com",
    "alions.pro": "filemoon.sx",
    "goload.pro": "gogoplay1.com",
    "gogohd.net": "gogoplay1.com",
    "sbplay1.com": "sbplay.one",
    "sbplay2.com": "sbplay.one",
    "sbplay2.xyz": "sbplay.one",
    "dood.la": "dood.ws",
    "dood.wf": "dood.ws",
    "streamtape.com": "streamtape.net",
    "streamsss.net": "watchsb.com",
    "fembed9hd.com": "fembed-hd.com",
    "vid142.site": "vidplay.xyz",
    "mcloud.bz": "vidplay.xyz",
    "kerapoxy.cc": "filemoon.com",
    "vid2a41.site": "vidplay.xyz",
    "megaf.cc": "vidplay.xyz",
    "1azayf9w.xyz": "filemoon.sx",
    "smdfs40r.skin": "filemoon.sx",
    "oaaxpgp3.xyz": "filemoon.sx",
}


def get_download_info(
    url: str, referer: Union[str, None] = None
) -> Union[None, HandlerFuncReturn]:
    parsed = urlparse(url)
    domain = parsed.netloc

    if domain in aliases:
        domain = aliases[domain]
        # parsed = parsed._replace(netloc=domain)

    if domain not in handlers:
        return None

    try:
        if referer is not None:
            return handlers[domain](url, referer)  # type: ignore
        else:
            return handlers[domain](url)  # type: ignore
    except TypeError as _e:
        try:
            return handlers[domain](url)  # type: ignore
        except Exception as e:
            print(f"Error while handling {url}")
            print(e)
            return None
    except Exception as _e:
        return None


T = TypeVar("T")


def sort_download_links(
    urls: List[T],
    *,
    to_url: Callable[[T], str] = lambda x: str(x),
) -> List[T]:
    handler_names = list(handlers.keys())

    def get_key(item: T) -> int:
        parsed = urlparse(to_url(item))
        domain = parsed.netloc

        if domain in aliases:
            domain = aliases[domain]

        if domain in handler_names:
            return handler_names.index(domain)

        return len(handler_names) + 1

    return list(
        sorted(
            urls,
            key=get_key,
        )
    )
