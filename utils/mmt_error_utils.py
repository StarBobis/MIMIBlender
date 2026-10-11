


class Fatal(Exception):
    pass


class MMTErrorUtils:

    @staticmethod
    def raise_fatal(error_message:str):
        raise Fatal(error_message)


