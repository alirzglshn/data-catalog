

from rest_framework.views import exception_handler


def catalog_exception_handler(exc, context):
    """wrap drf's default handler and normalize the error payload
    """

    response = exception_handler(exc, context)

    if response is not None and "detail" not in response.data:
        response.data = {"detail": response.data}

    return response
