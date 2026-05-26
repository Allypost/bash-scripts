#!/usr/bin/env python3

from collections import OrderedDict
import subprocess
import json
from typing import Iterator


def main():
    sinks = [
        s
        for s in pactl("list", "sinks")
        if any((p.get("availability") != "not available" for p in s.get("ports", [])))
    ]
    current_sink_name = pactl("info")["default_sink_name"]
    print(f"Current sink name: {current_sink_name}")
    current_sink = next(x for x in sinks if x.get("name") == current_sink_name)
    print(f"Current sink: {current_sink}")
    if not current_sink:
        raise ValueError("Could not find defaut sink in sinks")
    default_sink_index = sinks.index(current_sink)
    # move default sink to the end of the list
    sinks.append(sinks.pop(default_sink_index))
    sink_desc_to_sink = OrderedDict(
        (desc(sink, sink == current_sink), sink) for sink in sinks
    )
    next_sink_desc = select_one(map(str, sink_desc_to_sink.keys()))
    if not next_sink_desc:
        print("Cancelled selection")
        return
    next_sink = sink_desc_to_sink[next_sink_desc]
    if next_sink == current_sink:
        print("Already selected")
        return
    sink_inputs = pactl("list", "sink-inputs")
    for sink_input in sink_inputs:
        print(f"Moving {sink_input['index']} to {next_sink['name']}")
        pactl("move-sink-input", sink_input["index"], next_sink["index"])
    pactl("set-default-sink", next_sink["index"])


def pactl(*args: str):
    """
    Run pactl with the given arguments.
    Sets the format to json so output is some parsed json.
    """
    cmd = ["pactl", "-f", "json"] + list(args)
    cmd = list(map(str, cmd))
    res = subprocess.run(cmd, check=True, text=True, capture_output=True)
    if res.stdout:
        return json.loads(res.stdout)
    else:
        return None


def desc(sink: dict, current=False):
    return f"{sink['description']} ({sink['index']}){' [current]' if current else ''}"


def select_one(items: Iterator[str]):
    cmd = [
        "vicinae",
        "dmenu",
        "--no-section",
        "--no-footer",
        "--no-quick-look",
        "--no-metadata",
        "--placeholder",
        "Select audio output",
    ]
    p = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    stdout = p.communicate(input="\n".join(items))[0]
    p.terminate()
    return stdout.strip()


if __name__ == "__main__":
    main()
