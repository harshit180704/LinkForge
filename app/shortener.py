ALPHABET = (
    "0123456789"
    "abcdefghijklmnopqrstuvwxyz"
    "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
)


def encode_base62(number: int) -> str:
    if number < 0:
        raise ValueError("ID cannot be negative")

    if number == 0:
        return "0"

    result = ""

    while number:
        number, remainder = divmod(number, 62)
        result = ALPHABET[remainder] + result

    return result


def decode_base62(code: str) -> int:
    number = 0

    for char in code:
        number = number * 62 + ALPHABET.index(char)

    return number
