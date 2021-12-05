import os
from typing import Callable, Dict, List, Union
from bs4 import BeautifulSoup
import urllib.parse
from urllib.parse import urlparse
from dataclasses import dataclass
import cloudscraper

from .runners.js import run_js


@dataclass
class DownloadInfo:
    url: str
    referer: Union[str, None] = None


HandlerFuncReturn = Union[None, DownloadInfo]


def handle__streamani_net(url: str) -> HandlerFuncReturn:
    return None


def handle__sbplay_one(url: str) -> HandlerFuncReturn:
    download_page = url.replace("/e/", "/d/")
    page_html = cloudscraper\
        .create_scraper()\
        .get(
            download_page,
            headers={
                "User-Agent": "Gogo stream video downloader"
            },
        )\
        .text

    download_links = BeautifulSoup(page_html, "html.parser")\
        .find(class_="contentbox")\
        .find("table")\
        .find_all("td")

    @dataclass
    class Info:
        id: str
        mode: str
        hash: str

    def fix_pair(pair):
        link_, info_ = pair

        file_id, mode, file_hash = link_\
            .find("a")["onclick"]\
            .replace("download_video", "")[1:-1]\
            .replace("'", "")\
            .split(",")

        w, h = info_\
            .text\
            .strip()\
            .split(',')[0]\
            .split('x')

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
        [
            fix_pair(download_links[i:i+2])
            for i
            in range(0, len(download_links), 2)
        ],
        key=lambda x: x[1],
        reverse=True,
    )[0][0]

    download_generator_url = f"https://sbplay.one/dl?op=download_orig&id={info.id}&mode={info.mode}&hash={info.hash}"

    page_html = cloudscraper\
        .create_scraper()\
        .get(
            download_generator_url,
            headers={
                "User-Agent": "Gogo stream video downloader"
            },
        )\
        .text

    download_link = BeautifulSoup(page_html, "html.parser")\
        .find(class_="contentbox")\
        .find("a")["href"]

    return DownloadInfo(url=download_link, referer=download_generator_url)


def handle__mixdrop_co(url: str) -> HandlerFuncReturn:
    page_html = cloudscraper.create_scraper().get(url, headers={
        "User-Agent": "Gogo stream video downloader"
    }).text

    script_data = BeautifulSoup(page_html, "html.parser").find(
        lambda tag: tag.name == "script" and "MDCore.ref" in str(tag.string)).string.strip()

    payload = f"const MDCore = {{}}; {script_data}; process.stdout.write(`https:${{MDCore.wurl}}`);"

    return DownloadInfo(url=run_js(payload), referer=url)


def handle__embedsito_com(url: str) -> HandlerFuncReturn:
    api_id = url.split("/")[-1]
    resp = cloudscraper.create_scraper().post(
        f"https://embedsito.com/api/source/{api_id}",
        headers={
            "accept": "*/*",
            "accept-language": "en-GB,en;q=0.9,hr;q=0.8,de;q=0.7",
            "content-type": "application/x-www-form-urlencoded; charset=UTF-8",
            "x-requested-with": "XMLHttpRequest",
            "referer": url,
        },
        data="r=&d=embedsito.com"
    ).json()['data']

    return DownloadInfo(
        url=sorted(
            resp,
            key=lambda k: int(k["label"][:-1]),
            reverse=True,
        )[0]["file"],
        referer=url,
    )


def handle__www_mp4upload_com(url: str) -> HandlerFuncReturn:
    page_html = cloudscraper.create_scraper().get(url).text
    packed_script = BeautifulSoup(page_html, 'html.parser').find(
        lambda tag: tag.name == "script" and "function(p,a,c,k,e,d)" in str(tag.string)).string

    payload = f"""
    const fn = {packed_script[4:]}
    console.log(fn.toString());
    """
    r = run_js(payload)

    # Better: video_url = re.match(r'player\.src\("([^"]+)"\)', r)
    video_url = next(x for x in r.split("player.")
                     if x.startswith('src("')).strip()[5:-3]

    return DownloadInfo(url=video_url, referer=url)


def handle__ani_googledrive_stream(url: str) -> HandlerFuncReturn:
    download_url = os.popen(f"youtube-dl --get-url '{url}'").read().strip()

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
    def get_embedded_players(url: str) -> HandlerFuncReturn:
        response = cloudscraper.create_scraper().get(url)
        if not response:
            return None
        page_html = response.text
        soup = BeautifulSoup(page_html, "html.parser")

        urls = [
            tag["data-video"]
            for
            tag
            in soup.find_all(lambda tag: tag.has_attr("data-video"), class_="linkserver")
            if tag["data-video"]
        ]

        for site_url in urls:
            download_info = get_download_info(site_url)
            if download_info is not None:
                return download_info

        return None

    def get_video_urls(url: str) -> HandlerFuncReturn:
        cmd = os.popen(f"""
            curl -sL '{url}' |
            pup 'script:contains("https://")' |
            grep 'sources:' |
            sed -E 's/^[[:space:]]+sources\://g'
        """)
        sources = cmd.read().replace("\n", ",")
        cmd.close()

        payload = f"const s = [{sources}].flat(); process.stdout.write(s[0].file);"
        resp = run_js(payload)
        return DownloadInfo(url=resp, referer=url)

    parsed = urllib.parse.urlparse(url)
    url_path = parsed.path

    if url_path == '/streaming.php':
        return get_embedded_players(url)
    elif url_path == '/embedplus':
        return get_video_urls(url)
    else:
        return None


handlers: Dict[str, Callable[[str], HandlerFuncReturn]] = {
    # dood.la is behind cloudflare
    # streamtape.net ????

    "ani.googledrive.stream": handle__ani_googledrive_stream,
    "streamani.net": handle__streamani_net,
    "sbplay.one": handle__sbplay_one,
    "embedsito.com": handle__embedsito_com,
    "www.mp4upload.com": handle__www_mp4upload_com,
    "mixdrop.co": handle__mixdrop_co,
    "play.api-web.site": handle__play_api_web_site,
    "gogoplay1.com": handle__gogoplay1_com,
}

aliases: Dict[str, str] = {
    "gogo-stream.com": "gogoplay1.com",
    "goload.one": "gogoplay1.com",
    "sbplay1.com": "sbplay.one",
}


def get_download_info(url: str) -> Union[None, HandlerFuncReturn]:
    parsed = urlparse(url)
    domain = parsed.netloc

    if domain in aliases:
        domain = aliases[domain]
        parsed = parsed._replace(netloc=domain)
        url = parsed.geturl()

    if domain not in handlers:
        return None

    try:
        return handlers[domain](url)
    except Exception:
        return None


def sort_download_links(urls: List[str]) -> List[str]:
    handler_names = list(handlers.keys())

    def get_key(url: str) -> int:
        parsed = urlparse(url)
        domain = parsed.netloc

        if domain in aliases:
            domain = aliases[domain]

        if domain in handler_names:
            return handler_names.index(domain)

        return len(handler_names) + 1

    return list(sorted(
        urls,
        key=get_key,
    ))
