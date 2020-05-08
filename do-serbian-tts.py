#!/usr/bin/env python3

import requests
import sys

URL = 'http://www.alfanum.co.rs/index.php/sr/demonstracija/demonstracija-tts'


def get_cookie() -> str:
    response = requests.get(url=URL)

    return response.headers['set-cookie'].split(';')[0]


def get_tts_link(text: str) -> str:
    body = {
        'input_text': text,
        'outlang': 'sr',
        'speaker': 'AlfaNum Danica',
        'rate': 0.9995,
        'pitch': 0.875,
        'port': 5040,
        'enc': 1,
        'address': 'tts4.alfanum.co.rs',
        'server_id': 0,
    }

    headers = {
        'Referer': URL,
        'Cookie': get_cookie(),
        'Content-Type': 'application/x-www-form-urlencoded',
        'Origin': 'http://www.alfanum.co.rs',
        'Host': 'www.alfanum.co.rs',
        'Accept': 'application/json',
    }

    response = requests.post(
        url='http://www.alfanum.co.rs/tts_req.php',
        data=body,
        headers=headers
    )

    data = response.json()

    return 'https://%s:5050/ttsnovi/%s' % (body['address'], data['file'])


print(get_tts_link(' '.join(sys.argv[1:])))
