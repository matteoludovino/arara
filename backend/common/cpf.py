import re


def normalize_cpf(raw: str) -> str:
    return re.sub(r"\D", "", raw)


def is_valid_cpf(cpf: str) -> bool:
    if len(cpf) != 11 or not cpf.isdigit() or len(set(cpf)) == 1:
        return False
    for size in (9, 10):
        total = sum(int(d) * w for d, w in zip(cpf[:size], range(size + 1, 1, -1), strict=True))
        digit = (total * 10) % 11 % 10
        if digit != int(cpf[size]):
            return False
    return True
