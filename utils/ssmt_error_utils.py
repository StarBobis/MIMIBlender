


class Fatal(Exception):
    pass


class SSMTErrorUtils:

    @staticmethod
    def raise_fatal(error_message:str):
        raise Fatal(error_message)


