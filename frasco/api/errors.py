
class ApiError(Exception):
    def __init__(self, message, http_code=500):
        self.message = message
        self.http_code = http_code

    def __str__(self):
        return str(self.message)


class ApiInputError(ApiError):
    def __init__(self, message="Invalid Request"):
        super(ApiInputError, self).__init__(message, 400)


class ApiAuthentificationRequiredError(ApiError):
    def __init__(self, message="Authentification Required"):
        super(ApiAuthentificationRequiredError, self).__init__(message, 401)


class ApiNotAuthorizedError(ApiError):
    def __init__(self, message="Not Authorized"):
        super(ApiNotAuthorizedError, self).__init__(message, 403)


class ApiNotFoundError(ApiError):
    def __init__(self, message="Not Found"):
        super(ApiNotFoundError, self).__init__(message, 404)
