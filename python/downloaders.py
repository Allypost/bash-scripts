import json
import os
import re
from typing import Callable, Dict, List, TypeVar, Union
from bs4 import BeautifulSoup
import urllib.parse
from urllib.parse import urlparse
from dataclasses import dataclass
import cloudscraper
import os

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

    download_url = run_js(payload)

    if download_url == "https:undefined":
        return None

    return DownloadInfo(url=download_url, referer=url)


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

        page = BeautifulSoup(page_html, 'html.parser')

        attr_script_crypto_a = page.find('body')['class'][0].split('-')[1]
        attr_script_crypto_b = page.find(
            lambda tag:
            tag.name == 'div'
            and 'class' in tag.attrs
            and 'wrapper' in tag.attrs['class']
            and [x for x in tag.attrs['class'] if x.startswith('container-')]
        )['class']
        attr_script_crypto_b = [x for x in attr_script_crypto_b if x.startswith('container-')][0].split('-')[1]
        attr_script_crypto_c = page.find(
            lambda tag:
            tag.name == 'div'
            and 'class' in tag.attrs
            and [x for x in tag.attrs['class'] if x.startswith('videocontent-')]
        )['class']
        attr_script_crypto_c = [x for x in attr_script_crypto_c if x.startswith('videocontent-')][0].split('-')[1]
        attr_script_crypto = page.find(
            'script',
            attrs={"data-name": "episode"}
        ).attrs['data-value']

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
                    int(source['label'][:-2]) if source['label'][:-2].isdigit() else 0,
                    source['file'],
                ]
                for source
                in api_response['source']
                if source['label'][-1] == 'P'
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

    something_url = re.search(
        r"\$.get\('/pass_md5/([^']+)", page_html, re.IGNORECASE)
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
    files = sorted([
        [
            int(x['label'][:-1]),
            x['file'],
        ]
        for x
        in data['data']
    ], key=lambda x: x[0])

    best_file = files[-1][1]

    return DownloadInfo(
        url=best_file,
        referer=url,
    )


def handle__streamtape_net(url: str) -> HandlerFuncReturn:
    response = cloudscraper.create_scraper().get(
        url,
        headers={
            "User-Agent": "StreamTape video downloader",
            "Referer": url,
        },
    )

    if not response:
        return None

    page_html = response.text

    script_tag = BeautifulSoup(page_html, "html.parser").find(
        lambda tag: tag.name == "script" and "document.getElementById('robotlink')" in str(
            tag.string)
    ).string.strip()

    encoded_url = re.search(
        r'document\.getElementById\(\'robotlink\'\)\.innerHTML\s*=\s*([^;]+)',
        script_tag,
    ).group(1)

    payload = f"const url = {encoded_url}; process.stdout.write(url);"

    download_url = run_js(payload)
    if download_url.startswith('//'):
        download_url = f"https:{download_url}"

    return DownloadInfo(
        url=download_url,
        referer=url,
    )


handlers: Dict[str, Callable[[str], HandlerFuncReturn]] = {
    "gogoplay1.com": handle__gogoplay1_com,
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
    "goload.one": "gogoplay1.com",
    "gogoplay.io": "gogoplay1.com",
    "gogoplay4.com": "gogoplay1.com",
    "gogoplay5.com": "gogoplay1.com",
    "goload.pro": "gogoplay1.com",
    "sbplay1.com": "sbplay.one",
    "sbplay2.com": "sbplay.one",
    "sbplay2.xyz": "sbplay.one",
    "dood.la": "dood.ws",
    "streamtape.com": "streamtape.net",
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
