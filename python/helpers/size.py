def human_byte_size(size_bytes: str | int | float, *, sep=" "):
    """
    format a size in bytes into a 'human' file size, e.g. bytes, KB, MB, GB, TB, PB
    Note that bytes/KB will be reported in whole numbers but MB and above will have greater precision
    e.g. 1 B, 43 B, 443 KB, 4.3 MB, 4.43 GB, etc
    """
    suffixes_table = [
        ("B", 0),
        ("KiB", 0),
        ("MiB", 1),
        ("GiB", 2),
        ("TiB", 2),
        ("PiB", 2),
    ]

    num = float(size_bytes)
    for suffix, precision in suffixes_table:
        if num < 1024.0:
            break
        num /= 1024.0

    formatted_size = str(round(num, ndigits=precision or None))

    return f"{formatted_size}{sep}{suffix}"
