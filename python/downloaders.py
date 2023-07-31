import json
import os
import re
import subprocess
import urllib.parse
from dataclasses import dataclass, field
from itertools import chain
from typing import Callable, Dict, List, TypeVar, Union
from urllib.parse import urljoin, urlparse

import cloudscraper
import requests
from bs4 import BeautifulSoup

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
        headers = {
            "Cookie": session_cookie(),
            "User-Agent": "Instagram post download script (personal use only I swar)",
        }

        return requests.get(api_url, headers=headers)

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
            headers={"User-Agent": "Gogo stream video downloader"},
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
            headers={"User-Agent": "Gogo stream video downloader"},
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
        .get(url, headers={"User-Agent": "Gogo stream video downloader"})
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
        )
        .json()["data"]
    )

    return DownloadInfo(
        url=sorted(
            resp,
            key=lambda k: int(k["label"][:-1]),
            reverse=True,
        )[
            0
        ]["file"],
        referer=url,
    )


def handle__www_mp4upload_com(url: str) -> HandlerFuncReturn:
    page_html = cloudscraper.create_scraper().get(url).text
    packed_script = (
        BeautifulSoup(page_html, "html.parser")
        .find(
            lambda tag: tag.name == "script"
            and "function(p,a,c,k,e,d)" in str(tag.string)
        )
        .string
    )

    payload = f"""
    const fn = {packed_script[4:]}
    console.log(fn.toString());
    """
    r = run_js(payload)

    # Better: video_url = re.match(r'player\.src\("([^"]+)"\)', r)
    video_url = next(x for x in r.split("player.") if x.startswith('src("')).strip()[
        5:-3
    ]

    return DownloadInfo(url=video_url, referer=url)


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
        response = cloudscraper.create_scraper().get(url)
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
                "User-Agent": "Gogo stream video downloader",
                "Referer": url,
                "x-requested-with": "XMLHttpRequest",
            },
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
    response = cloudscraper.create_scraper().get(url)
    if not response:
        return None
    page_html = response.text

    something_url = re.search(r"\$.get\('/pass_md5/([^']+)", page_html, re.IGNORECASE)
    if not something_url:
        return None
    something_url = f"https://dood.ws/pass_md5/{something_url.group(1)}"

    response = cloudscraper.create_scraper().get(
        something_url,
        headers={
            "User-Agent": "Gogo stream video downloader",
            "Referer": url,
        },
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
            "User-Agent": "Gogo stream video downloader",
            "Referer": url,
            "x-requested-with": "XMLHttpRequest",
        },
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
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/102.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9",
            "Referer": url,
        },
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
    user_agent = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/107.0.0.0 Safari/537.36"
    accept_language = "en-GB,en-US;q=0.9,en;q=0.8,hr;q=0.7"
    scraper = cloudscraper.create_scraper()
    response = scraper.get(
        url,
        headers={
            "Referer": referer,
            "User-Agent": user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9",
        },
    )
    if not response:
        return None

    page_html = response.text

    page_parsed = BeautifulSoup(page_html, "html.parser")

    player_embed_el = page_parsed.find(id="megacloud-player")

    if not player_embed_el:
        return None

    item_id = player_embed_el.attrs["data-id"]

    if not item_id:
        return None

    response = scraper.get(
        f"https://megacloud.tv/embed-2/ajax/e-1/getSources?id={item_id}",
        headers={
            "Referer": url,
            "User-Agent": user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9",
        },
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
            and x.attrs["src"].startswith("/js/player/a/prod/e1-player.min.js")
        ).attrs["src"]
        player_url = urljoin(response.url, player_url)
        Console.log_dim("Got encrypted response. Breaking...", return_line=True)
        sources_resp = scraper.post(
            "https://player-deobfuscator.fxk.ch/deobfuscate/megacloud.tv",
            json={
                "playerUrl": player_url,
                "cipherText": page_json["sources"],
            },
        ).json()
        if "message" in sources_resp:
            Console.clear_line()
            Console.log_error(sources_resp["message"])
            return None

        result = sources_resp["data"]
        Console.log_dim(f"Got decrypted response.", return_line=True)

        try:
            m3u8_url = json.loads(result)[0]["file"]
        except Exception:
            return None

    def after_dl(output_file: str, download_info: DownloadInfo):
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
                            f"-metadata:s:s:{i}",
                            f"language=\"{sub['lang']}\"",
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
            "Origin: https://rapid.cloud.co",
            f"User-Agent: {user_agent}",
        ],
        after_dl=after_dl,
    )


def handle__rapid_cloud_co(url: str, referer: str) -> HandlerFuncReturn:
    user_agent = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/107.0.0.0 Safari/537.36"
    accept_language = "en-GB,en-US;q=0.9,en;q=0.8,hr;q=0.7"
    scraper = cloudscraper.create_scraper()
    response = scraper.get(
        url,
        headers={
            "Referer": referer,
            "User-Agent": user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9",
        },
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
            "User-Agent": user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9",
        },
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
        key_resp = scraper.post(
            "https://deobfuscator.oracle-arm-1.ji0.li/deobfuscate",
            json={
                "url": player_url,
            },
        ).json()
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
            const sources = {json.dumps(page_json.get('sources'))};

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
        #         "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/107.0.0.0 Safari/537.36",
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
                            f"language=\"{sub['lang']}\"",
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
            "Origin: https://rapid.cloud.co",
            f"User-Agent: {user_agent}",
        ],
        after_dl=after_dl,
    )


handlers: Dict[str, Callable[[str], HandlerFuncReturn]] = {
    "rapid-cloud.co": handle__rapid_cloud_co,
    "megacloud.tv": handle__megacloud_tv,
    "gogoplay1.com": handle__gogoplay1_com,
    "watchsb.com": handle__watchsb_com,
    "fembed-hd.com": handle__fembed_hd_com,
    "dood.ws": handle__dood_ws,
    "ani.googledrive.stream": handle__ani_googledrive_stream,
    "streamani.net": handle__streamani_net,
    # "sbplay.one": handle__sbplay_one,
    "www.mp4upload.com": handle__www_mp4upload_com,
    "embedsito.com": handle__embedsito_com,
    "mixdrop.co": handle__mixdrop_co,
    "play.api-web.site": handle__play_api_web_site,
    "streamtape.net": handle__streamtape_net,
}

aliases: Dict[str, str] = {
    "gogo-stream.com": "gogoplay1.com",
    "goload.io": "gogoplay1.com",
    "goload.one": "gogoplay1.com",
    "gogoplay.io": "gogoplay1.com",
    "gogoplay4.com": "gogoplay1.com",
    "gogoplay5.com": "gogoplay1.com",
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
}


def get_download_info(
    url: str, referer: Union[str, None] = None
) -> Union[None, HandlerFuncReturn]:
    parsed = urlparse(url)
    domain = parsed.netloc

    if domain in aliases:
        domain = aliases[domain]
        parsed = parsed._replace(netloc=domain)

    if domain not in handlers:
        return None

    try:
        if referer is not None:
            return handlers[domain](url, referer)
        else:
            return handlers[domain](url)
    except TypeError as e:
        return handlers[domain](url)
    except Exception as e:
        return None


T = TypeVar("T")


def sort_download_links(
    urls: List[T],
    *,
    to_url: Callable[[T], str] = lambda x: x,
) -> List[str]:
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
