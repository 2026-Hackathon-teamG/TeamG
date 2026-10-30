from fastapi.responses import JSONResponse

from shared import tokens

from . import fake

PATH = "/api/internal/export"
DECOY_ID = "endless_export"
PAGE_SIZE = 50


def respond(actor_id: str, page_no: int, secret: str) -> JSONResponse:
    next_token = tokens.sign(actor_id, page_no + 1, secret)
    return JSONResponse({
        "page": page_no,
        "page_size": PAGE_SIZE,
        "has_more": True,   # 끝나지 않음
        "records": fake.page(actor_id, page_no, PAGE_SIZE),
        "next_token": next_token,
        "next": f"{PATH}?token={next_token}",
    })
