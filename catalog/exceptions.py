"""shared drf exception handling so every endpoint returns errors in
the same shape instead of each view improvising its own error body
"""

from rest_framework.views import exception_handler


def catalog_exception_handler(exc, context):
    """wrap drf's default handler and normalize the error payload

    the default response already has the right status code, this
    just makes sure the body always has a top level "detail" key so
    api consumers do not need to branch on exception type
    """

    response = exception_handler(exc, context)

    if response is not None and "detail" not in response.data:
        response.data = {"detail": response.data}

    return response
