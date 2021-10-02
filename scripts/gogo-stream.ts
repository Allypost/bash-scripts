#!/usr/bin/env -S deno run --quiet --allow-all --unstable

import {
  $,
  $a,
} from 'https://deno.land/x/deno_dx@0.2.0/mod.ts';
import {
  DOMParser,
  NodeList,
} from "https://deno.land/x/deno_dom@v0.1.13-alpha/deno-dom-wasm.ts";

const runJs =
  async (payload: string): Promise<{
    language: string;
    version: string;
    run: {
      stdout: string;
      stderr: string;
      output: string;
      code: number;
      signal: unknown;
    }
  }> => {
    const runtimes: {
      language: string;
      version: string;
      aliases: string[];
      runtime?: string;
    }[] = await fetch('https://emkc.org/api/v2/piston/runtimes').then((res) => res.json());

    const runtime = runtimes.find(({ runtime }) => "node" === runtime);

    return await fetch(
      'https://emkc.org/api/v2/piston/execute',
      {
        method: "POST",
        body: JSON.stringify({
          "language": 'js',
          version: runtime?.version,
          "files": [
            {
              "content": payload,
            }
          ],
        }),
      },
    ).then((res) => res.json());
  }
  ;

const handlers: Record<string, (url: string) => Promise<{ url: string; referer?: string }>> = {
  async 'streamani.net'(url) {
    const sources = await $`
        curl -sL '${url}' |
          pup --color 'script:contains("https://")' |
          grep 'sources:' |
          sed -E 's/^[[:space:]]+sources\://g'
      `;

    const payload = `const s = [${sources.replaceAll('\n', ',')}].flat(); process.stdout.write(s[0].file);`;

    const result = await runJs(payload);
    return {
      url: result.run.stdout,
    }
  },

  async 'sbplay.one'(url) {
    const code =
      url
        .replace('.html', '')
        .split('/')
        .pop()
        ?.split('-')
        .pop()
      || ''
      ;
    const pageData = await fetch(`https://sbplay.one/play/${code}?auto=1`).then((res) => res.text());

    const doc = new DOMParser().parseFromString(pageData, "text/html");
    const scriptTags = Array.from(doc?.querySelectorAll("body script") || [] as unknown as NodeList);

    const jwPlayerKey =
      scriptTags
        .find((node) => node.textContent.includes('jwplayer.key='))
        ?.textContent
      ;

    const jwPlayer =
      scriptTags
        .find((node) => node.textContent.includes('eval(function(p,a,c,k,e,d)'))
        ?.textContent
      ;

    const payload = `
      let result = '';
      const jwplayer = () => ({
        addButton: () => null,
        setup: ({ sources }) => {
          result = sources[0].file;
        },
        on: () => null,
      });
      ${jwPlayerKey};
      ${jwPlayer};
      process.stdout.write(result);
    `

    const result = await runJs(payload);

    return {
      url: result.run.stdout,
    }
  },

  async 'mixdrop.co'(url) {
    const scriptData = (await $`
        curl -sL '${url}' |
          pup --color 'script:contains("MDCore.ref") text{}'
      `).trim();

    if (!scriptData) {
      throw new Error("Can't extract script data");
    }

    const payload = `const MDCore = {}; ${scriptData}; process.stdout.write(\`https:\${MDCore.wurl}\`);`;

    const result = await runJs(payload);

    return {
      url: result.run.stdout.trim(),
    }
  },

  async 'embedsito.com'(url) {
    const id = url.split('/').pop() || "";
    const {
      data,
    }: {
      data: {
        label: string;
        file: string;
      }[];
    } = await fetch(
      `https://embedsito.com/api/source/${id}`,
      {
        "headers": {
          "accept": "*/*",
          "accept-language": "en-GB,en;q=0.9,hr;q=0.8,de;q=0.7",
          "content-type": "application/x-www-form-urlencoded; charset=UTF-8",
          "sec-ch-ua": "\"Google Chrome\";v=\"93\", \" Not;A Brand\";v=\"99\", \"Chromium\";v=\"93\"",
          "sec-ch-ua-mobile": "?0",
          "sec-ch-ua-platform": "\"Linux\"",
          "sec-fetch-dest": "empty",
          "sec-fetch-mode": "cors",
          "sec-fetch-site": "same-origin",
          "x-requested-with": "XMLHttpRequest"
        },
        "referrer": `https://embedsito.com/v/${id}`,
        "referrerPolicy": "strict-origin-when-cross-origin",
        "body": "r=&d=embedsito.com",
        "method": "POST",
        "mode": "cors",
        "credentials": "omit"
      },
    ).then((res) => res.json());

    const file = data.sort((sm, bg) => parseInt(sm.label) - parseInt(bg.label)).pop()?.file;

    return {
      url: file || '',
    }
  },

  async 'www.mp4upload.com'(url) {
    const scriptData = (await $`
        curl -sL '${url}' |
          pup 'script[type="text/javascript"]:contains("eval(function(p,a,c,k,e,d)") text{}' |
          sed -e 's/^[[:space:]]*//' |
          cut -c 5-
      `).trim();

    if (!scriptData) {
      throw new Error("Can't extract script data");
    }

    throw new Error('Not implemented');
    return {
      url: ''
    };
  },
};

export const getDownloadLink =
  async (gogoStreamUrl: string) => {
    const siteUrlList = $a`curl -sL ${gogoStreamUrl} | pup '[data-video] attr{data-video}'`;
    const siteUrlMap = new Map();
    for await (const siteUrl of siteUrlList) {
      const {
        hostname,
      } = new URL(siteUrl);

      siteUrlMap.set(hostname, decodeURIComponent(siteUrl).replaceAll('&amp;', '&'));
    }

    for (const [key, handler] of Object.entries(handlers)) {
      if (!siteUrlMap.has(key)) {
        continue
      }

      try {
        const { url } = await handler(siteUrlMap.get(key));

        return url;
      } catch {
        continue;
      }
    }

    return null;
  }
  ;