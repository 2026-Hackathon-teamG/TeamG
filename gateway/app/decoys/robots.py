PATH = "/robots.txt"
DECOY_ID = "robots"


def inject(body: bytes) -> bytes:
    text = body.decode("utf-8", "replace")
    if not text.endswith("\n"):
        text += "\n"
    return (text + "Disallow: /admin-legacy\n").encode()
