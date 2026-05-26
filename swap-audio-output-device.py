#!/usr/bin/env python3

import subprocess
import json


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
    next_sink = sinks[(default_sink_index + 1) % len(sinks)]
    print(f"Next sink: {next_sink}")
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


if __name__ == "__main__":
    main()
